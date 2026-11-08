from __future__ import annotations

from pathlib import Path

import pytest

from wtpm.config import AnalysisConfig
from wtpm.pipeline import Pipeline

PILGER = (Path(__file__).parent / "fixtures" / "pilger.txt").read_text(encoding="utf-8")
POEM = (
    "Wie abends sich vom Quittenbaume\n"
    "Der Duft der Frucht zur Erde senkt,\n"
    "So fällt auf mich vom Sternenraume\n"
    "Der Hauch des Gottes, der mich lenkt,\n"
    "\n"
    "Wendet mein Haupt, schließt mir das Auge,\n"
    "Dass nur mein Herz noch hört und sieht,\n"
    "Raubt meinen Willen, ob ihm tauge\n"
    "Dies Herz als Saite seinem Lied.\n"
    "\n"
    "Ich lieg' verzückt und lausche, lausche:\n"
)
PROSE = (
    "Die Wirtschaftsauskunftei gibt über ihren Schufa-Score an, wie zahlungskräftig und "
    "kreditwürdig Kundinnen und Kunden sind. Bei Käufen erhält der Kunde das Blatt, in dem "
    "erklärt wird, dass und wie die Schufa Daten verarbeitet. Die Tigerente rollt."
)


@pytest.fixture(scope="module")
def pipeline():
    return Pipeline(language="de")


def _token(analysis, text):
    return next(t for t in analysis.document.tokens if t.text == text)


@pytest.fixture(scope="module")
def poem(pipeline):
    return pipeline.analyze(POEM, AnalysisConfig())


@pytest.fixture(scope="module")
def prose(pipeline):
    return pipeline.analyze(PROSE, AnalysisConfig())


@pytest.fixture(scope="module")
def pilger(pipeline):
    return pipeline.analyze(PILGER, AnalysisConfig())


def test_subjunctive_is_recognised(poem):
    tauge = _token(poem, "tauge")
    assert tauge.lemma == "taugen"
    assert tauge.morph["Mood"] == "Sub"


def test_verse_internal_verbs_are_verbs(poem):
    lausche = _token(poem, "lausche")
    assert (lausche.pos, lausche.lemma) == ("VERB", "lauschen")
    assert _token(poem, "hört").morph["VerbForm"] == "Fin"


def test_stanza_spanning_sentence_is_not_split_before_its_subject(poem):
    hauch = POEM.index("Der Hauch")
    assert all(sentence.start != hauch for sentence in poem.document.sentences)


def test_stanzas_ending_in_punctuation_get_no_sentence_hint(poem):
    assert poem.document.sentence_hints == []


def test_words_never_hang_on_line_breaks(poem):
    tokens = {t.id: t for t in poem.document.tokens}
    assert all(not tokens[t.head_id].is_space for t in poem.document.tokens if t.head_id)
    hauch = _token(poem, "Hauch")
    assert (tokens[hauch.head_id].text, hauch.dep) == ("fällt", "sb")
    edges = {
        (tokens[o.token_ids[0]].text, tokens[o.token_ids[1]].text)
        for p in poem.by_type("dependency")
        for o in p.occurrences
    }
    assert ("fällt", "Hauch") in edges


def test_finite_verb_in_embedded_clause(prose):
    assert _token(prose, "verarbeitet").morph["VerbForm"] == "Fin"


def test_compound_noun_keeps_its_lemma(prose):
    assert _token(prose, "Tigerente").lemma == "Tigerente"


@pytest.mark.parametrize("word", ["zahlungskräftig", "kreditwürdig"])
def test_predicative_adjectives_count_as_adjectives(prose, word):
    token = _token(prose, word)
    assert (token.tag, token.pos) == ("ADJD", "ADJ")


def test_adverbial_adjective_counts_as_adjective(pilger):
    golden = _token(pilger, "golden")
    assert (golden.tag, golden.pos) == ("ADJD", "ADJ")


def test_pilger_subject_and_rare_verb(pilger):
    pilger_token = _token(pilger, "Pilger")
    assert (pilger_token.morph["Case"], pilger_token.morph["Number"]) == ("Nom", "Sing")
    assert _token(pilger, "träuft").lemma == "träufen"
