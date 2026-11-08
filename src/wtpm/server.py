from __future__ import annotations

import json
import os
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .compose import DEFAULT_PRESET, ComposeError, compose, load_preset
from .config import AnalysisConfig
from .export import to_json
from .manifest import MANIFEST, load_manifest
from .pipeline import Pipeline
from .strudel import render_strudel

WEB_ROOT = Path(__file__).parent / "web"
FILES = {
    "/": ("sound.html", "text/html; charset=utf-8"),
    "/sound": ("sound.html", "text/html; charset=utf-8"),
    "/sound.js": ("sound.js", "text/javascript; charset=utf-8"),
    "/sound.css": ("sound.css", "text/css; charset=utf-8"),
}
MAX_TEXT = 2000
MOTIF_LENGTHS = (2, 3, 4, 5, 6, 7, 8)


class RequestError(ValueError):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class App:
    def __init__(self, model: str | None = None) -> None:
        self.pipeline = Pipeline(language="de", model=model)
        self.preset = load_preset(DEFAULT_PRESET)
        self.library = load_manifest()
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.samples = {"base": manifest["base"], "map": {s["s"]: s["file"] for s in manifest["samples"]}}
        self._lock = threading.Lock()

    def sonify(self, payload: dict) -> dict:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RequestError(HTTPStatus.BAD_REQUEST, "text must be a non-empty string")
        if len(text) > MAX_TEXT:
            raise RequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"text is longer than {MAX_TEXT} characters")
        seed = payload.get("sample_seed")
        config = AnalysisConfig(
            sequence_lengths=MOTIF_LENGTHS,
            surface_comparison="case_insensitive",
            break_on_punctuation=True,
            break_on_lines=False,
            normalise_parser_input=True,
        )
        with self._lock:
            analysis = json.loads(to_json(self.pipeline.analyze(text, config), indent=None))
        score = compose(analysis, self.preset, self.library, sample_seed=str(seed) if seed else None)
        return {"analysis": analysis, "score": score, "strudel": render_strudel(score)}


class Handler(BaseHTTPRequestHandler):
    server_version = "wtpm"
    app: App

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/samples":
            self._json(HTTPStatus.OK, self.app.samples)
        elif path in FILES:
            name, content_type = FILES[path]
            self._send(HTTPStatus.OK, content_type, (WEB_ROOT / name).read_bytes())
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/sonify":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise RequestError(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
            self._json(HTTPStatus.OK, self.app.sonify(payload))
        except json.JSONDecodeError as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {error}"})
        except RequestError as error:
            self._json(error.status, {"error": str(error)})
        except ComposeError as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            traceback.print_exc()
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(error).__name__}: {error}"})

    def _json(self, status: HTTPStatus, payload: dict) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def serve(host: str, port: int) -> None:
    bound = type("BoundHandler", (Handler,), {"app": App()})
    httpd = ThreadingHTTPServer((host, port), bound)
    print(f"wtpm running at http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    serve(os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000")))
