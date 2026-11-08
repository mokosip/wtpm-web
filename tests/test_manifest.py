from __future__ import annotations

import json
from pathlib import Path

from test_compose import layer, make_preset, pilger, pipeline  # noqa: F401

from wtpm.compose import compose
from wtpm.manifest import BASS_SYNTH, MANIFEST, build_manifest, load_manifest
from wtpm.samplebank import SampleRef

BASE = "https://raw.githubusercontent.com/tidalcycles/Dirt-Samples/abc/"
STRUDEL_MAP = {
    "_base": "https://raw.githubusercontent.com/tidalcycles/Dirt-Samples/master/",
    "bd": ["bd/BT0A0A7.wav", "bd/BT0A0D0.wav"],
    "sn": ["sn/ST0T0S0.wav"],
    "pad": ["pad/long-pad.wav"],
}


def _ref(sample_id, role, duration=0.4):
    return SampleRef(id=sample_id, path=Path("/x") / sample_id, duration=duration, role=role)


LIBRARY = [
    _ref("dirt/bd/BT0A0D0.wav", "kick"),
    _ref("dirt/sn/ST0T0S0.wav", "snare"),
    _ref("dirt/pad/long-pad.wav", "pad", 3.5),
    _ref("dirt/gone/missing.wav", "perc"),
    _ref("own/mine/kick.wav", "kick"),
]


def test_the_manifest_keeps_only_dirt_samples_strudel_can_load_each_under_its_own_name():
    manifest = build_manifest(LIBRARY, STRUDEL_MAP, BASE)
    assert manifest["base"] == BASE
    assert manifest["samples"] == [
        {"id": "dirt/bd/BT0A0D0.wav", "role": "kick", "duration": 0.4, "s": "bd_BT0A0D0", "file": "bd/BT0A0D0.wav"},
        {"id": "dirt/pad/long-pad.wav", "role": "pad", "duration": 3.5, "s": "pad_long_pad", "file": "pad/long-pad.wav"},
        {"id": "dirt/sn/ST0T0S0.wav", "role": "snare", "duration": 0.4, "s": "sn_ST0T0S0", "file": "sn/ST0T0S0.wav"},
    ]
    assert manifest["missing"] == ["dirt/gone/missing.wav"]
    assert manifest["synths"] == [{"id": f"synth/{BASS_SYNTH}", "role": "bass"}]


def test_the_shipped_manifest_loads_as_a_library_with_strudel_names(tmp_path):
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(build_manifest(LIBRARY, STRUDEL_MAP, BASE)), encoding="utf-8")
    library = load_manifest(path)
    assert [(s.id, s.role, s.s, s.synth) for s in library] == [
        ("dirt/bd/BT0A0D0.wav", "kick", "bd_BT0A0D0", False),
        ("dirt/pad/long-pad.wav", "pad", "pad_long_pad", False),
        ("dirt/sn/ST0T0S0.wav", "snare", "sn_ST0T0S0", False),
        (f"synth/{BASS_SYNTH}", "bass", None, True),
    ]
    assert MANIFEST.name == "samples.json"


def test_the_shipped_manifest_feeds_every_layer_and_the_same_seed_draws_the_same(pilger):  # noqa: F811
    library = load_manifest()
    names = {s.s for s in library if not s.synth}
    first = compose(pilger, make_preset(), library, sample_seed="x")
    assert all(layer(first, name)["events"] for name in ("puls", "bass", "motiv", "boegen"))
    assert all(s["s"] in names for s in first["samples"] if not s["synth"])
    assert {e["s"] for e in layer(first, "bass")["events"]} == {BASS_SYNTH}
    assert compose(pilger, make_preset(), library, sample_seed="x")["samples"] == first["samples"]
    assert compose(pilger, make_preset(), library, sample_seed="y")["samples"] != first["samples"]
