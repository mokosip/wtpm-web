from __future__ import annotations

import pytest

from helpers import make_document

from wtpm.analysis import analyze
from wtpm.config import AnalysisConfig


def _comma_document():
    return make_document(
        [[
            {"text": "well", "pos": "ADV", "head": None},
            {"text": ",", "pos": "PUNCT", "head": 0, "tight": True},
            {"text": "then", "pos": "ADV", "head": None},
        ]]
    )


def test_boundary_policy_is_recorded_in_export():
    analysis = analyze(_comma_document(), AnalysisConfig())
    payload = analysis.to_dict()
    assert payload["analysis"]["settings"]["boundary_policy"] == (
        "sentence_and_punctuation"
    )


def test_disabling_punctuation_break_restores_adjacency():
    document = _comma_document()
    broke = analyze(document, AnalysisConfig(break_on_punctuation=True))
    joined = analyze(document, AnalysisConfig(break_on_punctuation=False))

    assert broke.by_type("pos_ngram", length=2) == []
    assert {tuple(p.values) for p in joined.by_type("pos_ngram", length=2)} == {
        ("ADV", "ADV")
    }
    assert joined.to_dict()["analysis"]["settings"]["boundary_policy"] == "sentence"


def test_punctuation_is_never_counted_as_a_word():
    analysis = analyze(_comma_document(), AnalysisConfig(break_on_punctuation=False))
    values = {tuple(p.values) for p in analysis.by_type("pos")}
    assert ("PUNCT",) not in values
    assert values == {("ADV",)}


def test_transitions_do_not_span_punctuation_when_breaking():
    document = _comma_document()
    analysis = analyze(document, AnalysisConfig(break_on_punctuation=True))
    assert analysis.by_type("pos_transition") == []
