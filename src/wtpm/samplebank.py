from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


class SamplebankError(ValueError):
    pass


@dataclass(frozen=True)
class SampleRef:
    id: str
    path: Path | None
    duration: float | None
    role: str | None
    synth: bool = False
    s: str | None = None


@dataclass(frozen=True)
class Locations:
    meta_path: Path
    cache_path: Path
    roots: dict[str, Path]


def default_locations() -> Locations:
    tidal = Path(os.environ.get("SAMPLEBANK_TIDAL_DIR", "~/tidal")).expanduser()
    defaults = {
        "dirt": "~/Library/Application Support/SuperCollider/downloaded-quarks/Dirt-Samples",
        "dub": str(tidal / "dub" / "sounds"),
        "own": str(tidal / "samples"),
    }
    roots = {
        key: Path(os.environ.get(f"SAMPLEBANK_ROOT_{key.upper()}", value)).expanduser()
        for key, value in defaults.items()
    }
    return Locations(
        meta_path=Path(
            os.environ.get("SAMPLEBANK_META_PATH", roots["own"] / "samplebank.json")
        ).expanduser(),
        cache_path=Path(
            os.environ.get("SAMPLEBANK_CACHE_PATH", roots["own"] / ".samplebank-cache.json")
        ).expanduser(),
        roots=roots,
    )


def load_library(*, meta_path: Path, cache_path: Path, roots: dict[str, Path]) -> list[SampleRef]:
    meta = _read_json(meta_path, default={})
    cache = _read_json(cache_path, default=None)
    if cache is None:
        raise SamplebankError(f"samplebank analysis cache not found: {cache_path}")
    entries = cache.get("entries", {})

    library = []
    for sample_id, info in sorted(meta.items()):
        if "role" not in info or sample_id not in entries:
            continue
        parts = sample_id.split("/", 2)
        if len(parts) != 3 or parts[0] not in roots:
            continue
        path = (roots[parts[0]] / parts[1] / parts[2]).resolve()
        duration = entries[sample_id].get("features", {}).get("duration") or 0.0
        if duration <= 0 or not path.is_file():
            continue
        library.append(SampleRef(id=sample_id, path=path, duration=float(duration), role=info["role"]))
    return library


def _read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as error:
        raise SamplebankError(f"cannot read {path}: {error}") from error
