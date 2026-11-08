from __future__ import annotations

import pytest

from wtpm.config import AnalysisConfig
from wtpm.pipeline import Pipeline

POEM = (
    "Der Hauch des Gottes, der mich lenkt,\n"
    "Wendet mein Haupt, schließt mir das Auge,\n"
    "Raubt meinen Willen.\n"
    "Ich lieg’ verzückt und lausche:\n"
    "Niemals geb' ich dies Spiel zum Tausche,\n"
    "Blätter fallen.\n"
    "Dann las ich Hans' Buch.\n"
)


@pytest.fixture(scope="module")
def pipeline():
    return Pipeline(language="de")


@pytest.fixture(scope="module")
def normalised(pipeline):
    return pipeline.analyze(POEM, AnalysisConfig())


@pytest.fixture(scope="module")
def raw(pipeline):
    return pipeline.analyze(POEM, AnalysisConfig(normalise_parser_input=False))


def _token(analysis, text):
    return next(t for t in analysis.document.tokens if t.text == text)


def _changes(analysis):
    return {(n.source, n.parser_input, n.rule) for n in analysis.document.normalisations}


def test_source_text_and_offsets_stay_untouched(normalised):
    document = normalised.document
    assert document.text == POEM
    for token in document.tokens:
        assert POEM[token.start : token.end] == token.text


def test_elided_verbs_get_their_lemma(normalised):
    assert _token(normalised, "lieg’").lemma == "liegen"
    assert _token(normalised, "geb'").lemma == "geben"


def test_capitalised_verse_starts_are_read_as_verbs(normalised):
    wendet = _token(normalised, "Wendet")
    raubt = _token(normalised, "Raubt")
    assert (wendet.lemma, wendet.morph["VerbForm"]) == ("wenden", "Fin")
    assert (raubt.lemma, raubt.morph["VerbForm"]) == ("rauben", "Fin")


def test_every_replacement_is_recorded(normalised):
    assert _changes(normalised) == {
        ("Wendet", "wendet", "verse_start_case"),
        ("Raubt", "raubt", "verse_start_case"),
        ("lieg’", "liege", "elision"),
        ("geb'", "gebe", "elision"),
    }
    exported = normalised.to_dict()
    assert exported["analysis"]["settings"]["normalise_parser_input"] is True
    entry = next(n for n in exported["document"]["normalisations"] if n["source"] == "Wendet")
    assert POEM[entry["start"] : entry["end"]] == "Wendet"


def test_nouns_sentence_starts_and_genitives_stay(normalised):
    sources = {source for source, _, _ in _changes(normalised)}
    assert not sources & {"Der", "Ich", "Niemals", "Blätter", "Dann", "Hans'"}


def test_normalisation_can_be_switched_off(raw):
    assert raw.document.normalisations == []
    assert raw.to_dict()["analysis"]["settings"]["normalise_parser_input"] is False
    assert _token(raw, "Wendet").lemma != "wenden"


SONG = (
    "In einem unbekannten Land\nVor gar nicht allzu langer Zeit\nWar eine Biene sehr bekannt\n\n"
    "Von der sprach alles weit und breit\nUnd diese Biene die ich meine, nennt sich Maja.\n"
)


def test_blank_line_after_an_unpunctuated_line_starts_a_sentence(pipeline):
    song = pipeline.analyze(SONG, AnalysisConfig())
    start = SONG.index("Von")
    assert [h.to_dict() for h in song.document.sentence_hints] == [{"start": start, "rule": "stanza_break"}]
    assert [SONG[s.start : s.end].split("\n")[0] for s in song.document.sentences] == [
        "In einem unbekannten Land",
        "Von der sprach alles weit und breit",
    ]
    assert all(n.source != "Von" for n in song.document.normalisations)
    assert song.to_dict()["document"]["sentence_hints"] == [{"start": start, "rule": "stanza_break"}]


def test_stanza_hints_follow_the_normalisation_switch(pipeline):
    raw_song = pipeline.analyze(SONG, AnalysisConfig(normalise_parser_input=False))
    assert raw_song.document.sentence_hints == []


MAJA = (
    "In einem unbekannten Land\nVor gar nicht allzu langer Zeit\nWar eine Biene sehr bekannt\n\n"
    "Von der sprach alles weit und breit\nUnd diese Biene die ich meine, nennt sich Maja.\n"
    "Kleine, freche, schlaue Biene Maja\n\n"
    "Maja fliegt durch ihre Welt, zeigt uns das was ihr gefällt\nWir treffen heute unsere Freundin Biene Maja\n"
    "Diese kleine, freche Biene Maja\n\n"
    "Maja, alle lieben Maja\nMaja, Maja\nMaja, Maja,Maja erzähle uns von dir!\n"
)


def test_a_hinted_line_only_breaks_after_sentence_final_punctuation(pipeline):
    song = pipeline.analyze(MAJA, AnalysisConfig())
    assert [MAJA[s.start : s.end].split("\n")[0] for s in song.document.sentences] == [
        "In einem unbekannten Land",
        "Von der sprach alles weit und breit",
        "Kleine, freche, schlaue Biene Maja",
        "Maja fliegt durch ihre Welt, zeigt uns das was ihr gefällt",
        "Maja, alle lieben Maja",
    ]
