from __future__ import annotations

import pytest

from helpers import make_document, spec_sentences

from wtpm.analysis import analyze
from wtpm.config import AnalysisConfig


@pytest.fixture()
def spec_analysis():
    return analyze(make_document(spec_sentences(), language="en"), AnalysisConfig())


def test_source_text_is_preserved():
    doc = make_document(spec_sentences())
    assert doc.text == (
        "The quiet river carries stones. The restless ocean carries ships."
    )


def test_token_offsets_recover_source_substrings():
    doc = make_document(spec_sentences())
    for token in doc.tokens:
        assert doc.text[token.start : token.end] == token.text


def test_occurrences_reference_existing_tokens_in_order(spec_analysis):
    doc = spec_analysis.document
    known = {token.id: token for token in doc.tokens}
    contiguous = {"pos_ngram", "pos_transition", "surface", "lemma"}
    for pattern in spec_analysis.patterns:
        assert len(pattern.occurrences) == pattern.count
        for occurrence in pattern.occurrences:
            assert occurrence.sentence_id in {s.id for s in doc.sentences}
            indices = [known[token_id].index for token_id in occurrence.token_ids]
            assert {known[t].sentence_id for t in occurrence.token_ids} == {
                occurrence.sentence_id
            }
            if pattern.type in contiguous:
                assert indices == list(
                    range(indices[0], indices[0] + len(indices))
                )


def test_dependency_occurrences_are_ordered_head_then_dependent(spec_analysis):
    doc = spec_analysis.document
    known = {token.id: token for token in doc.tokens}
    edges = [
        occurrence
        for pattern in spec_analysis.by_type("dependency")
        for occurrence in pattern.occurrences
    ]
    assert edges
    for occurrence in edges:
        head, dependent = (known[t] for t in occurrence.token_ids)
        assert dependent.head_id == head.id
        assert occurrence.head_after_dependent == (head.index > dependent.index)


def test_category_frequencies_match_section_10_3(spec_analysis):
    counts = {
        pattern.values[0]: pattern.count
        for pattern in spec_analysis.by_type("pos")
    }
    assert counts == {"NOUN": 4, "DET": 2, "ADJ": 2, "VERB": 2}
    noun = next(p for p in spec_analysis.by_type("pos") if p.values == ["NOUN"])
    assert noun.denominator.kind == "eligible_word_tokens"
    assert noun.denominator.count == 10
    assert noun.relative_frequency == pytest.approx(0.4)


def test_trigram_windows_match_section_10_4(spec_analysis):
    trigrams = {tuple(p.values): p for p in spec_analysis.by_type("pos_ngram", length=3)}
    assert {k: v.count for k, v in trigrams.items()} == {
        ("DET", "ADJ", "NOUN"): 2,
        ("ADJ", "NOUN", "VERB"): 2,
        ("NOUN", "VERB", "NOUN"): 2,
    }
    for pattern in trigrams.values():
        assert pattern.denominator.kind == "eligible_pos_windows"
        assert pattern.denominator.length == 3
        assert pattern.denominator.count == 6
        assert pattern.relative_frequency == pytest.approx(2 / 6)


def test_each_sequence_length_has_its_own_denominator(spec_analysis):
    windows_per_sentence = {2: 4, 3: 3, 4: 2}
    for length, expected in windows_per_sentence.items():
        patterns = spec_analysis.by_type("pos_ngram", length=length)
        assert patterns
        for pattern in patterns:
            assert pattern.denominator.count == expected * 2


def test_overlapping_windows_are_counted(spec_analysis):
    bigrams = spec_analysis.by_type("pos_ngram", length=2)
    assert sum(p.count for p in bigrams) == 4 * 2
    assert {tuple(p.values): p.count for p in bigrams}[("ADJ", "NOUN")] == 2


def test_transitions_match_section_10_6(spec_analysis):
    transitions = {
        (p.values[0], p.values[1]): p for p in spec_analysis.by_type("pos_transition")
    }
    assert {k: v.count for k, v in transitions.items()} == {
        ("DET", "ADJ"): 2,
        ("ADJ", "NOUN"): 2,
        ("NOUN", "VERB"): 2,
        ("VERB", "NOUN"): 2,
    }
    det = transitions[("DET", "ADJ")]
    assert det.denominator.kind == "eligible_outgoing_transitions"
    assert det.denominator.count == 2
    assert det.relative_frequency == pytest.approx(1.0)


def test_transition_denominator_excludes_run_final_tokens(spec_analysis):
    nouns = [
        p
        for p in spec_analysis.by_type("pos_transition")
        if p.values[0] == "NOUN"
    ]
    assert sum(p.count for p in nouns) == 2
    assert {p.denominator.count for p in nouns} == {2}


def test_dependency_patterns_exclude_root_and_punctuation(spec_analysis):
    dependency = spec_analysis.by_type("dependency")
    assert sum(p.count for p in dependency) == 8
    for pattern in dependency:
        assert pattern.denominator.kind == "eligible_dependency_edges"
        assert pattern.denominator.count == 8
        assert pattern.values[1] != "ROOT"
        assert "PUNCT" not in pattern.values
    assert {tuple(p.values): p.count for p in dependency} == {
        ("NOUN", "det", "DET"): 2,
        ("NOUN", "amod", "ADJ"): 2,
        ("VERB", "nsubj", "NOUN"): 2,
        ("VERB", "obj", "NOUN"): 2,
    }


def test_dependency_edge_records_head_side(spec_analysis):
    subject = next(
        p for p in spec_analysis.by_type("dependency") if p.values == ["VERB", "nsubj", "NOUN"]
    )
    heads_after = [occ.head_after_dependent for occ in subject.occurrences]
    assert heads_after == [True, True]


def test_morphology_reports_coverage_per_feature(spec_analysis):
    morphology = spec_analysis.by_type("morphology")
    coverage = {tuple(p.values): p for p in morphology if len(p.values) == 1}
    assert set(coverage) == {("Number",), ("Tense",), ("Person",)}

    number_coverage = coverage[("Number",)]
    assert number_coverage.count == 6
    assert number_coverage.denominator.kind == "eligible_word_tokens"
    assert number_coverage.denominator.count == 10
    assert number_coverage.relative_frequency == pytest.approx(0.6)

    values = {tuple(p.values): p for p in morphology if len(p.values) == 2}
    assert values[("Number", "Sing")].count == 4
    assert values[("Number", "Plur")].count == 2
    assert values[("Tense", "Pres")].count == 2
    for pattern in values.values():
        assert pattern.denominator.kind == "tokens_with_feature"
        assert pattern.denominator.feature == pattern.values[0]
    assert values[("Number", "Sing")].denominator.count == 6
    assert values[("Number", "Sing")].relative_frequency == pytest.approx(4 / 6)


def test_surface_and_lemma_repetition(spec_analysis):
    surface = {
        tuple(p.values): p.count
        for p in spec_analysis.by_type("surface", length=1)
    }
    assert surface[("carries",)] == 2
    lemma = {tuple(p.values): p.count for p in spec_analysis.by_type("lemma", length=1)}
    assert lemma[("carry",)] == 2
    assert lemma[("stone",)] == 1


def test_exported_counts_agree_with_occurrence_lists(spec_analysis):
    for pattern in spec_analysis.patterns:
        assert pattern.count == len(pattern.occurrences)


def test_sequence_windows_do_not_cross_punctuation():
    doc = make_document(
        [
            [
                {"text": "well", "pos": "ADV", "head": None},
                {"text": ",", "pos": "PUNCT", "head": 0, "tight": True},
                {"text": "then", "pos": "ADV", "head": None},
            ]
        ]
    )
    analysis = analyze(doc, AnalysisConfig())
    bigrams = analysis.by_type("pos_ngram", length=2)
    assert bigrams == []
    assert {p.denominator.count for p in analysis.by_type("pos")} == {2}


def test_sequence_windows_do_not_cross_sentence_boundaries():
    doc = make_document(
        [
            [{"text": "go", "pos": "VERB", "head": None}, {"text": "now", "pos": "ADV", "head": 0}],
            [{"text": "stop", "pos": "VERB", "head": None}, {"text": "here", "pos": "ADV", "head": 0}],
        ]
    )
    analysis = analyze(doc, AnalysisConfig())
    assert {tuple(p.values) for p in analysis.by_type("pos_ngram", length=2)} == {("VERB", "ADV")}


def test_one_word_sentence_has_no_windows():
    doc = make_document([[{"text": "Stop", "pos": "VERB", "head": None}]])
    analysis = analyze(doc, AnalysisConfig())
    assert analysis.by_type("pos_ngram") == []
    assert analysis.by_type("pos_transition") == []
    assert [p.count for p in analysis.by_type("pos")] == [1]


def test_punctuation_only_input_produces_no_word_patterns():
    doc = make_document(
        [[{"text": "?!", "pos": "PUNCT", "head": None, "tight": True}]]
    )
    analysis = analyze(doc, AnalysisConfig())
    assert analysis.by_type("pos") == []
    assert analysis.by_type("pos_ngram") == []
    assert analysis.by_type("dependency") == []
    assert analysis.warnings


def test_empty_input_produces_empty_analysis():
    doc = make_document([])
    analysis = analyze(doc, AnalysisConfig())
    assert analysis.patterns == []
    assert analysis.document.text == ""


def test_case_insensitive_surface_mode_is_default():
    doc = make_document(
        [
            [{"text": "River", "pos": "NOUN", "head": None}],
            [{"text": "river", "pos": "NOUN", "head": None}],
        ]
    )
    default = analyze(doc, AnalysisConfig())
    surface = {tuple(p.values): p.count for p in default.by_type("surface", length=1)}
    assert surface == {("river",): 2}

    exact = analyze(doc, AnalysisConfig(surface_comparison="exact"))
    exact_surface = {tuple(p.values): p.count for p in exact.by_type("surface", length=1)}
    assert exact_surface == {("River",): 1, ("river",): 1}


def test_surface_comparison_never_alters_tokens():
    doc = make_document(
        [
            [{"text": "River", "pos": "NOUN", "head": None}],
            [{"text": "river", "pos": "NOUN", "head": None}],
        ]
    )
    analyze(doc, AnalysisConfig())
    assert [t.text for t in doc.tokens] == ["River", "river"]


def test_line_boundaries_do_not_break_sentences():
    doc = make_document(spec_sentences())
    assert len(doc.lines) == 1
    assert len(doc.paragraphs) == 1
    assert len(doc.sentences) == 2
