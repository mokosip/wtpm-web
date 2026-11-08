from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .schema import AnalysisIdentity, Document, Line, Normalisation, Paragraph, Sentence, SentenceHint, Token

PUNCT_POS = {"PUNCT", "SYM"}
SPACE_POS = {"SPACE"}
ROOT_DEPS = {"ROOT", "root"}


@dataclass(frozen=True)
class ModelInfo:
    name: str
    lang: str
    version: str
    spacy_version: str

    def identity(self, settings: dict) -> AnalysisIdentity:
        from datetime import datetime, timezone

        return AnalysisIdentity(
            library="spacy",
            library_version=self.spacy_version,
            model=self.name,
            model_version=self.version,
            settings=settings,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


def model_info(nlp) -> ModelInfo:
    import spacy

    return ModelInfo(
        name=f"{nlp.meta['lang']}_{nlp.meta['name']}",
        lang=nlp.meta["lang"],
        version=nlp.meta["version"],
        spacy_version=spacy.__version__,
    )


def build_document(
    doc,
    text: str,
    language: str,
    normalisations: Sequence[Normalisation] = (),
    sentence_hints: Sequence[SentenceHint] = (),
) -> Document:
    tokens: list[Token] = []
    id_by_alignment: dict[int, str] = {}

    for index, spacy_token in enumerate(doc):
        token_id = f"t{index + 1}"
        id_by_alignment[spacy_token.idx] = token_id
        tokens.append(
            Token(
                id=token_id,
                index=index,
                text=text[spacy_token.idx : spacy_token.idx + len(spacy_token.text)],
                start=spacy_token.idx,
                end=spacy_token.idx + len(spacy_token.text),
                pos=_pos(spacy_token) if doc.has_annotation("POS") else "",
                tag=spacy_token.tag_ if doc.has_annotation("TAG") else "",
                lemma=spacy_token.lemma_ if doc.has_annotation("LEMMA") else spacy_token.text,
                morph=dict(spacy_token.morph.to_dict()),
                is_punct=spacy_token.is_punct,
                is_space=spacy_token.is_space,
                eligible=_eligible(spacy_token),
                dep=spacy_token.dep_ if doc.has_annotation("DEP") else "",
                head_id=None,
                sentence_id="",
            )
        )

    for index, spacy_token in enumerate(doc):
        token = tokens[index]
        if doc.has_annotation("DEP"):
            head = _word_head(spacy_token)
            token.head_id = None if head is None else id_by_alignment.get(head.idx)

    sentences: list[Sentence] = []
    for s_index, span in enumerate(_span_sentences(doc)):
        sentence_id = f"s{s_index + 1}"
        token_ids = [tokens[i].id for i in range(span[0], span[1])]
        for i in range(span[0], span[1]):
            tokens[i].sentence_id = sentence_id
        root = next(
            (
                t.id
                for t in tokens[span[0] : span[1]]
                if t.head_id is None and not t.is_space and (t.dep in ROOT_DEPS or not doc.has_annotation("DEP"))
            ),
            None,
        )
        sentences.append(
            Sentence(
                id=sentence_id,
                index=s_index,
                start=span[2],
                end=span[3],
                token_ids=token_ids,
                root_token_id=root,
            )
        )

    lines, paragraphs = _layout(text, tokens, sentences)
    for token in tokens:
        if not token.sentence_id and sentences:
            token.sentence_id = sentences[-1].id

    return Document(
        text=text,
        language=language,
        tokens=tokens,
        sentences=sentences,
        lines=lines,
        paragraphs=paragraphs,
        normalisations=list(normalisations),
        sentence_hints=list(sentence_hints),
    )


def _pos(spacy_token) -> str:
    if spacy_token.tag_ == "ADJD":
        return "ADJ"
    return spacy_token.pos_


def _word_head(spacy_token):
    head = spacy_token.head
    while head.is_space and head.head.i != head.i:
        head = head.head
    if head.i == spacy_token.i or head.is_space:
        return None
    return head


def _eligible(spacy_token) -> bool:
    if spacy_token.is_space or spacy_token.is_punct:
        return False
    if spacy_token.pos_ in PUNCT_POS or spacy_token.pos_ in SPACE_POS:
        return False
    return bool(spacy_token.pos_)


def _span_sentences(doc) -> list[tuple[int, int, int, int]]:
    if not doc.has_annotation("SENT_START"):
        if len(doc) == 0:
            return []
        return [(0, len(doc), 0, len(doc.text))]
    spans: list[tuple[int, int, int, int]] = []
    pending = None
    for sent in doc.sents:
        anchors = [t for t in sent if not t.is_space]
        if not anchors:
            if spans:
                first, _, start, end = spans[-1]
                spans[-1] = (first, sent.end, start, end)
            elif pending is None:
                pending = sent.start
            continue
        first = sent.start if pending is None else pending
        pending = None
        spans.append((first, sent.end, anchors[0].idx, anchors[-1].idx + len(anchors[-1].text)))
    if not spans and len(doc):
        return [(0, len(doc), 0, len(doc.text))]
    return spans


def _layout(
    text: str, tokens: list[Token], sentences: list[Sentence]
) -> tuple[list[Line], list[Paragraph]]:
    raw_lines: list[tuple[int, int]] = []
    cursor = 0
    for segment in text.split("\n"):
        raw_lines.append((cursor, cursor + len(segment)))
        cursor += len(segment) + 1

    lines: list[Line] = []
    paragraphs: list[Paragraph] = []
    current_lines: list[int] = []
    paragraph_start = 0

    def close_paragraph(end: int) -> None:
        if not current_lines:
            return
        paragraphs.append(
            Paragraph(
                index=len(paragraphs),
                start=paragraph_start,
                end=end,
                line_indices=list(current_lines),
                sentence_ids=_sentences_in(paragraph_start, end, sentences),
            )
        )

    for start, end in raw_lines:
        if text[start:end].strip() == "":
            close_paragraph(start)
            current_lines = []
            paragraph_start = end + 1
            continue
        if not current_lines:
            paragraph_start = start
        lines.append(
            Line(
                index=len(lines),
                start=start,
                end=end,
                token_ids=[
                    t.id
                    for t in tokens
                    if t.start >= start and t.end <= end
                ],
                sentence_ids=_sentences_in(start, end, sentences),
            )
        )
        current_lines.append(len(lines) - 1)

    if current_lines:
        close_paragraph(lines[-1].end)

    return lines, paragraphs


def _sentences_in(start: int, end: int, sentences: list[Sentence]) -> list[str]:
    return [s.id for s in sentences if s.start < end and s.end > start]
