from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .samplebank import SampleRef

SCORE_SCHEMA = "wtpm-compose/1"
DEFAULT_PRESET = Path(__file__).parent / "presets" / "default.json"
LAYERS = ("puls", "bass", "motiv", "boegen", "leitwort")
MIN_SCHEMA = (1, 1)
LINE_AWARE_TYPES = ("pos_ngram", "dependency")


class ComposeError(ValueError):
    pass


@dataclass(frozen=True)
class Pick:
    layer: str
    sample: SampleRef
    long: bool

    @property
    def s(self) -> str:
        return self.sample.id.removeprefix("synth/") if self.sample.synth else self.sample.s


@dataclass(frozen=True)
class LayerPool:
    roles: frozenset[str]
    count: int
    long_only: bool
    synth: bool = False
    octave: int = 5


@dataclass(frozen=True)
class Span:
    low: float
    high: float

    def norm(self, value: float) -> float:
        return min(max((value - self.low) / (self.high - self.low), 0.0), 1.0)


def _span(values: list[float]) -> Span:
    low, high = (float(v) for v in values)
    if not low < high:
        raise ComposeError(f"profile range needs low < high, got {values}")
    return Span(low, high)


@dataclass(frozen=True)
class ComposePreset:
    sentence_words: Span
    bpm_range: tuple[float, float]
    verb_share: Span
    beats_per_bar: int
    steps_per_bar: int
    min_bars: int
    root: int
    intervals: tuple[int, ...]
    function_pos: frozenset[str]
    pos_degrees: dict[str, int]
    pools: dict[str, LayerPool]
    mix: dict[str, float]
    long_min_seconds: float
    long_roles: frozenset[str]
    puls_min_hits: int
    puls_gain: tuple[float, float]
    motif_gain: dict[str, float]
    motif_exclude: frozenset[tuple[str, ...]]
    echo: dict[str, float]
    data: dict[str, Any] = field(compare=False, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComposePreset":
        try:
            preset = cls(
                sentence_words=_span(data["profile"]["tempo"]["sentence_words"]),
                bpm_range=(float(data["profile"]["tempo"]["bpm"][0]), float(data["profile"]["tempo"]["bpm"][1])),
                verb_share=_span(data["profile"]["variation"]["verb_share"]),
                beats_per_bar=int(data["tempo"]["beats_per_bar"]),
                steps_per_bar=int(data["tempo"]["steps_per_bar"]),
                min_bars=int(data["bars"]["min"]),
                root=int(data["scale"]["root"]),
                intervals=tuple(int(i) for i in data["scale"]["intervals"]),
                function_pos=frozenset(data["function_pos"]),
                pos_degrees={pos: int(d) for pos, d in data["pos_degrees"].items()},
                pools={
                    name: LayerPool(
                        roles=frozenset(spec["roles"]),
                        count=int(spec["samples"]),
                        long_only=bool(spec.get("long_only", False)),
                        synth=bool(spec.get("synth", False)),
                        octave=int(spec.get("octave", 5)),
                    )
                    for name, spec in data["layers"].items()
                },
                mix={name: float(level) for name, level in data["mix"].items()},
                long_min_seconds=float(data["long"]["min_seconds"]),
                long_roles=frozenset(data["long"]["roles"]),
                puls_min_hits=int(data["puls"]["min_hits"]),
                puls_gain=(float(data["puls"]["gain"][0]), float(data["puls"]["gain"][1])),
                motif_gain={kind: float(data["motif"]["gain"][kind]) for kind in ("function", "content")},
                motif_exclude=frozenset(tuple(values) for values in data["motif"]["exclude"]),
                echo={name: float(value) for name, value in data["echo"].items()},
                data=data,
            )
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise ComposeError(f"invalid compose preset: {error!r}") from error
        preset._validate()
        return preset

    def _validate(self) -> None:
        if self.min_bars < 1:
            raise ComposeError("bars: need min >= 1")
        if not self.intervals:
            raise ComposeError("scale needs at least one interval")
        if set(self.pools) != set(LAYERS):
            raise ComposeError(f"layers must define a sample pool for each of {LAYERS}")
        for name, pool in self.pools.items():
            if not pool.roles or pool.count < 1:
                raise ComposeError(f"layer {name}: needs at least one role and one sample")
        if set(self.mix) != set(LAYERS):
            raise ComposeError(f"mix must set a level for each of {LAYERS}")
        for name, level in self.mix.items():
            if not 0 < level <= 2:
                raise ComposeError(f"mix level for {name} must be in (0, 2], got {level}")

    def is_long(self, sample: SampleRef) -> bool:
        return (
            not sample.synth and sample.role in self.long_roles and sample.duration >= self.long_min_seconds
        )

    def tempo(self, bpm: float) -> dict[str, Any]:
        return {
            "bpm": bpm,
            "beats_per_bar": self.beats_per_bar,
            "steps_per_bar": self.steps_per_bar,
            "cps": bpm / 60 / self.beats_per_bar,
        }


def _profile(analysis: dict[str, Any], preset: ComposePreset) -> dict[str, Any]:
    eligible = {t["id"] for t in analysis["tokens"] if t["eligible"]}
    lengths = [n for n in (sum(1 for i in s["token_ids"] if i in eligible) for s in analysis["sentences"]) if n]
    sentence_words = sum(lengths) / len(lengths) if lengths else 0.0
    norm = preset.sentence_words.norm(sentence_words)
    fast, slow = preset.bpm_range
    words = [t for t in analysis["tokens"] if t["eligible"]]
    verbs = sum(1 for t in words if t["pos"] == "VERB")
    nouns = sum(1 for t in words if t["pos"] in ("NOUN", "PROPN"))
    verb_share = verbs / (verbs + nouns) if verbs + nouns else 0.0
    return {
        "tempo": {
            "sentence_words": round(sentence_words, 3),
            "norm": round(norm, 3),
            "bpm": round(fast + (slow - fast) * norm),
        },
        "variation": {
            "verb_share": round(verb_share, 3),
            "norm": round(preset.verb_share.norm(verb_share), 3),
        },
    }


def _word_at(ids: list[str], step: int, preset: ComposePreset) -> int:
    spb = preset.steps_per_bar
    starts = [min(round(k / len(ids) * spb), spb - 1) for k in range(len(ids))]
    return max((k for k, start in enumerate(starts) if start <= step % spb), default=0)


def _echo_words(analysis: dict[str, Any]) -> dict[str, list[str]]:
    tokens = {t["id"]: t for t in analysis["tokens"]}
    position = {t["id"]: n for n, t in enumerate(t for t in analysis["tokens"] if t["eligible"])}
    echo: dict[str, list[str]] = {}
    for pattern in analysis["patterns"]:
        if pattern["type"] != "surface" or pattern["length"] < 2 or pattern["count"] < 2:
            continue
        for occurrence in sorted(pattern["occurrences"], key=lambda o: position[o["token_ids"][0]])[1:]:
            words = [tokens[i]["text"] for i in occurrence["token_ids"]]
            for token_id in occurrence["token_ids"]:
                if len(words) > len(echo.get(token_id, [])):
                    echo[token_id] = words
    eligible = [t for t in analysis["tokens"] if t["eligible"]]
    for before, token in zip(eligible, eligible[1:]):
        same = before["text"].casefold() == token["text"].casefold()
        if same and before["sentence_id"] == token["sentence_id"] and token["id"] not in echo:
            echo[token["id"]] = [token["text"]]
    return echo


def _apply_echo(layers, verses, echo: dict[str, list[str]], preset: ComposePreset) -> None:
    for layer in layers:
        for event in layer["events"]:
            ids = verses[event["bar"]]["token_ids"]
            words = echo.get(ids[_word_at(ids, event["step"], preset)])
            if words:
                event["echo"] = dict(preset.echo)
                event["source"]["echo"] = words


def load_preset(path: str | Path) -> ComposePreset:
    with open(path, encoding="utf-8") as handle:
        return ComposePreset.from_dict(json.load(handle))


def compose(
    analysis: dict[str, Any],
    preset: ComposePreset,
    library: list[SampleRef],
    sample_seed: str | None = None,
) -> dict[str, Any]:
    _validate_input(analysis)
    form, verses = _verses(analysis, preset)
    tokens = {t["id"]: t for t in analysis["tokens"]}
    seed = _seed(analysis)
    profile = _profile(analysis, preset)
    motifs = _verse_motifs(analysis, verses, preset)
    sample_seed = sample_seed or _hash({"preset": preset.data})
    bass_notes = _bass_notes(verses, tokens, preset)
    picks, pools = _pick_samples(preset, library, sample_seed)
    builders = {
        "puls": lambda: _puls(
            verses, tokens, preset, picks["puls"],
            _puls_variation(sample_seed, profile["variation"]["norm"], len(picks["puls"]), preset),
        ),
        "bass": lambda: {"name": "bass", "events": _bass(bass_notes, preset, picks["bass"])},
        "motiv": lambda: _motiv(analysis, motifs, preset, picks["motiv"]),
        "boegen": lambda: {"name": "boegen", "events": _boegen(analysis, verses, tokens, preset, picks["boegen"])},
        "leitwort": lambda: {"name": "leitwort", "events": _leitwort(verses, tokens, preset, picks["leitwort"])},
    }
    layers = [builders[name]() for name in LAYERS]
    punctuation = apply_punctuation(layers, _punctuation_marks(analysis, verses, preset), preset)
    _apply_echo(layers, verses, _echo_words(analysis), preset)
    for layer in layers:
        level = preset.mix[layer["name"]]
        for event in layer["events"]:
            event["gain"] = round(event["gain"] * level, 4)
    return {
        "schema": SCORE_SCHEMA,
        "input": {
            "schema_version": analysis["schema_version"],
            "boundary_policy": analysis["analysis"]["settings"]["boundary_policy"],
            "manual_tokens": sum(
                1 for t in analysis["tokens"] if t["eligible"] and t.get("annotation_source") == "manual"
            ),
        },
        "seed": seed,
        "sample_seed": sample_seed,
        "pools": pools,
        "mix": dict(preset.mix),
        "punctuation": punctuation,
        "profile": profile,
        "tempo": preset.tempo(profile["tempo"]["bpm"]),
        "scale": {"root": preset.root, "intervals": list(preset.intervals)},
        "bars": len(verses),
        "form": form,
        "verses": verses,
        "layers": layers,
        "samples": [
            {
                "s": pick.s,
                "layer": pick.layer,
                "id": pick.sample.id,
                "role": pick.sample.role,
                "duration": pick.sample.duration,
                "synth": pick.sample.synth,
                "long": pick.long,
            }
            for layer in LAYERS
            for pick in picks[layer]
        ],
    }


def _pick_samples(
    preset: ComposePreset, library: list[SampleRef], sample_seed: str
) -> tuple[dict[str, list[Pick]], dict[str, int]]:
    picks: dict[str, list[Pick]] = {}
    sizes: dict[str, int] = {}
    for layer in LAYERS:
        pool = preset.pools[layer]
        candidates = sorted(
            (
                s
                for s in library
                if s.synth == pool.synth
                and s.role in pool.roles
                and (not pool.long_only or preset.is_long(s))
            ),
            key=lambda s: s.id,
        )
        if not candidates:
            kind = "synths" if pool.synth else "samples"
            requirement = f" of at least {preset.long_min_seconds:g} s" if pool.long_only else ""
            raise ComposeError(
                f"layer {layer}: no {kind} with role {sorted(pool.roles)}{requirement} in the samplebank"
            )
        sizes[layer] = len(candidates)
        chosen = random.Random(f"{sample_seed}:{layer}").sample(candidates, min(pool.count, len(candidates)))
        picks[layer] = [Pick(layer=layer, sample=sample, long=preset.is_long(sample)) for sample in chosen]
    return picks, sizes


def _validate_input(analysis: dict[str, Any]) -> None:
    version = str(analysis.get("schema_version", "0"))
    try:
        parsed = tuple(int(part) for part in version.split("."))
    except ValueError:
        parsed = (0,)
    if parsed < MIN_SCHEMA:
        raise ComposeError(f"analysis needs schema_version 1.1 or newer (verse crossings), got {version}")
    pos_of = {t["id"]: t["pos"] for t in analysis["tokens"]}
    for pattern in analysis["patterns"]:
        if pattern["type"] not in LINE_AWARE_TYPES:
            continue
        for occurrence in pattern["occurrences"]:
            if "crosses_line" not in occurrence:
                raise ComposeError(f"{pattern['pattern_id']}: occurrence without crosses_line")
            if pattern["type"] == "pos_ngram":
                actual = [pos_of[i] for i in occurrence["token_ids"]]
                if actual != pattern["values"]:
                    raise ComposeError(
                        f"{pattern['pattern_id']}: values {pattern['values']} do not match token POS {actual}"
                    )


def _seed(analysis: dict[str, Any]) -> str:
    return _hash({"text": analysis["document"]["text"]})


def _hash(material: dict[str, Any]) -> str:
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _event(
    preset: ComposePreset, bar: int, step: int, s: str, degree: int | None,
    gain: float, legato: float, source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "bar": bar,
        "step": bar * preset.steps_per_bar + step,
        "s": s,
        "note": None if degree is None else _note(preset, degree),
        "gain": round(gain, 4),
        "legato": legato,
        "source": dict(source),
    }


def _note(preset: ComposePreset, degree: int) -> int:
    octave, index = divmod(degree, len(preset.intervals))
    return preset.root + preset.intervals[index] + 12 * octave


def _puls_variation(sample_seed: str, probability: float, choices: int, preset: ComposePreset) -> dict[str, Any]:
    positions = []
    for step in range(preset.steps_per_bar):
        draw = random.Random(f"{sample_seed}:puls:{step}")
        chance, index = draw.random(), draw.randrange(choices)
        positions.append(index if chance < probability else 0)
    return {"probability": probability, "positions": positions}


def _puls(verses, tokens, preset: ComposePreset, picks: list[Pick], variation: dict[str, Any]) -> dict[str, Any]:
    low, high = preset.puls_gain
    events = []
    for verse in verses:
        words = [tokens[i] for i in verse["token_ids"]]
        spb = preset.steps_per_bar
        positions = sorted(
            {min(round(k / len(words) * spb), spb - 1) for k, w in enumerate(words) if w["pos"] in preset.function_pos}
        )
        beat = spb // preset.beats_per_bar
        strong = [0, 2 * beat, beat, 3 * beat]
        filled = [step for step in strong if step not in positions][: max(preset.puls_min_hits - len(positions), 0)]
        function_words = sum(1 for w in words if w["pos"] in preset.function_pos)
        gain = low + (high - low) * (function_words / len(words) if words else 0)
        source = {"unit": verse["unit_id"], "function_words": function_words, "positions": positions, "filled": filled}
        for step in sorted(positions + filled):
            sample = picks[variation["positions"][step]]
            events.append(_event(preset, verse["bar"], step, sample.s, None, gain, 1.0, source))
    return {"name": "puls", "events": events, "variation": variation}


VERB_POS = frozenset({"VERB", "AUX"})


def _position(index: int, count: int, steps: int, grid: int) -> int:
    return min(round(index / count * steps / grid) * grid, steps - grid)


def _depth(token: dict[str, Any], tokens: dict[str, dict[str, Any]]) -> int:
    depth = 0
    while token["head_id"] is not None:
        token = tokens[token["head_id"]]
        depth += 1
    return depth


def _bass_notes(verses, tokens, preset: ComposePreset) -> list[dict[str, Any]]:
    notes = []
    for verse in verses:
        ids = verse["token_ids"]
        for index, token_id in enumerate(ids):
            token = tokens[token_id]
            if token["pos"] not in VERB_POS:
                continue
            notes.append(
                {
                    "onset": verse["bar"] * preset.steps_per_bar + _position(index, len(ids), preset.steps_per_bar, 2),
                    "source": {
                        "unit": verse["unit_id"],
                        "token_id": token_id,
                        "text": token["text"],
                        "depth": _depth(token, tokens),
                    },
                }
            )
    loop = len(verses) * preset.steps_per_bar
    for note, following in zip(notes, notes[1:] + notes[:1]):
        note["hold"] = (following["onset"] - note["onset"]) % loop or loop
    return notes


def _bass(notes: list[dict[str, Any]], preset: ComposePreset, picks: list[Pick]) -> list[dict[str, Any]]:
    sample = picks[0]
    shift = (preset.pools["bass"].octave - 5) * 12 if sample.sample.synth else 0
    events = []
    for note in notes:
        bar, step = divmod(note["onset"], preset.steps_per_bar)
        event = _event(
            preset, bar, step, sample.s, note["source"]["depth"], 0.85, note["hold"],
            {**note["source"], "hold": note["hold"]},
        )
        event["note"] += shift
        events.append(event)
    return events


def _verse_motifs(analysis: dict[str, Any], verses, preset: ComposePreset) -> list[dict[str, Any] | None]:
    candidates = [
        p
        for p in analysis["patterns"]
        if p["type"] == "pos_ngram" and p["count"] >= 2 and p["length"] <= preset.steps_per_bar // 2
    ]
    motifs: list[dict[str, Any] | None] = []
    for verse in verses:
        index = {token_id: position for position, token_id in enumerate(verse["token_ids"])}
        best = None
        for pattern in candidates:
            for occurrence in pattern["occurrences"]:
                ids = occurrence["token_ids"]
                if all(token_id in index for token_id in ids):
                    standard = tuple(pattern["values"]) in preset.motif_exclude
                    key = (standard, -pattern["count"], -pattern["length"], index[ids[0]])
                    if best is None or key < best[0]:
                        best = (key, pattern, ids)
        if best is None:
            motifs.append(None)
            continue
        (standard, *_), pattern, ids = best
        spb = preset.steps_per_bar
        word_step = _position(index[ids[0]], len(index), spb, 2)
        motifs.append(
            {
                "bar": verse["bar"],
                "values": pattern["values"],
                "count": pattern["count"],
                "token_ids": ids,
                "standard": standard,
                "offset": min(word_step, spb - 2 * len(ids)),
            }
        )
    return motifs


def _frequency_rank(analysis: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in analysis["tokens"]:
        if token["eligible"]:
            counts[token["pos"]] = counts.get(token["pos"], 0) + 1
    return {pos: rank for rank, pos in enumerate(sorted(counts, key=lambda pos: (-counts[pos], pos)))}


def _motiv(analysis, motifs, preset: ComposePreset, picks: list[Pick]) -> dict[str, Any]:
    layer: dict[str, Any] = {"name": "motiv", "source": {"motifs": motifs}, "events": []}
    sample = picks[0]
    degree_of = _frequency_rank(analysis)
    for motif in motifs:
        if motif is None:
            continue
        bar = motif["bar"]
        for position, pos in enumerate(motif["values"]):
            layer["events"].append(
                _event(
                    preset, bar, motif["offset"] + 2 * position, sample.s, degree_of.get(pos, 0),
                    preset.motif_gain["function" if pos in preset.function_pos else "content"], 2,
                    {"bar": bar, "pos": pos, "degree": degree_of.get(pos, 0)},
                )
            )
    return layer


def _boegen(analysis, verses, tokens, preset: ComposePreset, picks: list[Pick]) -> list[dict[str, Any]]:
    events = []
    place = {}
    for verse in verses:
        ids = verse["token_ids"]
        for index, token_id in enumerate(ids):
            step = min(round(index / len(ids) * preset.steps_per_bar), preset.steps_per_bar - 1)
            place[token_id] = (verse, verse["bar"] * preset.steps_per_bar + step)
    groups: dict[tuple[int, int], list[tuple[str, str, int, int]]] = {}
    for pattern in analysis["patterns"]:
        if pattern["type"] != "dependency":
            continue
        for occurrence in pattern["occurrences"]:
            head, dependent = occurrence["token_ids"]
            if not occurrence["crosses_line"] or head not in place or dependent not in place:
                continue
            earlier, later = sorted((head, dependent), key=lambda i: place[i][1])
            from_bar, to_bar = place[earlier][0]["bar"], place[later][0]["bar"]
            if from_bar == to_bar:
                continue
            groups.setdefault((from_bar, to_bar), []).append((head, dependent, place[earlier][1], place[later][1]))
    ordered = sorted(groups.items(), key=lambda item: (min(e[2] for e in item[1]), item[0][1]))
    for index, ((from_bar, to_bar), edges) in enumerate(ordered):
        edges.sort(key=lambda e: (e[2], e[3]))
        onset = edges[0][2]
        end = max(e[3] for e in edges)
        head = tokens[edges[0][0]]
        source = {
            "from_verse": verses[from_bar]["unit_id"],
            "to_verse": verses[to_bar]["unit_id"],
            "edges": [[tokens[h]["text"], tokens[d]["text"]] for h, d, _, _ in edges],
        }
        event = _event(
            preset, from_bar, onset - from_bar * preset.steps_per_bar,
            picks[index % len(picks)].s, preset.pos_degrees.get(head["pos"], 0),
            min(0.5 + 0.1 * len(edges), 0.9), max(end - onset, 1), source,
        )
        events.append(event)
    return events


def _leitwort(verses, tokens, preset: ComposePreset, picks: list[Pick]) -> list[dict[str, Any]]:
    occurrences: dict[str, list[tuple[dict[str, Any], int, str]]] = {}
    for verse in verses:
        ids = verse["token_ids"]
        for index, token_id in enumerate(ids):
            token = tokens[token_id]
            if token["pos"] in preset.function_pos:
                continue
            step = min(round(index / len(ids) * preset.steps_per_bar), preset.steps_per_bar - 1)
            occurrences.setdefault(token["lemma"].casefold(), []).append((verse, step, token_id))
    events = []
    repeated = [(lemma, found) for lemma, found in occurrences.items() if len(found) >= 2]
    for index, (lemma, found) in enumerate(repeated):
        sample = picks[index % len(picks)]
        for verse, step, token_id in found:
            source = {"lemma": lemma, "token_id": token_id, "unit": verse["unit_id"]}
            events.append(_event(preset, verse["bar"], step, sample.s, index, 0.9, 1.0, source))
    return sorted(events, key=lambda e: e["step"])


ACCENT = 10 ** (3 / 80)
BOUNDARY_MARKS = frozenset(",;:–—-")


def _punctuation_marks(analysis, verses, preset: ComposePreset) -> list[dict[str, Any]]:
    place = {
        token_id: (verse["bar"], index, len(verse["token_ids"]))
        for verse in verses
        for index, token_id in enumerate(verse["token_ids"])
    }
    marks = []
    last = None
    for token in analysis["tokens"]:
        if token["id"] in place:
            last = place[token["id"]]
        elif token["is_punct"] and last is not None and set(token["text"]) & (set(".?!") | BOUNDARY_MARKS):
            bar, index, count = last
            step = min(round((index + 1) / count * preset.steps_per_bar), preset.steps_per_bar - 1)
            marks.append({"bar": bar, "step": step, "text": token["text"], "inside": index + 1 < count})
    return marks


def apply_punctuation(
    layers: list[dict[str, Any]], marks: list[dict[str, Any]], preset: ComposePreset
) -> list[dict[str, Any]]:
    by_name = {layer["name"]: layer for layer in layers}
    effects = []
    for mark in marks:
        in_bar = lambda name: [e for e in by_name[name]["events"] if e["bar"] == mark["bar"]]  # noqa: E731
        done = []
        if "." in mark["text"]:
            before = [e for e in in_bar("bass") if e["step"] % preset.steps_per_bar <= mark["step"]]
            if before:
                _touch(max(before, key=lambda e: e["step"]), mark, gain=ACCENT)
                done.append("accent bass")
            else:
                done.append("no bass in bar")
        if "?" in mark["text"]:
            motif = in_bar("motiv")
            if motif:
                last = max(motif, key=lambda e: e["step"])
                last["source"]["degree"] += 1
                last["note"] = _note(preset, last["source"]["degree"])
                _touch(last, mark)
                done.append("raise last motif note")
            else:
                done.append("no motif in bar")
        if set(mark["text"]) & BOUNDARY_MARKS and mark["inside"]:
            start = mark["step"]
            cut = {}
            for name in ("puls", "motiv"):
                cut[name] = 0
                for event in by_name[name]["events"]:
                    step = event["step"] % preset.steps_per_bar
                    if event["bar"] == mark["bar"] and step < start and event["legato"] > start - step:
                        event["legato"] = start - step
                        cut[name] += 1
            done.append(f"cut puls ({cut['puls']} hits) and motiv ({cut['motiv']} notes) at the mark")
        if "!" in mark["text"]:
            for layer in layers:
                for event in layer["events"]:
                    if event["bar"] == mark["bar"]:
                        _touch(event, mark, gain=ACCENT)
            done.append("bar +3 dB")
        effects.append({**mark, "effect": "; ".join(done)})
    return effects


def _touch(event: dict[str, Any], mark: dict[str, Any], gain: float = 1.0) -> None:
    event["gain"] = round(event["gain"] * gain, 4)
    event["source"].setdefault("punctuation", []).append(mark["text"])


def _verses(analysis: dict[str, Any], preset: ComposePreset) -> tuple[str, list[dict[str, Any]]]:
    eligible = {t["id"] for t in analysis["tokens"] if t["eligible"]}

    def units(sections):
        found = [(unit["id"], [i for i in unit["token_ids"] if i in eligible]) for unit in sections]
        return [(unit_id, ids) for unit_id, ids in found if ids]

    form, chosen = "line", units(analysis["sections"]["lines"])
    sentences = units(analysis["sentences"])
    if len(sentences) > len(chosen):
        form, chosen = "sentence", sentences
    if not chosen:
        raise ComposeError("analysis contains no words to compose from")
    while len(chosen) < preset.min_bars:
        index = max(range(len(chosen)), key=lambda i: len(chosen[i][1]))
        unit_id, ids = chosen[index]
        if len(ids) < 2:
            break
        half = -(-len(ids) // 2)
        chosen[index : index + 1] = [(unit_id, ids[:half]), (unit_id, ids[half:])]
    return form, [{"bar": bar, "unit_id": unit_id, "token_ids": ids} for bar, (unit_id, ids) in enumerate(chosen)]
