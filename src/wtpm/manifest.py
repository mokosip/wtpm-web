from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

from .samplebank import SampleRef, default_locations, load_library

MANIFEST = Path(__file__).parent / "samples.json"
DIRT_COMMIT = "c74fc80f8db8038f6a33648ffef5ac00a07ad402"
DIRT_BASE = f"https://raw.githubusercontent.com/tidalcycles/Dirt-Samples/{DIRT_COMMIT}/"
BASS_SYNTH = "sawtooth"


def build_manifest(library: list[SampleRef], strudel_map: dict[str, Any], base: str) -> dict[str, Any]:
    files = {file for key, entries in strudel_map.items() if not key.startswith("_") for file in entries}
    samples, missing, names = [], [], set()
    for sample in sorted(library, key=lambda s: s.id):
        root, _, file = sample.id.partition("/")
        if root != "dirt" or sample.synth:
            continue
        if file not in files:
            missing.append(sample.id)
            continue
        folder, _, name = file.partition("/")
        s = re.sub(r"\W", "_", f"{folder}_{Path(name).stem}")
        if s in names:
            raise ValueError(f"two samples map to the Strudel name {s}")
        names.add(s)
        samples.append({"id": sample.id, "role": sample.role, "duration": sample.duration, "s": s, "file": file})
    return {
        "base": base,
        "samples": samples,
        "synths": [{"id": f"synth/{BASS_SYNTH}", "role": "bass"}],
        "missing": missing,
    }


def load_manifest(path: Path = MANIFEST) -> list[SampleRef]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    library = [
        SampleRef(id=s["id"], path=None, duration=s["duration"], role=s["role"], s=s["s"])
        for s in data["samples"]
    ]
    return library + [
        SampleRef(id=s["id"], path=None, duration=None, role=s["role"], synth=True) for s in data["synths"]
    ]


def main() -> int:
    locations = default_locations()
    library = load_library(meta_path=locations.meta_path, cache_path=locations.cache_path, roots=locations.roots)
    with urllib.request.urlopen(f"{DIRT_BASE}strudel.json", timeout=30) as response:
        strudel_map = json.load(response)
    manifest = build_manifest(library, strudel_map, DIRT_BASE)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(manifest['samples'])} samples, {len(manifest['missing'])} not in Dirt-Samples@{DIRT_COMMIT[:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
