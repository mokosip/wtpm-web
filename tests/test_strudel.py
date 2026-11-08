from __future__ import annotations

import re

from test_compose import layer, make_library, make_preset, pilger, pipeline, score  # noqa: F401

from wtpm.compose import compose
from wtpm.strudel import BASS_LPF, ECHO_ORBIT, SAMPLE_BASE_NOTE, SYNTH_BASE_NOTE, render_strudel

CALL = re.compile(r'\.?(\w+)\("([^"]*)"\)')


def _slots(code):
    calls = dict(CALL.findall(code))
    columns = [calls[name].split() for name in ("s", "note", "gain", "clip") if name in calls]
    return [tuple(column[slot] for column in columns) + (slot,) for slot in range(len(columns[0])) if columns[0][slot] != "~"]


def _expected(score, event):
    synth = next(s["synth"] for s in score["samples"] if s["s"] == event["s"])
    base = SYNTH_BASE_NOTE if synth else SAMPLE_BASE_NOTE
    return (event["s"], f"{(event['note'] or 0) + base:g}", f"{round(event['gain'] ** 4, 4):g}", f"{event['legato']:g}", event["step"])


def test_every_event_sounds_once_in_its_slot_with_strudel_pitch_level_and_length(score):  # noqa: F811
    rendered = render_strudel(score)
    assert (rendered["cps"], rendered["bars"]) == (score["tempo"]["cps"], score["bars"])
    for name in ("puls", "bass", "motiv", "boegen", "leitwort"):
        played = sorted(slot for voice in rendered["voices"] if voice["layer"] == name for slot in _slots(voice["code"]))
        expected = sorted(_expected(score, e) for e in layer(score, name)["events"])
        assert played == expected and played or not layer(score, name)["events"]


def test_the_bass_is_a_filtered_strudel_synth(score):  # noqa: F811
    bass = [voice["code"] for voice in rendered_voices(score, "bass")]
    assert bass and all(f".lpf({BASS_LPF})" in code for code in bass)
    assert not any(".lpf(" in voice["code"] for voice in render_strudel(score)["voices"] if voice["layer"] != "bass")


def test_echo_notes_get_their_own_voice_on_the_echo_orbit(pipeline):  # noqa: F811
    echoed = compose(pipeline.analyze("Der Wind singt leise.\nDer Wind singt laut.").to_dict(), make_preset(), make_library())
    voices = render_strudel(echoed)["voices"]
    wet = [voice["code"] for voice in voices if ".room(" in voice["code"]]
    assert wet and all(f".orbit({ECHO_ORBIT})" in code for code in wet)
    echo = next(e["echo"] for lay in echoed["layers"] for e in lay["events"] if "echo" in e)
    assert all(f".{key}({value:g})" in code for code in wet for key, value in echo.items())
    dry = [voice["code"] for voice in voices if ".room(" not in voice["code"]]
    assert dry and not any(".orbit(" in code for code in dry)


def rendered_voices(score, name):
    return [voice for voice in render_strudel(score)["voices"] if voice["layer"] == name]
