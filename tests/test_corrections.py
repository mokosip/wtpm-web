from __future__ import annotations

import pytest

from helpers import make_document

from wtpm.analysis import analyze
from wtpm.config import AnalysisConfig
from wtpm.corrections import CorrectionError, apply_corrections, parse_corrections


def _document():
    return make_document(
        [
            [
                {"text": "golden", "pos": "VERB", "lemma": "gold", "dep": "ROOT", "head": None},
                {"text": "golden", "pos": "VERB", "lemma": "gold", "dep": "oc", "head": 0},
            ],
            [{"text": "rain", "pos": "NOUN", "dep": "ROOT", "head": None}],
        ],
        language="de",
    )


def test_correction_is_bound_to_one_position_not_to_the_word():
    document = _document()
    second = document.tokens[1]
    apply_corrections(
        document,
        parse_corrections(
            {"corrections": [{"token": {"start": second.start, "text": "golden"}, "pos": "ADJ"}]}
        ),
    )

    assert [t.pos for t in document.tokens[:2]] == ["VERB", "ADJ"]
    assert document.tokens[0].model_annotation is None
    assert second.model_annotation == {"pos": "VERB"}


def test_unchanged_values_are_not_recorded_as_manual():
    document = _document()
    apply_corrections(
        document,
        parse_corrections({"corrections": [{"token": {"start": 0, "text": "golden"}, "pos": "VERB"}]}),
    )
    assert document.tokens[0].model_annotation is None


def test_text_mismatch_at_offset_is_rejected():
    with pytest.raises(CorrectionError, match="no token 'gold'"):
        apply_corrections(
            _document(),
            parse_corrections({"corrections": [{"token": {"start": 0, "text": "gold"}, "pos": "ADJ"}]}),
        )


def test_head_outside_the_sentence_is_rejected():
    document = _document()
    rain = document.tokens[2]
    with pytest.raises(CorrectionError, match="same sentence"):
        apply_corrections(
            document,
            parse_corrections(
                {
                    "corrections": [
                        {
                            "token": {"start": document.tokens[1].start, "text": "golden"},
                            "head": {"start": rain.start, "text": "rain"},
                        }
                    ]
                }
            ),
        )


def test_head_change_that_breaks_the_tree_is_rejected():
    document = _document()
    first, second = document.tokens[:2]
    with pytest.raises(CorrectionError, match="exactly one root"):
        apply_corrections(
            document,
            parse_corrections(
                {
                    "corrections": [
                        {
                            "token": {"start": first.start, "text": "golden"},
                            "head": {"start": second.start, "text": "golden"},
                            "dep": "mo",
                        }
                    ]
                }
            ),
        )


def test_unknown_fields_and_pos_values_are_rejected():
    with pytest.raises(CorrectionError, match="unknown field"):
        parse_corrections({"corrections": [{"token": {"start": 0, "text": "golden"}, "case": "Nom"}]})
    with pytest.raises(CorrectionError, match="universal POS"):
        parse_corrections({"corrections": [{"token": {"start": 0, "text": "golden"}, "pos": "ADJD"}]})


def test_corrected_pos_feeds_every_sequence_statistic():
    document = _document()
    apply_corrections(
        document,
        parse_corrections(
            {"corrections": [{"token": {"start": document.tokens[1].start, "text": "golden"}, "pos": "ADJ"}]}
        ),
    )
    analysis = analyze(document, AnalysisConfig())

    assert {tuple(p.values): p.count for p in analysis.by_type("pos")} == {
        ("VERB",): 1,
        ("ADJ",): 1,
        ("NOUN",): 1,
    }
    (bigram,) = analysis.by_type("pos_ngram", length=2)
    assert bigram.values == ["VERB", "ADJ"]
    assert bigram.manual_occurrences == 1
    (transition,) = analysis.by_type("pos_transition")
    assert transition.values == ["VERB", "ADJ"]
    (surface,) = [p for p in analysis.by_type("surface", length=2)]
    assert surface.manual_occurrences == 0
