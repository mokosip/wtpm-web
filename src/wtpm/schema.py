from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "1.2"


@dataclass
class Token:
    id: str
    index: int
    text: str
    start: int
    end: int
    pos: str
    tag: str
    lemma: str
    morph: dict[str, str]
    is_punct: bool
    is_space: bool
    eligible: bool
    dep: str
    head_id: str | None
    sentence_id: str
    model_annotation: dict[str, Any] | None = None
    correction_note: str | None = None

    @property
    def corrected_fields(self) -> frozenset[str]:
        return frozenset(self.model_annotation or ())

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "index": self.index,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "pos": self.pos,
            "tag": self.tag,
            "lemma": self.lemma,
            "morph": self.morph,
            "is_punct": self.is_punct,
            "is_space": self.is_space,
            "eligible": self.eligible,
            "dep": self.dep,
            "head_id": self.head_id,
            "sentence_id": self.sentence_id,
            "annotation_source": "manual" if self.model_annotation else "model",
        }
        if self.model_annotation:
            payload["model_annotation"] = self.model_annotation
            payload["correction_note"] = self.correction_note
        return payload


@dataclass
class Sentence:
    id: str
    index: int
    start: int
    end: int
    token_ids: list[str]
    root_token_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "token_ids": self.token_ids,
            "root_token_id": self.root_token_id,
        }


@dataclass
class Line:
    index: int
    start: int
    end: int
    token_ids: list[str]
    sentence_ids: list[str]

    @property
    def id(self) -> str:
        return f"l{self.index + 1}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "token_ids": self.token_ids,
            "sentence_ids": self.sentence_ids,
        }


@dataclass
class Paragraph:
    index: int
    start: int
    end: int
    line_indices: list[int]
    sentence_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "line_indices": self.line_indices,
            "sentence_ids": self.sentence_ids,
        }


@dataclass(frozen=True)
class Normalisation:
    start: int
    end: int
    source: str
    parser_input: str
    rule: Literal["elision", "verse_start_case"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "source": self.source,
            "parser_input": self.parser_input,
            "rule": self.rule,
        }


@dataclass(frozen=True)
class SentenceHint:
    start: int
    rule: Literal["stanza_break"]

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "rule": self.rule}


@dataclass
class Document:
    text: str
    language: str
    tokens: list[Token]
    sentences: list[Sentence]
    lines: list[Line]
    paragraphs: list[Paragraph]
    normalisations: list[Normalisation] = field(default_factory=list)
    sentence_hints: list[SentenceHint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "normalisations": [n.to_dict() for n in self.normalisations],
            "sentence_hints": [h.to_dict() for h in self.sentence_hints],
            "tokens": [t.to_dict() for t in self.tokens],
            "sentences": [s.to_dict() for s in self.sentences],
            "lines": [line.to_dict() for line in self.lines],
            "paragraphs": [p.to_dict() for p in self.paragraphs],
        }

    def token(self, token_id: str) -> Token:
        return self._index()[token_id]

    def _index(self) -> dict[str, Token]:
        cached = getattr(self, "_token_index", None)
        if cached is None:
            cached = {t.id: t for t in self.tokens}
            self._token_index = cached
        return cached


@dataclass(frozen=True)
class Denominator:
    kind: str
    count: int
    length: int | None = None
    feature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind, "count": self.count}
        if self.length is not None:
            payload["length"] = self.length
        if self.feature is not None:
            payload["feature"] = self.feature
        return payload


@dataclass
class Occurrence:
    sentence_id: str
    token_ids: list[str]
    head_after_dependent: bool | None = None
    manual_token_ids: list[str] = field(default_factory=list)
    line_ids: list[str] | None = None
    line_breaks_after: list[int] | None = None
    crosses_line: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sentence_id": self.sentence_id,
            "token_ids": self.token_ids,
        }
        if self.head_after_dependent is not None:
            payload["head_after_dependent"] = self.head_after_dependent
        if self.line_ids is not None:
            payload["line_ids"] = self.line_ids
            payload["crosses_line"] = self.crosses_line
        if self.line_breaks_after is not None:
            payload["line_breaks_after"] = self.line_breaks_after
        if self.manual_token_ids:
            payload["manual_token_ids"] = self.manual_token_ids
        return payload


@dataclass
class Pattern:
    pattern_id: str
    type: str
    values: list[str]
    length: int | None
    count: int
    denominator: Denominator
    occurrences: list[Occurrence]

    @property
    def relative_frequency(self) -> float:
        if not self.denominator.count:
            return 0.0
        return self.count / self.denominator.count

    @property
    def manual_occurrences(self) -> int:
        return sum(1 for o in self.occurrences if o.manual_token_ids)

    @property
    def line_aware(self) -> bool:
        return any(o.crosses_line is not None for o in self.occurrences)

    @property
    def line_crossing_count(self) -> int:
        return sum(1 for o in self.occurrences if o.crosses_line is True)

    @property
    def line_internal_count(self) -> int:
        return sum(1 for o in self.occurrences if o.crosses_line is False)

    def line_break_profiles(self) -> list[dict[str, Any]]:
        counts: dict[tuple[int, ...], int] = {}
        for occurrence in self.occurrences:
            if occurrence.line_breaks_after is None:
                continue
            key = tuple(occurrence.line_breaks_after)
            counts[key] = counts.get(key, 0) + 1
        return [
            {"breaks_after": list(key), "count": count}
            for key, count in sorted(counts.items(), key=lambda kv: (len(kv[0]), kv[0]))
        ]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pattern_id": self.pattern_id,
            "type": self.type,
            "values": self.values,
            "count": self.count,
            "denominator": self.denominator.to_dict(),
            "relative_frequency": self.relative_frequency,
            "manual_occurrences": self.manual_occurrences,
            "occurrences": [occ.to_dict() for occ in self.occurrences],
        }
        if self.length is not None:
            payload["length"] = self.length
        if self.line_aware:
            payload["line_internal_count"] = self.line_internal_count
            payload["line_crossing_count"] = self.line_crossing_count
            profiles = self.line_break_profiles()
            if profiles:
                payload["line_break_profiles"] = profiles
        return payload


@dataclass
class AnalysisIdentity:
    library: str
    library_version: str
    model: str
    model_version: str
    settings: dict[str, Any]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "library_version": self.library_version,
            "model": self.model,
            "model_version": self.model_version,
            "settings": self.settings,
            "timestamp": self.timestamp,
        }


@dataclass
class Analysis:
    document: Document
    analysis: AnalysisIdentity
    patterns: list[Pattern]
    warnings: list[str] = field(default_factory=list)

    def by_type(self, pattern_type: str, length: int | None = None) -> list[Pattern]:
        return [
            p
            for p in self.patterns
            if p.type == pattern_type and (length is None or p.length == length)
        ]

    def annotation_review(self) -> dict[str, Any]:
        words = [t for t in self.document.tokens if t.eligible]
        manual = sum(1 for t in words if t.model_annotation)
        return {
            "linguistic_verification": "partial_manual" if manual else "not_performed",
            "model_tokens": len(words) - manual,
            "manually_corrected_tokens": manual,
            "warnings_scope": "technical_input_checks",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "document": self.document.to_dict(),
            "analysis": self.analysis.to_dict(),
            "sections": {
                "lines": [line.to_dict() for line in self.document.lines],
                "paragraphs": [p.to_dict() for p in self.document.paragraphs],
            },
            "sentences": [s.to_dict() for s in self.document.sentences],
            "tokens": [t.to_dict() for t in self.document.tokens],
            "patterns": [p.to_dict() for p in self.patterns],
            "annotation_review": self.annotation_review(),
            "warnings": self.warnings,
        }


PatternType = Literal[
    "pos",
    "pos_ngram",
    "pos_transition",
    "dependency",
    "morphology",
    "surface",
    "lemma",
]
