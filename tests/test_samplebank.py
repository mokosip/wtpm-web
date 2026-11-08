from __future__ import annotations

import json

import pytest

from wtpm.samplebank import SamplebankError, load_library


def test_library_holds_every_playable_sample_with_a_set_role(tmp_path):
    bank_dir = tmp_path / "dirt" / "pluck"
    bank_dir.mkdir(parents=True)
    for name in ("a.wav", "b.wav", "c.wav", "empty.wav"):
        (bank_dir / name).write_bytes(b"x")
    meta = tmp_path / "samplebank.json"
    meta.write_text(
        json.dumps(
            {
                "dirt/pluck/a.wav": {"role": "stab", "star": True},
                "dirt/pluck/b.wav": {"tags": ["warm"]},
                "dirt/pluck/c.wav": {"type": "tonal"},
                "dirt/pluck/empty.wav": {"role": "stab"},
                "dirt/pluck/gone.wav": {"role": "stab"},
            }
        )
    )
    cache = tmp_path / "cache.json"
    cache.write_text(
        json.dumps(
            {
                "entries": {
                    f"dirt/pluck/{name}": {"key": [0, 1], "features": {"duration": duration}}
                    for name, duration in (("a.wav", 2.0), ("b.wav", 1.0), ("c.wav", 1.0), ("empty.wav", 0.0), ("gone.wav", 1.0))
                }
            }
        )
    )
    library = load_library(meta_path=meta, cache_path=cache, roots={"dirt": tmp_path / "dirt"})
    assert [(s.id, s.role, s.duration) for s in library] == [("dirt/pluck/a.wav", "stab", 2.0)]
    assert library[0].path == bank_dir / "a.wav"


def test_missing_analysis_cache_is_reported(tmp_path):
    with pytest.raises(SamplebankError, match="analysis cache not found"):
        load_library(meta_path=tmp_path / "m.json", cache_path=tmp_path / "c.json", roots={})
