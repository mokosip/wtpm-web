"""Hand-built document fixtures.

Tests build documents explicitly so that every expected count is independent of
a statistical model. Token dictionaries use:

    text, pos, lemma, dep, head (index within the sentence, None for the root),
    tag, morph, tight (no space before this token)
"""

from __future__ import annotations

from wtpm.schema import Document, Line, Paragraph, Sentence, Token


def make_document(sentences: list[list[dict]], language: str = "en") -> Document:
    tokens: list[Token] = []
    built_sentences: list[Sentence] = []
    text = ""
    cursor = 0

    for s_index, spec in enumerate(sentences, start=1):
        sentence_id = f"s{s_index}"
        sentence_start = None
        token_ids: list[str] = []

        for position, raw in enumerate(spec):
            if not raw.get("tight") and (position or s_index > 1):
                text += " "
                cursor += 1
            start = cursor
            text += raw["text"]
            cursor += len(raw["text"])
            if sentence_start is None:
                sentence_start = start

            token_id = f"t{len(tokens) + 1}"
            head = raw.get("head")
            token = Token(
                id=token_id,
                index=len(tokens),
                text=raw["text"],
                start=start,
                end=cursor,
                pos=raw.get("pos", ""),
                tag=raw.get("tag", ""),
                lemma=raw.get("lemma", raw["text"]),
                morph=dict(raw.get("morph", {})),
                is_punct=raw.get("is_punct", raw.get("pos") == "PUNCT"),
                is_space=raw.get("is_space", False),
                eligible=raw.get(
                    "eligible",
                    raw.get("pos") not in ("PUNCT", "SPACE", ""),
                ),
                dep=raw.get("dep", ""),
                head_id=f"{sentence_id}:{head}" if head is not None else None,
                sentence_id=sentence_id,
            )
            tokens.append(token)
            token_ids.append(token_id)

        for token in tokens[-len(spec) :]:
            if token.head_id is not None:
                local = int(token.head_id.split(":")[1])
                token.head_id = token_ids[local]

        root = next((t.id for t in tokens[-len(spec) :] if t.head_id is None), None)
        built_sentences.append(
            Sentence(
                id=sentence_id,
                index=s_index - 1,
                start=sentence_start or 0,
                end=cursor,
                token_ids=token_ids,
                root_token_id=root,
            )
        )

    line = Line(
        index=0,
        start=0,
        end=len(text),
        token_ids=[t.id for t in tokens],
        sentence_ids=[s.id for s in built_sentences],
    )
    paragraph = Paragraph(
        index=0,
        start=0,
        end=len(text),
        line_indices=[0],
        sentence_ids=[s.id for s in built_sentences],
    )
    return Document(
        text=text,
        language=language,
        tokens=tokens,
        sentences=built_sentences,
        lines=[line],
        paragraphs=[paragraph],
    )


def spec_sentences() -> list[list[dict]]:
    """The illustrative example from section 10 of the concept document."""
    return [
        [
            {"text": "The", "pos": "DET", "lemma": "the", "dep": "det", "head": 2},
            {"text": "quiet", "pos": "ADJ", "lemma": "quiet", "dep": "amod", "head": 2},
            {
                "text": "river",
                "pos": "NOUN",
                "lemma": "river",
                "dep": "nsubj",
                "head": 3,
                "morph": {"Number": "Sing"},
            },
            {
                "text": "carries",
                "pos": "VERB",
                "lemma": "carry",
                "dep": "ROOT",
                "head": None,
                "morph": {"Tense": "Pres", "Person": "3", "Number": "Sing"},
            },
            {
                "text": "stones",
                "pos": "NOUN",
                "lemma": "stone",
                "dep": "obj",
                "head": 3,
                "morph": {"Number": "Plur"},
            },
            {"text": ".", "pos": "PUNCT", "lemma": ".", "dep": "punct", "head": 3, "tight": True},
        ],
        [
            {"text": "The", "pos": "DET", "lemma": "the", "dep": "det", "head": 2},
            {"text": "restless", "pos": "ADJ", "lemma": "restless", "dep": "amod", "head": 2},
            {
                "text": "ocean",
                "pos": "NOUN",
                "lemma": "ocean",
                "dep": "nsubj",
                "head": 3,
                "morph": {"Number": "Sing"},
            },
            {
                "text": "carries",
                "pos": "VERB",
                "lemma": "carry",
                "dep": "ROOT",
                "head": None,
                "morph": {"Tense": "Pres", "Person": "3", "Number": "Sing"},
            },
            {
                "text": "ships",
                "pos": "NOUN",
                "lemma": "ship",
                "dep": "obj",
                "head": 3,
                "morph": {"Number": "Plur"},
            },
            {"text": ".", "pos": "PUNCT", "lemma": ".", "dep": "punct", "head": 3, "tight": True},
        ],
    ]
