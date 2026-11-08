from __future__ import annotations

from typing import Any

REST = "~"
INDENT = "  "


def render_tidal(score: dict[str, Any], bar: int | None = None) -> str:
    single = bar is not None
    if single:
        score = _single_bar(score, bar)
    tempo = score["tempo"]
    slots = score["bars"] * tempo["steps_per_bar"]
    spec = score.get("live_motif", {})
    live = {verse["bar"]: verse for verse in spec["verses"]} if spec.get("active") else {}
    voices = [
        _voice(part, slots) + _effects(echo)
        for layer in score["layers"]
        for echo, events in _by_echo(
            [e for e in layer["events"] if not (layer["name"] == "motiv" and e["bar"] in live)]
        )
        for part in _split(events)
    ]
    if live:
        motif = next(layer for layer in score["layers"] if layer["name"] == "motiv")
        if not single:
            voices = [[f"slow {score['bars']}", f"$ {voice[0]}", *voice[1:]] for voice in voices]
        voices += [
            _live_voice(events, verse, score, slots, single) + _effects(echo)
            for bar, verse in live.items()
            for echo, events in _by_echo([e for e in motif["events"] if e["bar"] == bar])
        ]
    head = f"setcps ({_number(tempo['bpm'])}/60/{tempo['beats_per_bar']})\n\nd1 $ silence\n"
    if not voices:
        return head
    lines = [] if single or live else [f"$ slow {score['bars']}"]
    lines += ["$ stack", "["]
    for index, voice in enumerate(voices):
        if index:
            lines.append(",")
        lines += voice
    lines.append("]")
    return head + "\nd1\n" + "".join(f"{INDENT}{line}\n" for line in lines)


def _single_bar(score: dict[str, Any], bar: int) -> dict[str, Any]:
    offset = bar * score["tempo"]["steps_per_bar"]
    layers = [
        {**layer, "events": [{**e, "bar": 0, "step": e["step"] - offset} for e in layer["events"] if e["bar"] == bar]}
        for layer in score["layers"]
    ]
    live = score.get("live_motif", {})
    if live.get("active"):
        verses = [{**verse, "bar": 0} for verse in live["verses"] if verse["bar"] == bar]
        live = {**live, "verses": verses} if verses else {"active": False, "reason": "no chain in this verse"}
    return {**score, "bars": 1, "layers": layers, "live_motif": live}


def render_scd(score: dict[str, Any]) -> str:
    lines = [
        f'~dirt.loadSoundFile("{_sc_string(sample["path"])}", \\{sample["name"]}{", true" if sample.get("index") else ""});'
        for sample in score["samples"]
        if not sample["synth"] and not sample.get("superdirt")
    ]
    return "(\n" + "\n".join(lines) + "\n)\n"


def _split(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    voices: list[dict[int, dict[str, Any]]] = []
    for event in sorted(events, key=lambda e: e["step"]):
        voice = next((v for v in voices if event["step"] not in v), None)
        if voice is None:
            voice = {}
            voices.append(voice)
        voice[event["step"]] = event
    return [list(voice.values()) for voice in voices]


def _by_echo(events: list[dict[str, Any]]) -> list[tuple[tuple[tuple[str, float], ...], list[dict[str, Any]]]]:
    groups: dict[tuple[tuple[str, float], ...], list[dict[str, Any]]] = {}
    for event in events:
        groups.setdefault(tuple(event.get("echo", {}).items()), []).append(event)
    return sorted(groups.items(), key=lambda group: bool(group[0]))


def _effects(echo: tuple[tuple[str, float], ...]) -> list[str]:
    return [f"# {name} {_number(value)}" for name, value in echo]


def _voice(events: list[dict[str, Any]], slots: int) -> list[str]:
    sounds, notes, gains, legatos = ([REST] * slots for _ in range(4))
    for event in events:
        step = event["step"]
        sounds[step] = event["s"]
        notes[step] = _number(event["note"] or 0)
        gains[step] = _number(event["gain"])
        legatos[step] = _number(event["legato"])
    lines = [f's "{" ".join(sounds)}"']
    if any(event["note"] is not None for event in events):
        lines.append(f'# note "{" ".join(notes)}"')
    lines += [f'# gain "{" ".join(gains)}"', f'# legato "{" ".join(legatos)}"']
    return lines


def _live_voice(
    events: list[dict[str, Any]], verse: dict[str, Any], score: dict[str, Any], slots: int, every_cycle: bool
) -> list[str]:
    spec, bars, steps_per_bar = score["live_motif"], score["bars"], score["tempo"]["steps_per_bar"]
    sequence = (lambda body: f'"{body}"') if every_cycle else (lambda body: f'(slow {bars} "{body}")')
    sounds, gains, legatos, onsets, raises = ([REST] * slots for _ in range(5))
    for event in events:
        step = event["step"]
        raised = int("?" in "".join(event["source"].get("punctuation", [])))
        sounds[step], gains[step], legatos[step] = event["s"], _number(event["gain"]), _number(event["legato"])
        onsets[step], raises[step] = "t", str(raised)
    rows = [", ".join(repr(p) for p in row) for row in verse["matrix"]]
    chain = [
        f"(struct {sequence(' '.join(onsets))}",
        f"{INDENT}$ fit 0 [{', '.join(str(d) for d in spec['degrees'])}]",
        f"{INDENT}$ compress ({verse['offset']}/{steps_per_bar}, {verse['offset'] + 2 * verse['steps']}/{steps_per_bar})",
        f"{INDENT}$ markovPat {verse['steps']} {verse['start']}",
        *(f"{2 * INDENT}{', ' if index else '[ '}[{row}]" for index, row in enumerate(rows)),
        f"{2 * INDENT}]",
        ")",
        f"|+ {sequence(' '.join(raises))}",
    ]
    rhythm = [f's "{" ".join(sounds)}"', f'# gain "{" ".join(gains)}"', f'# legato "{" ".join(legatos)}"']
    if not every_cycle:
        rhythm = [f"(slow {bars}", f"{INDENT}$ {rhythm[0]}", *(INDENT + line for line in rhythm[1:])]
        rhythm[-1] += ")"
    scale = ", ".join(str(i) for i in score["scale"]["intervals"])
    return [
        *rhythm,
        f"# note (toScale [{scale}] (",
        *(INDENT + line for line in chain),
        f"{INDENT}) |+ {score['scale']['root']})",
    ]


def _number(value: float) -> str:
    return f"{value:g}"


def _sc_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
