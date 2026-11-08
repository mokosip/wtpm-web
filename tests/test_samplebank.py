from __future__ import annotations

import json
import wave

import pytest

from wtpm.samplebank import SamplebankError, default_locations, list_banks, load_bank, load_library


def write_wav(path, seconds, rate=1000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(seconds * rate))


def bank_root(tmp_path):
    root = tmp_path / "own"
    root.mkdir()
    roles = [{"id": role} for role in ("kick", "snare", "hat", "pad", "stab")]
    (root / "vocabulary.json").write_text(json.dumps({"version": 1, "roles": roles}))
    write_wav(root / "test_kick" / "01_b.wav", 0.4)
    write_wav(root / "test_kick" / "00_a.WAV", 0.3)
    (root / "test_kick" / "notes.txt").write_text("not audio")
    write_wav(root / "test_pad" / "00_wide.wav", 2.5)
    write_wav(root / "other_snare" / "00_x.wav", 0.2)
    write_wav(root / "heavy_rain" / "00_rain.wav", 3.0)
    return root


def test_banks_are_folders_named_bank_underscore_role(tmp_path):
    assert list_banks(bank_root(tmp_path)) == {"other": {"snare": 1}, "test": {"kick": 2, "pad": 1}}


def test_a_bank_holds_its_audio_files_with_folder_role_and_length(tmp_path):
    root = bank_root(tmp_path)
    samples = load_bank(root, "test")
    assert [(s.id, s.role, s.path) for s in samples] == [
        ("bank/test/test_kick/00_a.WAV", "kick", root / "test_kick" / "00_a.WAV"),
        ("bank/test/test_kick/01_b.wav", "kick", root / "test_kick" / "01_b.wav"),
        ("bank/test/test_pad/00_wide.wav", "pad", root / "test_pad" / "00_wide.wav"),
    ]
    assert [s.duration for s in samples] == pytest.approx([0.3, 0.4, 2.5])
    assert not any(s.synth for s in samples)


def test_an_unknown_bank_is_reported(tmp_path):
    with pytest.raises(SamplebankError, match="no sample bank named 'nope'"):
        load_bank(bank_root(tmp_path), "nope")


def test_bank_samples_carry_their_superdirt_name_and_index(tmp_path):
    root = bank_root(tmp_path)
    (root / "test_kick" / "00_b.aif").write_bytes(b"FORM")
    assert [(s.path.name, s.dirt_name) for s in load_bank(root, "test")] == [
        ("00_a.WAV", "test_kick:0"),
        ("00_b.aif", "test_kick:1"),
        ("01_b.wav", "test_kick:2"),
        ("00_wide.wav", "test_pad:0"),
    ]


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
    assert [(s.id, s.role, s.duration, s.star) for s in library] == [("dirt/pluck/a.wav", "stab", 2.0, True)]
    assert library[0].path == bank_dir / "a.wav"


def test_missing_analysis_cache_is_reported(tmp_path):
    with pytest.raises(SamplebankError, match="analysis cache not found"):
        load_library(meta_path=tmp_path / "m.json", cache_path=tmp_path / "c.json", roots={})


def test_superdirt_synths_join_the_library_with_their_role(tmp_path):
    quark = tmp_path / "SuperDirt"
    (quark / "library").mkdir(parents=True)
    (quark / "synths").mkdir()
    (quark / "library" / "default-synths-extra.scd").write_text(
        "SynthDef(\\superreese, { |out| }).add;\nSynthDef(\\superpiano, {}).add;\nSynthDef(\\mysuperbass, {}).add;"
    )
    (quark / "synths" / "default-synths.scd").write_text("SynthDef(\\debug, {}).add; SynthDef(\\zzz, {}).add;")
    meta = tmp_path / "samplebank.json"
    meta.write_text(json.dumps({"synth/superpiano": {"role": "pad", "tags": ["warm"], "star": True}}))
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"entries": {}}))
    library = load_library(meta_path=meta, cache_path=cache, roots={}, superdirt_dir=quark)
    assert {s.id: (s.role, s.tags, s.star, s.synth, s.path, s.duration) for s in library} == {
        "synth/mysuperbass": ("bass", ["synth"], False, True, None, None),
        "synth/superpiano": ("pad", ["synth", "warm"], True, True, None, None),
        "synth/superreese": ("bass", ["synth"], False, True, None, None),
    }


def test_superdirt_location_follows_the_samplebank_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SAMPLEBANK_SUPERDIRT_DIR", str(tmp_path / "quark"))
    assert default_locations().superdirt_dir == tmp_path / "quark"
