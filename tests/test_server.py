from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from wtpm.manifest import MANIFEST
from wtpm.server import MAX_TEXT, App, Handler


@pytest.fixture(scope="module")
def base_url():
    bound = type("BoundHandler", (Handler,), {"app": App(model="de_core_news_sm")})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bound)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.status, response.headers.get("Content-Type"), response.read()


def _post(url, payload):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_sonify_turns_a_text_and_seed_into_score_and_strudel_voices(base_url):
    status, body = _post(f"{base_url}/api/sonify", {"text": "Der Hund bellt.\nDer Hund schläft.", "sample_seed": "a"})
    assert status == 200
    assert body["analysis"]["tokens"] and body["analysis"]["sentences"]
    assert body["score"]["sample_seed"] == "a"
    assert body["strudel"]["cps"] == body["score"]["tempo"]["cps"]
    assert {voice["layer"] for voice in body["strudel"]["voices"]} >= {"puls", "motiv"}
    again = _post(f"{base_url}/api/sonify", {"text": "Der Hund bellt.\nDer Hund schläft.", "sample_seed": "a"})[1]
    assert again["strudel"] == body["strudel"]


@pytest.mark.parametrize(
    ("payload", "status", "message"),
    [
        ({"text": "   "}, 400, "text"),
        ({"text": "Wort " * (MAX_TEXT // 5 + 1)}, 413, str(MAX_TEXT)),
        ({"text": 5}, 400, "text"),
    ],
)
def test_sonify_refuses_empty_too_long_or_malformed_text(base_url, payload, status, message):
    code, body = _post(f"{base_url}/api/sonify", payload)
    assert code == status and message in body["error"]


def test_the_sample_map_names_every_manifest_sample_for_strudel(base_url):
    status, _, raw = _get(f"{base_url}/api/samples")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert status == 200
    assert json.loads(raw) == {"base": manifest["base"], "map": {s["s"]: s["file"] for s in manifest["samples"]}}


@pytest.mark.parametrize("path", ["/", "/sound"])
def test_the_sound_page_is_the_only_page_and_loads_pinned_strudel(base_url, path):
    status, content_type, raw = _get(f"{base_url}{path}")
    assert status == 200 and content_type.startswith("text/html")
    assert b"https://unpkg.com/@strudel/web@1.3.0" in raw


@pytest.mark.parametrize("path", ["/api/analyze", "/api/favorites", "/index.html", "/../pyproject.toml"])
def test_everything_else_is_not_found(base_url, path):
    with pytest.raises(urllib.error.HTTPError) as error:
        _get(f"{base_url}{path}")
    assert error.value.code == 404
