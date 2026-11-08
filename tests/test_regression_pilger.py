from __future__ import annotations

from pathlib import Path

import pytest

from wtpm.config import AnalysisConfig
from wtpm.corrections import load_corrections
from wtpm.pipeline import Pipeline

FIXTURES = Path(__file__).parent / "fixtures"
TEXT = (FIXTURES / "pilger.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pipeline():
    return Pipeline(language="de", model="de_core_news_sm")


def _window_counts(analysis) -> dict[int, int]:
    return {
        length: sum(p.count for p in analysis.by_type("pos_ngram", length=length))
        for length in (2, 3, 4)
    }


def test_line_breaks_do_not_interrupt_sequences_under_punctuation_policy(pipeline):
    analysis = pipeline.analyze(TEXT, AnalysisConfig())

    assert analysis.analysis.settings["boundary_policy"] == "sentence_and_punctuation"
    assert _window_counts(analysis) == {2: 21, 3: 18, 4: 15}
    for length, expected in ((2, 21), (3, 18), (4, 15)):
        denominators = {
            p.denominator.count for p in analysis.by_type("pos_ngram", length=length)
        }
        assert denominators == {expected}


def test_verse_line_boundaries_are_selectable(pipeline):
    analysis = pipeline.analyze(TEXT, AnalysisConfig(break_on_lines=True))

    assert analysis.analysis.settings["boundary_policy"] == (
        "sentence_punctuation_and_line"
    )
    assert _window_counts(analysis) == {2: 19, 3: 15, 4: 11}


CORRECTIONS = load_corrections(FIXTURES / "pilger.corrections.json")


@pytest.fixture(scope="module")
def model_only(pipeline):
    return pipeline.analyze(TEXT, AnalysisConfig())


@pytest.fixture(scope="module")
def corrected(pipeline):
    return pipeline.analyze(TEXT, AnalysisConfig(), corrections=CORRECTIONS)


def _token(analysis, text):
    (token,) = [t for t in analysis.document.tokens if t.text == text]
    return token


def test_corrections_set_the_contextual_annotation(corrected):
    golden = _token(corrected, "golden")
    assert (golden.pos, golden.tag, golden.lemma, golden.morph) == (
        "ADJ",
        "ADJD",
        "golden",
        {"Degree": "Pos"},
    )
    assert golden.dep == "mo"
    assert golden.head_id == _token(corrected, "träuft").id

    pilger = _token(corrected, "Pilger")
    assert (pilger.morph["Case"], pilger.morph["Number"]) == ("Nom", "Sing")
    assert pilger.dep == "sb" and pilger.head_id == _token(corrected, "fühlt").id

    reiche = _token(corrected, "Reiche")
    assert (reiche.pos, reiche.tag) == ("NOUN", "NN")
    assert reiche.morph["Number"] == "Plur"

    assert _token(corrected, "träuft").lemma == "träufen"


def test_model_annotation_stays_distinguishable(model_only, corrected):
    golden_model = _token(model_only, "golden")
    golden = _token(corrected, "golden")

    assert golden_model.model_annotation is None
    assert golden.model_annotation["pos"] == golden_model.pos
    assert golden.model_annotation["lemma"] == golden_model.lemma
    assert golden.correction_note

    exported = {t["text"]: t for t in corrected.to_dict()["tokens"]}
    assert exported["golden"]["annotation_source"] == "manual"
    assert exported["golden"]["model_annotation"]["morph"] == golden_model.morph
    assert exported["fremde"]["annotation_source"] == "model"
    assert "model_annotation" not in exported["fremde"]


def _counts(analysis, pattern_type, length=None):
    return {tuple(p.values): p.count for p in analysis.by_type(pattern_type, length)}


def test_golden_creates_no_verb_or_subjunctive_patterns(corrected):
    golden = _token(corrected, "golden").id
    hätten = _token(corrected, "hätten").id

    for pattern_type in ("pos_ngram", "pos_transition"):
        for pattern in corrected.by_type(pattern_type):
            for occurrence in pattern.occurrences:
                if golden in occurrence.token_ids:
                    slot = occurrence.token_ids.index(golden)
                    assert pattern.values[slot] == "ADJ"

    (verbs,) = [p for p in corrected.by_type("pos") if p.values == ["VERB"]]
    assert golden not in {i for o in verbs.occurrences for i in o.token_ids}
    (subjunctive,) = [p for p in corrected.by_type("morphology") if p.values == ["Mood", "Sub"]]
    assert [o.token_ids for o in subjunctive.occurrences] == [[hätten]]
    assert _counts(corrected, "morphology")[("VerbForm", "Fin")] == 3


def test_dependent_statistics_are_recomputed(corrected):
    pos = {tuple(p.values): (p.count, p.denominator.count) for p in corrected.by_type("pos")}
    assert pos[("ADJ",)] == (3, 24)
    assert pos[("NOUN",)] == (5, 24)
    assert pos[("VERB",)] == (3, 24)
    assert ("PROPN",) not in pos
    (adj,) = [p for p in corrected.by_type("pos") if p.values == ["ADJ"]]
    assert adj.relative_frequency == pytest.approx(3 / 24)

    golden = _token(corrected, "golden").id
    edges = {
        tuple(o.token_ids): tuple(p.values)
        for p in corrected.by_type("dependency")
        for o in p.occurrences
    }
    assert edges[(_token(corrected, "träuft").id, golden)] == ("VERB", "mo", "ADJ")
    assert edges[(_token(corrected, "fühlt").id, _token(corrected, "träuft").id)] == (
        "VERB",
        "oc",
        "VERB",
    )
    (von,) = [t for t in corrected.document.tokens if t.text == "von" and t.start == 66]
    assert edges[(_token(corrected, "träuft").id, von.id)] == ("VERB", "mo", "ADP")
    assert not any(
        o.token_ids[0] == golden for p in corrected.by_type("dependency") for o in p.occurrences
    )
    total = sum(p.count for p in corrected.by_type("dependency"))
    assert {p.denominator.count for p in corrected.by_type("dependency")} == {total}

    numbers = {
        p.values[1]: {corrected.document.token(o.token_ids[0]).text for o in p.occurrences}
        for p in corrected.by_type("morphology")
        if p.values[0] == "Number" and len(p.values) == 2
    }
    assert "Pilger" in numbers["Sing"] and "Reiche" in numbers["Plur"]
    assert "Pilger" not in numbers["Plur"]

    lemmas = _counts(corrected, "lemma", 1)
    assert ("golden",) in lemmas and ("träufen",) in lemmas
    assert ("gold",) not in lemmas and ("träuftn",) not in lemmas


def test_manual_corrections_are_flagged_in_statistics(corrected):
    golden = _token(corrected, "golden").id
    for pattern in corrected.by_type("pos_ngram"):
        for occurrence in pattern.occurrences:
            if golden in occurrence.token_ids:
                assert golden in occurrence.manual_token_ids
    assert all(p.manual_occurrences == 0 for p in corrected.by_type("surface"))


def test_empty_warnings_are_not_a_linguistic_all_clear(model_only, corrected):
    model_payload = model_only.to_dict()
    assert model_payload["warnings"] == []
    assert model_payload["annotation_review"]["linguistic_verification"] == "not_performed"
    assert model_payload["annotation_review"]["warnings_scope"] == "technical_input_checks"

    review = corrected.to_dict()["annotation_review"]
    assert review["linguistic_verification"] == "partial_manual"
    assert review["manually_corrected_tokens"] == 6
    assert review["model_tokens"] == 18


def _bigram(analysis, first, second):
    ids = [_token(analysis, first).id, _token(analysis, second).id]
    for pattern in analysis.by_type("pos_ngram", 2):
        for occurrence in pattern.occurrences:
            if occurrence.token_ids == ids:
                return pattern, occurrence
    raise AssertionError(f"no bigram {first} {second}")


def test_sequences_record_crossed_verse_boundaries(model_only):
    pattern, occurrence = _bigram(model_only, "scheue", "Pilger")
    assert occurrence.line_ids == ["l1", "l2"]
    assert occurrence.line_breaks_after == [0]
    _, internal = _bigram(model_only, "fremde", "scheue")
    assert internal.line_ids == ["l1"]
    assert internal.line_breaks_after == []

    crossing = {
        length: sum(p.line_crossing_count for p in model_only.by_type("pos_ngram", length))
        for length in (2, 3, 4)
    }
    internal_counts = {
        length: sum(p.line_internal_count for p in model_only.by_type("pos_ngram", length))
        for length in (2, 3, 4)
    }
    assert crossing == {2: 2, 3: 3, 4: 4}
    assert internal_counts == {2: 19, 3: 15, 4: 11}
    for pattern in model_only.patterns:
        if pattern.type in {"pos_ngram", "pos_transition", "dependency"}:
            assert pattern.line_internal_count + pattern.line_crossing_count == pattern.count


def test_boundary_positions_are_reported_separately(model_only):
    positions: dict[tuple[int, ...], int] = {}
    for pattern in model_only.by_type("pos_ngram", 4):
        for profile in pattern.line_break_profiles():
            key = tuple(profile["breaks_after"])
            positions[key] = positions.get(key, 0) + profile["count"]
    assert positions == {(): 11, (0,): 1, (1,): 1, (2,): 2}


def test_line_internal_analysis_stays_available(pipeline):
    analysis = pipeline.analyze(TEXT, AnalysisConfig(break_on_lines=True))
    for pattern in analysis.by_type("pos_ngram"):
        assert pattern.line_crossing_count == 0


def test_dependencies_report_verse_crossing_independent_of_sequences(pipeline):
    for config in (AnalysisConfig(), AnalysisConfig(break_on_lines=True)):
        analysis = pipeline.analyze(TEXT, config)
        crossing = {
            (analysis.document.token(o.token_ids[0]).text, analysis.document.token(o.token_ids[1]).text): o.crosses_line
            for p in analysis.by_type("dependency")
            for o in p.occurrences
        }
        assert crossing[("fühlt", "Pilger")] is True
        assert crossing[("Heimlichkeiten", "ihre")] is False
