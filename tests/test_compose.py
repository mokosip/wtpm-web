from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from helpers import make_document

from wtpm.analysis import analyze
from wtpm.compose import (
    DEFAULT_PRESET,
    ComposeError,
    ComposePreset,
    apply_punctuation,
    compose,
)
from wtpm.config import AnalysisConfig
from wtpm.corrections import load_corrections
from wtpm.pipeline import Pipeline
from wtpm.samplebank import SampleRef

FIXTURES = Path(__file__).parent / "fixtures"
PRESET_DATA = json.loads(DEFAULT_PRESET.read_text(encoding="utf-8"))
LIBRARY_SPEC = {
    "perc": [0.3, 0.3, 0.4, 0.5],
    "kick": [0.6, 0.6],
    "snare": [0.4],
    "bass": [0.5, 0.8, 1.2],
    "stab": [1.0, 1.2, 0.8, 0.7],
    "lead": [2.0, 1.1],
    "pad": [2.5, 4.5, 5.0],
    "drone": [2.0],
    "texture": [3.0, 4.0, 1.0],
    "field": [1.8],
    "fx": [0.4, 0.9],
    "voice": [3.0],
}


NEUTRAL_PROFILE = {
    "tempo": {"sentence_words": [8, 40], "bpm": [90, 90]},
    "variation": {"verb_share": [2, 3]},
}


def make_preset(**overrides) -> ComposePreset:
    data = copy.deepcopy(PRESET_DATA)
    data["profile"] = copy.deepcopy(NEUTRAL_PROFILE)
    data["profile"].update(overrides.pop("profile", {}))
    data.update(overrides)
    return ComposePreset.from_dict(data)


SYNTHS = [
    SampleRef(id=f"synth/{name}", path=None, duration=None, role=role, synth=True)
    for name, role in (
        ("superkick", "kick"), ("sostoms", "perc"), ("superreese", "bass"), ("super808", "bass"), ("superhammond", "pad"),
    )
]


def make_library(spec=None, synths=SYNTHS) -> list[SampleRef]:
    return [
        SampleRef(id=f"dirt/{kind}/{n}.wav", path=None, duration=duration, role=kind, s=f"{kind}_{n}")
        for kind, durations in (spec or LIBRARY_SPEC).items()
        for n, duration in enumerate(durations)
    ] + list(synths)


@pytest.fixture(scope="module")
def pipeline():
    return Pipeline(language="de", model="de_core_news_sm")


@pytest.fixture(scope="module")
def pilger(pipeline):
    text = (FIXTURES / "pilger.txt").read_text(encoding="utf-8")
    corrections = load_corrections(FIXTURES / "pilger.corrections.json")
    return pipeline.analyze(text, AnalysisConfig(), corrections=corrections).to_dict()


@pytest.fixture(scope="module")
def score(pilger):
    preset = make_preset()
    return compose(pilger, preset, make_library())


def run(analysis, sample_seed=None, **overrides):
    preset = make_preset(**overrides)
    return compose(analysis, preset, make_library(), sample_seed=sample_seed)


def words_of(analysis, verse):
    by_id = {t["id"]: t["text"] for t in analysis["tokens"]}
    return [by_id[i] for i in verse["token_ids"]]


def test_one_bar_per_verse(pilger, score):
    assert score["bars"] == 4
    assert score["form"] == "line"
    assert [(v["bar"], v["unit_id"]) for v in score["verses"]] == [(0, "l1"), (1, "l2"), (2, "l3"), (3, "l4")]
    assert words_of(pilger, score["verses"][3]) == ["ihre", "Heimlichkeiten", "aufgehäuft"]
    assert score["tempo"] == {"bpm": 90.0, "beats_per_bar": 4, "steps_per_bar": 16, "cps": 0.375}


def test_single_line_is_split_into_two_bars(pipeline):
    analysis = pipeline.analyze("Der Fluss trägt die Steine weit.").to_dict()
    score = run(analysis)
    assert score["bars"] == 2
    assert [words_of(analysis, v) for v in score["verses"]] == [["Der", "Fluss", "trägt"], ["die", "Steine", "weit"]]


def test_a_single_word_is_one_bar_and_no_bar_stays_empty(pipeline):
    analysis = pipeline.analyze("Hallo").to_dict()
    score = run(analysis)
    assert score["bars"] == 1
    assert [words_of(analysis, v) for v in score["verses"]] == [["Hallo"]]
    assert {e["bar"] for lay in score["layers"] for e in lay["events"]} == {0}


def test_prose_with_more_sentences_than_lines_gets_one_bar_per_sentence(pipeline):
    analysis = pipeline.analyze("Der Hund bellt laut. Die Katze schläft lange. Ein Vogel singt hell.").to_dict()
    score = run(analysis)
    assert score["form"] == "sentence"
    assert [(v["bar"], v["unit_id"]) for v in score["verses"]] == [(0, "s1"), (1, "s2"), (2, "s3")]
    assert [words_of(analysis, v) for v in score["verses"]] == [
        ["Der", "Hund", "bellt", "laut"],
        ["Die", "Katze", "schläft", "lange"],
        ["Ein", "Vogel", "singt", "hell"],
    ]
    assert {e["source"]["unit"] for e in layer(score, "puls")["events"]} == {"s1", "s2", "s3"}


def test_every_verse_line_becomes_a_bar(pipeline):
    text = "\n".join(f"Zeile {n} klingt." for n in range(1, 13))
    analysis = pipeline.analyze(text).to_dict()
    score = run(analysis)
    assert score["bars"] == 12
    assert [v["unit_id"] for v in score["verses"]] == [f"l{n}" for n in range(1, 13)]
    assert {e["bar"] for e in layer(score, "puls")["events"]} == set(range(12))


def test_tempo_follows_the_mean_sentence_length(pipeline):
    tempo = {"sentence_words": [2, 10], "bpm": [120, 40]}
    short = run(pipeline.analyze("Hunde bellen. Katzen schlafen.").to_dict(), profile={"tempo": tempo})
    middle = run(pipeline.analyze("Der Hund bellt sehr laut. Die Katze schläft dort lange.").to_dict(), profile={"tempo": tempo})
    names = " und ".join(["Anna", "Berta", "Clara", "Doris", "Emma", "Frieda"])
    long = run(pipeline.analyze(f"{names} singen.").to_dict(), profile={"tempo": tempo})
    assert [s["tempo"]["bpm"] for s in (short, middle, long)] == [120, 90, 40]
    assert middle["tempo"] == {"bpm": 90, "beats_per_bar": 4, "steps_per_bar": 16, "cps": 0.375}
    assert middle["profile"]["tempo"] == {"sentence_words": 5.0, "norm": 0.375, "bpm": 90}


def test_seed_is_reproducible_and_follows_the_text_only(pipeline, pilger, score):
    assert run(pilger)["seed"] == score["seed"]
    assert run(pilger) == score
    other = pipeline.analyze("Ein anderer Text.\nMit zwei Zeilen.").to_dict()
    assert run(other)["seed"] != score["seed"]


def test_preset_changes_do_not_redraw_the_motif(pilger, score):
    layers = copy.deepcopy(PRESET_DATA["layers"])
    layers["bass"]["octave"] = 2
    changed = run(
        pilger,
        mix={**PRESET_DATA["mix"], "motiv": 0.5},
        layers=layers,
        profile={"variation": {"verb_share": [0.0, 0.5]}},
    )
    assert changed["seed"] == score["seed"]
    drawn = lambda s: [(e["bar"], e["source"]["pos"]) for e in layer(s, "motiv")["events"]]  # noqa: E731
    assert drawn(changed) == drawn(score)


def layer(score, name):
    (found,) = [candidate for candidate in score["layers"] if candidate["name"] == name]
    return found


def _puls_steps(score):
    events = layer(score, "puls")["events"]
    return [[e["step"] - bar * 16 for e in events if e["bar"] == bar] for bar in range(score["bars"])]


def test_puls_hits_sit_on_the_function_words_of_each_verse(pilger, score):
    tokens = {t["id"]: t for t in pilger["tokens"]}
    function = set(PRESET_DATA["function_pos"])
    for verse, steps in zip(score["verses"], _puls_steps(score)):
        words = [tokens[i] for i in verse["token_ids"]]
        positions = sorted({min(round(k / len(words) * 16), 15) for k, w in enumerate(words) if w["pos"] in function})
        if len(positions) >= 2:
            assert steps == positions
    events = layer(score, "puls")["events"]
    assert events[0]["gain"] == pytest.approx(0.6 + 0.35 * 3 / 8, abs=1e-4)
    assert {e["s"] for e in events} == {_picked(score, "puls")[0]["s"]}


def test_the_puls_draws_up_to_x_samples_each_under_its_own_name(score):
    puls = _picked(score, "puls")
    assert PRESET_DATA["layers"]["puls"]["samples"] > len(puls) == 7
    assert all(s["s"] == "_".join(s["id"].removeprefix("dirt/").removesuffix(".wav").split("/")) for s in puls)
    assert {s["role"] for s in puls} == {"perc", "kick", "snare"}


FULL_VARIATION = {"variation": {"verb_share": [0.0, 0.01]}}


def _variation(pilger, seed, verb_share):
    return run(pilger, sample_seed=seed, profile={"variation": {"verb_share": verb_share}})


def test_the_sample_seed_fixes_which_puls_sample_each_step_of_the_bar_plays(pilger):
    varied = _variation(pilger, "a", [0.0, 0.01])
    spec = layer(varied, "puls")["variation"]
    assert spec["probability"] == 1.0
    assert len(spec["positions"]) == 16 and len(set(spec["positions"])) > 2
    assert all(0 <= k < 7 for k in spec["positions"])
    events = layer(varied, "puls")["events"]
    assert len({e["bar"] for e in events}) > 1
    puls = _picked(varied, "puls")
    assert all(e["s"] == puls[spec["positions"][e["step"] % 16]]["s"] for e in events)
    assert layer(_variation(pilger, "b", [0.0, 0.01]), "puls")["variation"]["positions"] != spec["positions"]


def test_without_variation_every_step_plays_the_first_puls_sample(score):
    assert layer(score, "puls")["variation"]["positions"] == [0] * 16


def test_a_higher_variation_keeps_every_step_a_lower_one_varied(pilger):
    low = layer(_variation(pilger, "a", [0.0, 1.0]), "puls")["variation"]
    high = layer(_variation(pilger, "a", [0.0, 0.5]), "puls")["variation"]
    assert low["probability"] < high["probability"]
    assert sum(k > 0 for k in low["positions"]) < sum(k > 0 for k in high["positions"])
    assert all(h == k for k, h in zip(low["positions"], high["positions"]) if k > 0)


def test_the_same_number_of_function_words_in_other_places_gives_another_rhythm():
    score = run(fixture_analysis(["DET", "NOUN", "ADP", "NOUN"], ["NOUN", "VERB", "DET", "PRON"]))
    assert [bar[0]["source"]["function_words"] for bar in _bars(layer(score, "puls")["events"], 2)] == [2, 2]
    assert _puls_steps(score) == [[0, 8], [8, 12]]


def test_a_verse_below_the_minimum_is_filled_on_the_strong_beats():
    score = run(fixture_analysis(["NOUN", "VERB"], ["NOUN", "DET", "VERB", "ADV"], ["NOUN", "DET"]))
    assert _puls_steps(score) == [[0, 8], [0, 4], [0, 8]]
    assert [bar[0]["source"]["filled"] for bar in _bars(layer(score, "puls")["events"], 3)] == [[0, 8], [0], [0]]


def test_auxiliaries_count_as_function_words(pipeline):
    analysis = pipeline.analyze("Der Hund ist müde.\nDie Katze ist wach.").to_dict()
    assert [t["pos"] for t in analysis["tokens"] if t["text"] == "ist"] == ["AUX", "AUX"]
    score = run(analysis)
    puls = layer(score, "puls")["events"]
    assert [next(e for e in puls if e["bar"] == bar)["source"]["function_words"] for bar in (0, 1)] == [2, 2]
    assert all(e["source"]["lemma"] != "sein" for e in layer(score, "leitwort")["events"])


def test_bass_is_a_held_bass_synth_that_climbs_with_dependency_depth(score):
    bass = layer(score, "bass")
    assert [(e["source"]["text"], e["source"]["depth"], e["note"]) for e in bass["events"]] == [
        ("fühlt", 0, -24),
        ("träuft", 1, -21),
        ("hätten", 2, -19),
        ("aufgehäuft", 3, -17),
    ]
    assert [e["step"] for e in bass["events"]] == [8, 30, 38, 58]
    assert [e["legato"] for e in bass["events"]] == [22, 8, 20, 14]
    (picked,) = _picked(score, "bass")
    assert (picked["synth"], picked["role"], picked["duration"]) == (True, "bass", None)
    assert {e["s"] for e in bass["events"]} == {picked["id"].removeprefix("synth/")} <= {"superreese", "super808"}
    assert score["pools"]["bass"] == 2


def test_bass_needs_a_bass_synth(pilger):
    with pytest.raises(ComposeError, match=r"layer bass: no synths with role \['bass'\]"):
        compose(pilger, make_preset(), make_library(synths=[]))


def test_scale_degrees_wrap_into_the_next_octave(pilger):
    score = run(pilger, scale={"root": 2, "intervals": [0, 7]})
    notes = [e["note"] for e in layer(score, "bass")["events"]]
    assert notes == [-22, -15, -10, -3]


def _bars(events, bars):
    return [[e for e in events if e["bar"] == bar] for bar in range(bars)]


def frequency_rank(analysis):
    counts = {}
    for token in analysis["tokens"]:
        if token["eligible"]:
            counts[token["pos"]] = counts.get(token["pos"], 0) + 1
    return {pos: rank for rank, pos in enumerate(sorted(counts, key=lambda pos: (-counts[pos], pos)))}


def test_motif_pitch_is_the_pos_frequency_rank(pilger, score):
    rank = frequency_rank(pilger)
    events = [e for e in layer(score, "motiv")["events"] if "punctuation" not in e["source"]]
    assert events
    assert [e["note"] for e in events] == [note_of(rank[e["source"]["pos"]]) for e in events]


def _motif_gain(pos):
    return PRESET_DATA["motif"]["gain"]["function" if pos in PRESET_DATA["function_pos"] else "content"]


ALL_LENGTHS = tuple(range(2, 9))
V1 = ["DET", "NOUN", "VERB", "ADV"]
V2 = ["PRON", "DET", "NOUN", "VERB", "ADV"]
NO_EXCLUDE = {"motif": {**PRESET_DATA["motif"], "exclude": []}}


def test_each_verse_plays_its_most_frequent_repeated_sequence_exactly():
    motiv = layer(run(fixture_analysis(V1, V2, ["DET", "NOUN"], ["INTJ"], lengths=ALL_LENGTHS), **NO_EXCLUDE), "motiv")
    assert [m and (m["values"], m["count"]) for m in motiv["source"]["motifs"]] == [
        (["DET", "NOUN"], 3), (["DET", "NOUN"], 3), (["DET", "NOUN"], 3), None,
    ]
    for bar in range(3):
        events = [e for e in motiv["events"] if e["bar"] == bar]
        assert [e["source"]["pos"] for e in events] == ["DET", "NOUN"]
        assert [e["gain"] for e in events] == [_motif_gain("DET"), _motif_gain("NOUN")]
        assert [e["legato"] for e in events] == [2.0, 2.0]
    assert not [e for e in motiv["events"] if e["bar"] == 3]


def test_equally_frequent_sequences_prefer_the_longer_one():
    motiv = layer(run(fixture_analysis(V1, V2, ["INTJ"], lengths=ALL_LENGTHS)), "motiv")
    assert [m and m["values"] for m in motiv["source"]["motifs"]] == [V1, V1, None]
    assert [e["source"]["pos"] for e in motiv["events"] if e["bar"] == 1] == V1


def test_standard_sequences_of_the_preset_do_not_win_a_verse():
    assert ["DET", "NOUN"] in PRESET_DATA["motif"]["exclude"]
    motiv = layer(run(fixture_analysis(V1, V2, ["DET", "NOUN"], lengths=ALL_LENGTHS)), "motiv")
    assert [m and m["values"] for m in motiv["source"]["motifs"]][:2] == [V1, V1]


def test_a_verse_with_only_standard_sequences_plays_the_best_of_them():
    motiv = layer(run(fixture_analysis(V1, V2, ["DET", "NOUN"], lengths=ALL_LENGTHS)), "motiv")
    motifs = motiv["source"]["motifs"]
    assert [(m["values"], m["standard"]) for m in motifs] == [(V1, False), (V1, False), (["DET", "NOUN"], True)]
    assert [e["source"]["pos"] for e in motiv["events"] if e["bar"] == 2] == ["DET", "NOUN"]


LATE = ["INTJ", "PART", "SCONJ", "NUM", "PROPN", "ADP", *V1]


def test_a_verse_motif_starts_on_the_eighth_nearest_its_first_word():
    motiv = layer(run(fixture_analysis(V1, V2, ["DET", "NOUN"], lengths=ALL_LENGTHS), **NO_EXCLUDE), "motiv")
    steps = [[e["step"] - bar * 16 for e in motiv["events"] if e["bar"] == bar] for bar in range(3)]
    assert steps == [[0, 2], [4, 6], [0, 2]]


def test_a_late_motif_is_moved_forward_to_end_inside_its_bar():
    motiv = layer(run(fixture_analysis(V1, LATE, lengths=ALL_LENGTHS)), "motiv")
    assert [m["values"] for m in motiv["source"]["motifs"]] == [V1, V1]
    assert [e["step"] - 16 for e in motiv["events"] if e["bar"] == 1] == [8, 10, 12, 14]


def test_boegen_hold_across_each_crossed_verse_pair(score):
    boegen = layer(score, "boegen")
    summary = [
        (e["source"]["from_verse"], e["source"]["to_verse"], len(e["source"]["edges"]), e["step"], e["legato"])
        for e in boegen["events"]
    ]
    assert summary == [("l1", "l2", 5, 8, 22), ("l1", "l3", 1, 8, 24), ("l3", "l4", 1, 37, 22)]
    assert all(e["step"] // 16 < (e["step"] + e["legato"]) // 16 for e in boegen["events"])
    assert [e["gain"] for e in boegen["events"]] == pytest.approx([0.9 * 0.75, 0.6 * 0.75, 0.6 * 0.75])
    assert [e["note"] for e in boegen["events"]] == [5, 5, 5]
    assert [e["s"] for e in boegen["events"]] == [s["s"] for s in _picked(score, "boegen")]


def test_leitwort_is_silent_when_only_function_lemmas_repeat(score):
    assert layer(score, "leitwort")["events"] == []


def _echoed(score):
    return sorted(
        (lay["name"], e["bar"], e["step"] % 16) for lay in score["layers"] for e in lay["events"] if "echo" in e
    )


def test_a_repeated_word_sequence_echoes_from_its_second_occurrence(pipeline):
    score = run(pipeline.analyze("Der Wind singt leise.\nDer Wind singt laut.").to_dict())
    assert _echoed(score) == [
        ("bass", 1, 8), ("leitwort", 1, 4), ("leitwort", 1, 8),
        ("motiv", 1, 0), ("motiv", 1, 2), ("motiv", 1, 4), ("motiv", 1, 6), ("puls", 1, 0), ("puls", 1, 8),
    ]
    echoes = [e for lay in score["layers"] for e in lay["events"] if "echo" in e]
    assert all(e["echo"] == PRESET_DATA["echo"] for e in echoes)
    assert {tuple(e["source"]["echo"]) for e in echoes} == {("Der", "Wind", "singt")}



def test_an_immediately_repeated_word_echoes_on_the_repetition(pipeline):
    score = run(pipeline.analyze("Was ein Jammer Jammer.\nSchade.").to_dict())
    assert _echoed(score) == [("leitwort", 0, 12)]


def test_leitwort_marks_every_occurrence_of_a_repeated_content_lemma(pipeline):
    text = (Path(__file__).parents[1] / "examples" / "gedicht.txt").read_text(encoding="utf-8")
    scored = run(pipeline.analyze(text).to_dict())
    leitwort, picked = layer(scored, "leitwort"), _picked(scored, "leitwort")
    by_lemma: dict[str, list[dict]] = {}
    for event in leitwort["events"]:
        by_lemma.setdefault(event["source"]["lemma"], []).append(event)
    assert list(by_lemma) == ["tragen", "stein", "zählen"]
    for index, (lemma, events) in enumerate(by_lemma.items()):
        assert len(events) == 2
        assert {e["s"] for e in events} == {picked[index % 3]["s"]}
        assert {e["note"] for e in events} == {[0, 3, 5][index]}


def fixture_analysis(*sentences, lengths=(2, 3, 4)):
    words = iter(f"w{i}" for i in range(100))
    document = make_document(
        [[{"text": next(words), "pos": pos, "head": None} for pos in sentence] for sentence in sentences]
    )
    return analyze(document, AnalysisConfig(sequence_lengths=lengths)).to_dict()


SIX = ["NOUN", "VERB", "ADJ", "ADV", "DET", "PRON"]
TEN = [*SIX, "ADP", "NUM", "PROPN", "CCONJ"]


def test_a_verse_motif_never_outgrows_the_eight_eighths_of_one_bar():
    motiv = layer(run(fixture_analysis(TEN, TEN, lengths=tuple(range(2, 11)))), "motiv")
    assert motiv["source"]["motifs"][0]["values"] == TEN[:8]
    assert len([e for e in motiv["events"] if e["bar"] == 0]) == 8


def _first(payload, pattern_type):
    return next(p for p in payload["patterns"] if p["type"] == pattern_type)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda p: p.update(schema_version="1.0"), "schema_version 1.1"),
        (lambda p: _first(p, "dependency")["occurrences"][0].pop("crosses_line"), "crosses_line"),
        (lambda p: _first(p, "pos_ngram")["occurrences"][0].pop("crosses_line"), "crosses_line"),
        (lambda p: _first(p, "pos_ngram").update(values=["X", "X"]), "do not match token POS"),
    ],
)
def test_incomplete_or_inconsistent_input_is_rejected(pilger, change, message):
    payload = copy.deepcopy(pilger)
    change(payload)
    with pytest.raises(ComposeError, match=message):
        run(payload)




def _picked(score, layer_name):
    return [s for s in score["samples"] if s["layer"] == layer_name]


def test_each_sample_layer_draws_from_its_roles(score):
    for layer_name, spec in PRESET_DATA["layers"].items():
        picked = _picked(score, layer_name)
        assert len(picked) == min(spec["samples"], score["pools"][layer_name])
        assert {s["role"] for s in picked} <= set(spec["roles"])
        assert len({s["id"] for s in picked}) == len(picked)
    assert score["pools"] == {"puls": 7, "bass": 2, "motiv": 6, "boegen": 7, "leitwort": 6}


def test_sample_layers_never_draw_synths(score):
    assert all(not s["synth"] for s in score["samples"] if s["layer"] != "bass")
    assert all(s["synth"] for s in score["samples"] if s["layer"] == "bass")


def test_boegen_draw_only_long_pad_drone_texture_or_field_samples(score):
    for sample in _picked(score, "boegen"):
        assert sample["long"] and sample["duration"] >= 1.5
        assert sample["role"] in {"pad", "drone", "texture", "field"}


def test_sample_seed_stays_the_same_for_every_text_unless_rerolled(pipeline, pilger, score):
    other = run(pipeline.analyze("Ein anderer Text.\nMit zwei Zeilen.").to_dict())
    assert other["seed"] != score["seed"]
    assert other["sample_seed"] == score["sample_seed"]
    assert run(pilger)["samples"] == score["samples"]
    assert run(pilger, scale={"root": 2, "intervals": [0, 3, 5, 7, 10]})["sample_seed"] != score["sample_seed"]
    preset = make_preset()
    rerolls = [compose(pilger, preset, make_library(), sample_seed=f"r{n}") for n in range(6)]
    assert {r["sample_seed"] for r in rerolls} == {f"r{n}" for n in range(6)}
    assert len({tuple(s["id"] for s in r["samples"]) for r in rerolls}) > 1
    again = compose(pilger, preset, make_library(), sample_seed="r3")
    assert again["samples"] == rerolls[3]["samples"]


def test_a_layer_without_matching_tagged_samples_is_reported(pilger):
    spec = {kind: durations for kind, durations in LIBRARY_SPEC.items() if kind not in {"texture", "field", "drone"}}
    spec["pad"] = [1.0]
    with pytest.raises(ComposeError, match=r"layer boegen: no samples with role .*at least 1.5 s"):
        compose(pilger, make_preset(), make_library(spec))


def test_layer_levels_scale_every_gain_of_their_layer(pilger, score):
    flat = run(pilger, mix={name: 1.0 for name in PRESET_DATA["mix"]})
    for staged, unstaged in zip(score["layers"], flat["layers"]):
        level = PRESET_DATA["mix"][staged["name"]]
        assert [e["gain"] for e in staged["events"]] == pytest.approx(
            [e["gain"] * level for e in unstaged["events"]], abs=1e-4
        )
    assert score["mix"] == PRESET_DATA["mix"]


def test_mix_must_cover_every_layer():
    with pytest.raises(ComposeError, match="mix"):
        make_preset(mix={"puls": 1.0})


def test_punctuation_marks_sit_after_their_word_in_the_verse(pipeline):
    analysis = pipeline.analyze("Wer kommt?\nEr ruft: komm!\nDer Tag endet.").to_dict()
    marks = [(m["bar"], m["step"], m["text"]) for m in run(analysis)["punctuation"]]
    assert marks == [(0, 15, "?"), (1, 11, ":"), (1, 15, "!"), (2, 15, ".")]


def test_commas_and_dashes_mark_phrase_boundaries_inside_a_verse(pipeline):
    analysis = pipeline.analyze("Der Hund, der Mann – er geht.\nDer Tag endet.").to_dict()
    marks = [(m["bar"], m["step"], m["text"], m["inside"]) for m in run(analysis)["punctuation"]]
    assert marks == [(0, 5, ",", True), (0, 11, "–", True), (0, 15, ".", False), (1, 15, ".", False)]


def note_of(degree, intervals=(0, 3, 5, 7, 10)):
    octave, index = divmod(degree, len(intervals))
    return intervals[index] + 12 * octave


def test_every_event_of_a_marked_bar_records_the_mark_once(pipeline):
    analysis = pipeline.analyze("Er ruft den Hund und die Katze laut!\nDer Tag endet.").to_dict()
    puls = [e for e in layer(run(analysis), "puls")["events"] if e["bar"] == 0]
    assert len(puls) > 1
    assert all(e["source"]["punctuation"] == ["!"] for e in puls)


def test_note_lengths_do_not_depend_on_phrase_length(pipeline):
    analysis = pipeline.analyze("Hunde bellen.\nDer alte Mann geht langsam durch den dunklen Wald.").to_dict()
    score = compose(analysis, ComposePreset.from_dict(PRESET_DATA), make_library(), sample_seed="fixed")
    for name, length in (("puls", 1.0), ("motiv", 2)):
        events = layer(score, name)["events"]
        assert {e["bar"] for e in events} == {0, 1}
        assert {e["legato"] for e in events} == {length}


def _bar_pattern(events, bar):
    return sorted(
        (e["step"] - bar * 16, e["s"], e["note"], e["gain"], e["legato"]) for e in events if e["bar"] == bar
    )


A = ["DET", "NOUN", "VERB"]
B = ["PRON", "VERB", "ADV", "ADJ"]


def test_verses_of_the_same_structure_play_the_same_bar():
    score = run(fixture_analysis(A, B, A, ["NOUN", "VERB"]), profile=FULL_VARIATION)
    for name in ("puls", "motiv"):
        events = layer(score, name)["events"]
        assert _bar_pattern(events, 2) == _bar_pattern(events, 0)
        assert _bar_pattern(events, 1) != _bar_pattern(events, 0)


def test_the_verb_share_sets_the_variation_and_moves_no_note(pilger, score):
    varied = run(pilger, sample_seed=score["sample_seed"], profile={"variation": {"verb_share": [0.0, 0.01]}})
    assert varied["profile"]["variation"]["norm"] == 1.0
    assert score["profile"]["variation"]["norm"] == 0.0
    for name in ("puls", "bass", "motiv", "boegen", "leitwort"):
        assert [e["step"] for e in layer(varied, name)["events"]] == [e["step"] for e in layer(score, name)["events"]]



def _ev(bar, step, gain=0.8, note=None, degree=None):
    source = {} if degree is None else {"degree": degree}
    return {"bar": bar, "step": bar * 16 + step, "s": "x:0", "note": note, "gain": gain, "legato": 1, "source": source}


def _layers(**events):
    return [{"name": name, "events": events.get(name, [])} for name in ("puls", "bass", "motiv", "boegen", "leitwort")]


def _mark(bar, step, text, inside=True):
    return {"bar": bar, "step": step, "text": text, "inside": inside}


def test_question_raises_the_last_motif_note_of_its_bar():
    layers = _layers(motiv=[_ev(0, 0, note=3, degree=1), _ev(0, 4, note=5, degree=2), _ev(1, 4, note=5, degree=2)])
    effects = apply_punctuation(layers, [_mark(0, 15, "?")], make_preset())
    motiv = layers[2]["events"]
    assert [e["note"] for e in motiv] == [3, 7, 5]
    assert motiv[1]["source"]["punctuation"] == ["?"]
    assert effects[0]["effect"] == "raise last motif note"


def test_period_accents_the_last_bass_note_before_it():
    layers = _layers(bass=[_ev(0, 2, gain=0.8), _ev(0, 10, gain=0.8), _ev(1, 0, gain=0.8)])
    apply_punctuation(layers, [_mark(0, 8, "."), _mark(2, 15, ".")], make_preset())
    assert [e["gain"] for e in layers[1]["events"]] == pytest.approx([0.8 * 10 ** (3 / 80), 0.8, 0.8], abs=1e-4)


def test_colon_and_semicolon_keep_every_pulse_hit():
    layers = _layers(puls=[_ev(0, 6), _ev(0, 8), _ev(0, 9), _ev(0, 10), _ev(1, 8)])
    effects = apply_punctuation(layers, [_mark(0, 8, ":")], make_preset())
    assert [e["step"] for e in layers[0]["events"]] == [6, 8, 9, 10, 24]
    assert effects[0]["effect"] == "cut puls (0 hits) and motiv (0 notes) at the mark"


def test_a_phrase_boundary_only_cuts_notes_that_sound_into_it():
    held = _ev(0, 4)
    held["legato"] = 6
    layers = _layers(puls=[_ev(0, 0), _ev(0, 8), _ev(0, 9), _ev(1, 8)], motiv=[held, _ev(0, 8)])
    effects = apply_punctuation(layers, [_mark(0, 8, ",")], make_preset())
    assert [(e["step"], e["legato"]) for e in layers[0]["events"]] == [(0, 1), (8, 1), (9, 1), (24, 1)]
    assert [(e["step"], e["legato"]) for e in layers[2]["events"]] == [(4, 4), (8, 1)]
    assert effects[0]["effect"] == "cut puls (0 hits) and motiv (1 notes) at the mark"


def test_a_mark_at_the_end_of_a_verse_leaves_no_rest():
    layers = _layers(puls=[_ev(0, 15)], motiv=[_ev(0, 15)])
    apply_punctuation(layers, [_mark(0, 15, ",", inside=False)], make_preset())
    assert [len(layers[0]["events"]), len(layers[2]["events"])] == [1, 1]


def test_exclamation_lifts_the_whole_bar():
    layers = _layers(puls=[_ev(1, 0)], bass=[_ev(1, 4)], motiv=[_ev(0, 0)])
    apply_punctuation(layers, [_mark(1, 15, "!")], make_preset())
    assert layers[0]["events"][0]["gain"] == pytest.approx(0.8 * 10 ** (3 / 80), abs=1e-4)
    assert layers[1]["events"][0]["gain"] == pytest.approx(0.8 * 10 ** (3 / 80), abs=1e-4)
    assert layers[2]["events"][0]["gain"] == 0.8
