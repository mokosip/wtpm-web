from __future__ import annotations

import json
from pathlib import Path

import pytest

import spacy
from spacy.tokens import Doc

from wtpm.analysis import analyze
from wtpm.config import AnalysisConfig
from wtpm.export import to_json
from wtpm.ingest import build_document
from wtpm.pipeline import DEFAULT_MODELS, Pipeline

POEM = "Ein Fichtenbaum steht einsam\nIm Norden auf kahler Höh’.\n"
# Heinrich Heine, "Ein Fichtenbaum steht einsam" (1827), public domain.
HEINE = (Path(__file__).parents[1] / "examples" / "heine-ein-fichtenbaum.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pipeline():
    return Pipeline(language="de")


@pytest.fixture(scope="module")
def poem_analysis(pipeline):
    return pipeline.analyze(POEM, AnalysisConfig(sequence_lengths=(2, 3)))


def test_source_text_is_preserved_byte_for_byte(poem_analysis):
    assert poem_analysis.document.text == POEM


def test_token_offsets_match_source_unicode_positions(poem_analysis):
    text = poem_analysis.document.text
    for token in poem_analysis.document.tokens:
        assert text[token.start : token.end] == token.text


def test_sentence_roots_have_null_heads(poem_analysis):
    document = poem_analysis.document
    assert document.sentences
    for sentence in document.sentences:
        assert sentence.root_token_id is not None
        root = document.token(sentence.root_token_id)
        assert root.head_id is None
        assert root.sentence_id == sentence.id


def test_non_root_tokens_point_at_an_existing_token(poem_analysis):
    document = poem_analysis.document
    ids = {t.id for t in document.tokens}
    for token in document.tokens:
        if token.head_id is not None:
            assert token.head_id in ids
            assert token.head_id != token.id


def test_lines_are_preserved_separately_from_sentences(poem_analysis):
    document = poem_analysis.document
    assert len(document.lines) == 2
    assert all(line.sentence_ids for line in document.lines)


def test_paragraphs_group_blank_line_separated_blocks(pipeline):
    text = "Erster Satz.\n\nZweiter Satz.\n"
    document = pipeline.analyze(text).document
    assert len(document.paragraphs) == 2
    assert len(document.lines) == 2


def test_blank_lines_do_not_become_sentences(pipeline):
    document = pipeline.analyze(HEINE).document
    assert [HEINE[s.start : s.end] for s in document.sentences] == [
        "Ein Fichtenbaum steht einsam\nIm Norden auf kahler Höh’.",
        "Ihn schläfert;",
        "mit weißer Decke\nUmhüllen ihn Eis und Schnee.",
        "Er träumt von einer Palme,\nDie, fern im Morgenland,\nEinsam und schweigend trauert\nAuf brennender Felsenwand.",
    ]
    assert sorted(i for s in document.sentences for i in s.token_ids) == sorted(t.id for t in document.tokens)


def test_dependency_edges_exclude_punctuation_and_roots(poem_analysis):
    document = poem_analysis.document
    total = sum(p.count for p in poem_analysis.by_type("dependency"))
    assert total > 0
    for pattern in poem_analysis.by_type("dependency"):
        assert pattern.denominator.count == total
        for occurrence in pattern.occurrences:
            head, dependent = (document.token(t) for t in occurrence.token_ids)
            assert dependent.head_id == head.id
            assert not head.is_punct and not dependent.is_punct
            assert dependent.dep not in {"ROOT", "punct"}


def test_export_is_valid_json_with_required_provenance(poem_analysis):
    payload = json.loads(to_json(poem_analysis))
    assert payload["schema_version"]
    assert payload["document"]["text"] == POEM
    assert payload["document"]["language"] == "de"
    assert payload["analysis"]["model"] == DEFAULT_MODELS["de"]
    assert payload["analysis"]["model_version"]
    assert payload["analysis"]["library_version"]
    assert payload["analysis"]["settings"]["boundary_policy"] == (
        "sentence_and_punctuation"
    )
    assert payload["tokens"] and payload["sentences"] and payload["patterns"]


def test_export_counts_agree_with_occurrences(poem_analysis):
    for pattern in poem_analysis.patterns:
        assert pattern.count == len(pattern.occurrences)
        assert pattern.count <= pattern.denominator.count


def test_empty_input_yields_empty_patterns(pipeline):
    analysis = pipeline.analyze("")
    assert analysis.patterns == []
    assert analysis.warnings


def test_punctuation_only_input_yields_warning(pipeline):
    analysis = pipeline.analyze("?!")
    assert analysis.by_type("pos") == []
    assert analysis.warnings


def test_sequences_stay_inside_single_sentences(poem_analysis):
    document = poem_analysis.document
    for pattern in poem_analysis.by_type("pos_ngram"):
        for occurrence in pattern.occurrences:
            sentence_ids = {
                document.token(t).sentence_id for t in occurrence.token_ids
            }
            assert sentence_ids == {occurrence.sentence_id}


def test_a_whitespace_root_leaves_the_sentence_without_word_root():
    text = "Hallo\nWelt"
    doc = Doc(
        spacy.blank("de").vocab,
        words=["Hallo", "\n", "Welt"],
        spaces=[False, False, False],
        heads=[1, 1, 1],
        deps=["mo", "ROOT", "nk"],
        pos=["NOUN", "SPACE", "NOUN"],
        sent_starts=[True, False, False],
    )
    document = build_document(doc, text, "de")
    (sentence,) = document.sentences
    assert sentence.root_token_id is None
    assert [t.head_id for t in document.tokens if t.eligible] == [None, None]
    warnings = analyze(document, AnalysisConfig()).warnings
    assert any("s1" in w and "whitespace" in w for w in warnings)
