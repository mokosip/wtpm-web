from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .ingest import PUNCT_POS, SPACE_POS
from .schema import Document, Token

UNIVERSAL_POS = frozenset(
    {
        "ADJ", "ADP", "ADV", "AUX", "CCONJ", "DET", "INTJ", "NOUN", "NUM",
        "PART", "PRON", "PROPN", "PUNCT", "SCONJ", "SYM", "VERB", "X",
    }
)
STRING_FIELDS = ("pos", "tag", "lemma", "dep")
FIELDS = frozenset({"token", "note", "morph", "head", *STRING_FIELDS})


class CorrectionError(ValueError):
    pass


@dataclass(frozen=True)
class TokenRef:
    start: int
    text: str


@dataclass(frozen=True)
class Correction:
    token: TokenRef
    values: dict[str, Any]
    note: str | None = None


def load_corrections(path: str | Path) -> list[Correction]:
    with open(path, encoding="utf-8") as handle:
        return parse_corrections(json.load(handle))


def parse_corrections(payload: Any) -> list[Correction]:
    if isinstance(payload, dict):
        payload = payload.get("corrections")
    if not isinstance(payload, list):
        raise CorrectionError("expected {\"corrections\": [...]}")
    return [_parse_one(entry) for entry in payload]


def apply_corrections(document: Document, corrections: Sequence[Correction]) -> None:
    by_start = {t.start: t for t in document.tokens if not t.is_space}
    seen: set[str] = set()
    touched: set[str] = set()

    for correction in corrections:
        token = _resolve(by_start, correction.token)
        if token.id in seen:
            raise CorrectionError(f"token '{token.text}' at {token.start} corrected twice")
        seen.add(token.id)

        original: dict[str, Any] = {}
        for key, value in correction.values.items():
            if key == "head":
                head_id = _head_id(by_start, token, value)
                if head_id != token.head_id:
                    original["head_id"] = token.head_id
                    token.head_id = head_id
                continue
            if getattr(token, key) != value:
                original[key] = getattr(token, key)
                setattr(token, key, dict(value) if key == "morph" else value)

        if not original:
            continue
        token.model_annotation = original
        token.correction_note = correction.note
        if "pos" in original:
            token.eligible = _eligible(token)
        touched.add(token.sentence_id)

    for sentence in document.sentences:
        if sentence.id in touched:
            sentence.root_token_id = _root(document, sentence.token_ids)


def _parse_one(entry: Any) -> Correction:
    if not isinstance(entry, dict):
        raise CorrectionError(f"correction must be an object: {entry!r}")
    unknown = set(entry) - FIELDS
    if unknown:
        raise CorrectionError(f"unknown field(s) {sorted(unknown)} in {entry!r}")
    if "token" not in entry:
        raise CorrectionError(f"correction without 'token': {entry!r}")

    values: dict[str, Any] = {}
    for key in STRING_FIELDS:
        if key in entry:
            if not isinstance(entry[key], str) or not entry[key]:
                raise CorrectionError(f"'{key}' must be a non-empty string: {entry!r}")
            values[key] = entry[key]
    if "pos" in values and values["pos"] not in UNIVERSAL_POS:
        raise CorrectionError(f"'{values['pos']}' is not a universal POS tag")
    if "morph" in entry:
        morph = entry["morph"]
        if not isinstance(morph, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in morph.items()
        ):
            raise CorrectionError(f"'morph' must map feature names to strings: {entry!r}")
        values["morph"] = dict(morph)
    if "head" in entry:
        values["head"] = None if entry["head"] is None else _parse_ref(entry["head"])
    if not values:
        raise CorrectionError(f"correction changes nothing: {entry!r}")

    note = entry.get("note")
    if note is not None and not isinstance(note, str):
        raise CorrectionError(f"'note' must be a string: {entry!r}")
    return Correction(token=_parse_ref(entry["token"]), values=values, note=note)


def _parse_ref(raw: Any) -> TokenRef:
    if (
        not isinstance(raw, dict)
        or set(raw) != {"start", "text"}
        or not isinstance(raw["start"], int)
        or not isinstance(raw["text"], str)
    ):
        raise CorrectionError(f"token reference must be {{start, text}}: {raw!r}")
    return TokenRef(start=raw["start"], text=raw["text"])


def _resolve(by_start: dict[int, Token], ref: TokenRef) -> Token:
    token = by_start.get(ref.start)
    if token is None or token.text != ref.text:
        raise CorrectionError(f"no token '{ref.text}' at offset {ref.start}")
    return token


def _head_id(by_start: dict[int, Token], token: Token, ref: TokenRef | None) -> str | None:
    if ref is None:
        return None
    head = _resolve(by_start, ref)
    if head.id == token.id:
        raise CorrectionError(f"token '{token.text}' cannot be its own head")
    if head.sentence_id != token.sentence_id:
        raise CorrectionError(
            f"head '{head.text}' of '{token.text}' must be in the same sentence"
        )
    return head.id


def _root(document: Document, token_ids: list[str]) -> str:
    tokens = [document.token(i) for i in token_ids]
    roots = [t.id for t in tokens if t.head_id is None and not t.is_space]
    if len(roots) != 1:
        raise CorrectionError(
            f"sentence must have exactly one root after corrections, found {len(roots)}"
        )
    for token in tokens:
        current, steps = token, 0
        while current.head_id is not None:
            current = document.token(current.head_id)
            steps += 1
            if steps > len(tokens):
                raise CorrectionError(f"dependency cycle through '{token.text}'")
    return roots[0]


def _eligible(token: Token) -> bool:
    if token.is_space or token.is_punct:
        return False
    return bool(token.pos) and token.pos not in PUNCT_POS | SPACE_POS
