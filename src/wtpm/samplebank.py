from __future__ import annotations

import json
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

SYNTH_FILES = ("library/default-synths-extra.scd", "synths/default-synths.scd")
SYNTH_HELPERS = frozenset({"debug", "dirt_from", "in", "in1", "inr"})
SYNTHDEF = re.compile(r"SynthDef\(\s*\\(\w+)")
AUDIO_SUFFIXES = frozenset({".wav", ".aif", ".aiff", ".aifc"})
SYNTH_ROLES = {
    name: role
    for role, names in {
        "kick": "superkick soskick",
        "snare": "supersnare sossnare superclap",
        "hat": "superhat soshats",
        "perc": "sostoms superhex dirac imp gabor cyclo",
        "bass": "superreese super808",
        "stab": "superpiano superfm superchip superfork supermandolin supervibe superpwm supersquare supersaw "
        "supergong psin pmsin",
        "lead": "superhoover supertron superzow supercomparator",
        "pad": "superhammond",
        "noise": "supernoise superstatic",
        "fx": "supersiren supergrind superprimes superwavemechanics",
    }.items()
    for name in names.split()
}
NAME_ROLES = [
    (re.compile(pattern), role)
    for pattern, role in [
        (r"bass", "bass"),
        (r"kick|^\d*bd\d*$", "kick"),
        (r"^\d*(sn|sd|cp)\d*$|clap", "snare"),
        (r"^\d*(hh|cy|oh)\d*$|hat|^ho$|cymbal|ride|crash|^(cc|cr)$", "hat"),
        (r"^808(ht|mt|lt|lc|mc)$|^(ht|mt|lt|cb)$", "perc"),
        (r"break|amen|loop", "perc"),
        (r"numbers|speak|speech|diphone|voice|vox|mouth|alphabet|kurt", "voice"),
        (r"pad", "pad"),
        (r"piano|arp|key|gtr|sax|sitar|superpiano|notes|moog|juno|pluck", "stab"),
        (r"tabla|conga|perc|drum|tok|clak|hand|bottle|glass", "perc"),
        (r"vinyl|noise", "noise"),
        (r"nature|bird|wind|fire|sea|rain", "field"),
        (r"^(invaders|cosmicg|tacscan|space|subroc3d|incoming|bleep|blip|feelfx)$", "fx"),
        (r"^dr(\d+|_few)?$|^gretsch$", "perc"),
        (r"^stab$", "stab"),
    ]
]


class SamplebankError(ValueError):
    pass


@dataclass(frozen=True)
class SampleRef:
    id: str
    path: Path | None
    duration: float | None
    role: str | None
    star: bool
    tags: list[str] = field(default_factory=list)
    synth: bool = False
    dirt_name: str | None = None


@dataclass(frozen=True)
class Locations:
    meta_path: Path
    cache_path: Path
    roots: dict[str, Path]
    superdirt_dir: Path


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
        superdirt_dir=Path(
            os.environ.get(
                "SAMPLEBANK_SUPERDIRT_DIR", "~/Library/Application Support/SuperCollider/downloaded-quarks/SuperDirt"
            )
        ).expanduser(),
    )


def load_library(
    *, meta_path: Path, cache_path: Path, roots: dict[str, Path], superdirt_dir: Path | None = None
) -> list[SampleRef]:
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
        library.append(
            SampleRef(
                id=sample_id,
                path=path,
                duration=float(duration),
                role=info["role"],
                star=bool(info.get("star", False)),
                tags=list(info.get("tags", [])),
            )
        )
    if superdirt_dir is not None:
        library += _synths(superdirt_dir, meta)
    return library


def _synths(superdirt_dir: Path, meta: dict) -> list[SampleRef]:
    names: set[str] = set()
    for relative in SYNTH_FILES:
        try:
            names.update(SYNTHDEF.findall((Path(superdirt_dir) / relative).read_text(encoding="utf-8")))
        except FileNotFoundError:
            continue
    synths = []
    for name in sorted(names - SYNTH_HELPERS):
        info = meta.get(f"synth/{name}", {})
        role = info.get("role") or _guess_synth_role(name)
        if role is None:
            continue
        synths.append(
            SampleRef(
                id=f"synth/{name}",
                path=None,
                duration=None,
                role=role,
                star=bool(info.get("star", False)),
                tags=["synth", *(t for t in info.get("tags", []) if t != "synth")],
                synth=True,
            )
        )
    return synths


def _guess_synth_role(name: str) -> str | None:
    if name in SYNTH_ROLES:
        return SYNTH_ROLES[name]
    lowered = name.lower()
    return next((role for pattern, role in NAME_ROLES if pattern.search(lowered)), None)


def _read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as error:
        raise SamplebankError(f"cannot read {path}: {error}") from error


def sample_library(locations: Locations, bank: str | None = None) -> list[SampleRef]:
    if bank:
        return load_bank(locations.roots["own"], bank)
    return load_library(
        meta_path=locations.meta_path,
        cache_path=locations.cache_path,
        roots=locations.roots,
        superdirt_dir=locations.superdirt_dir,
    )


def list_banks(root: Path) -> dict[str, dict[str, int]]:
    banks: dict[str, dict[str, int]] = {}
    for bank, role, folder in _bank_folders(root):
        banks.setdefault(bank, {})[role] = len(_audio_files(folder))
    return {bank: dict(sorted(roles.items())) for bank, roles in sorted(banks.items())}


def load_bank(root: Path, name: str) -> list[SampleRef]:
    samples = [
        SampleRef(
            id=f"bank/{name}/{folder.name}/{path.name}",
            path=path,
            duration=_wav_seconds(path),
            role=role,
            star=False,
            dirt_name=f"{folder.name}:{index}",
        )
        for bank, role, folder in _bank_folders(root)
        if bank == name
        for index, path in enumerate(_audio_files(folder))
    ]
    if not samples:
        raise SamplebankError(f"no sample bank named {name!r} in {root}")
    return samples


def _bank_folders(root: Path) -> list[tuple[str, str, Path]]:
    vocabulary = _read_json(Path(root) / "vocabulary.json", default=None)
    if vocabulary is None:
        raise SamplebankError(f"role vocabulary not found: {Path(root) / 'vocabulary.json'}")
    roles = {entry["id"] for entry in vocabulary.get("roles", [])}
    folders = []
    for folder in sorted(Path(root).iterdir()):
        bank, _, role = folder.name.rpartition("_")
        if folder.is_dir() and bank and role in roles and _audio_files(folder):
            folders.append((bank, role, folder))
    return folders


def _audio_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES)


def _wav_seconds(path: Path) -> float | None:
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    offset, byte_rate, size = 12, None, None
    while offset + 8 <= len(data):
        chunk, length = data[offset : offset + 4], struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        if chunk == b"fmt ":
            byte_rate = struct.unpack("<I", data[offset + 16 : offset + 20])[0]
        elif chunk == b"data":
            size = length
        offset += 8 + length + (length & 1)
    return size / byte_rate if byte_rate and size is not None else None
