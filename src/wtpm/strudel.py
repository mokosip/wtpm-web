from __future__ import annotations

from typing import Any

REST = "~"
SAMPLE_BASE_NOTE = 36
SYNTH_BASE_NOTE = 60
BASS_LPF = 600
ECHO_ORBIT = 1


def render_strudel(score: dict[str, Any]) -> dict[str, Any]:
    slots = score["bars"] * score["tempo"]["steps_per_bar"]
    synths = {sample["s"] for sample in score["samples"] if sample["synth"]}
    voices = [
        {"layer": layer["name"], "code": _voice(part, slots, synths) + _effects(echo)}
        for layer in score["layers"]
        for echo, events in _by_echo(layer["events"])
        for part in _split(events)
    ]
    return {"cps": score["tempo"]["cps"], "bars": score["bars"], "voices": voices}


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


def _voice(events: list[dict[str, Any]], slots: int, synths: set[str]) -> str:
    sounds, notes, gains, clips = ([REST] * slots for _ in range(4))
    for event in events:
        step = event["step"]
        base = SYNTH_BASE_NOTE if event["s"] in synths else SAMPLE_BASE_NOTE
        sounds[step] = event["s"]
        notes[step] = _number((event["note"] or 0) + base)
        gains[step] = _number(round(event["gain"] ** 4, 4))
        clips[step] = _number(event["legato"])
    code = "".join(
        f'{"." if name != "s" else ""}{name}("{" ".join(values)}")'
        for name, values in (("s", sounds), ("note", notes), ("gain", gains), ("clip", clips))
    )
    return code + (f".lpf({BASS_LPF})" if any(event["s"] in synths for event in events) else "")


def _effects(echo: tuple[tuple[str, float], ...]) -> str:
    if not echo:
        return ""
    return "".join(f".{name}({_number(value)})" for name, value in echo) + f".orbit({ECHO_ORBIT})"


def _number(value: float) -> str:
    return f"{value:g}"
