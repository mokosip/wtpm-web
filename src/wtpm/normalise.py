from __future__ import annotations

import re

from .schema import Normalisation, SentenceHint

ELISION = re.compile(r"\w*[a-zäöüß]['’](?=[\s.,;:!?]|$)")
GENITIVE_ENDINGS = ("s", "ß", "x", "z")
SENTENCE_END = (".", "!", "?", ":", ";")
NOMINAL = {"NOUN", "PROPN"}


def normalise(text: str, nlp) -> tuple[str, list[Normalisation], list[SentenceHint]]:
    hints = [SentenceHint(start, "stanza_break") for start in _stanza_starts(text)]
    sentence_starts = {hint.start for hint in hints}
    chars = list(text)
    changes = []
    for match in ELISION.finditer(text):
        word = match.group()
        if word[0].isupper() and word[-2] in GENITIVE_ENDINGS:
            continue
        chars[match.end() - 1] = "e"
        changes.append(Normalisation(match.start(), match.end(), word, word[:-1] + "e", "elision"))

    line_starts = {i + 1 for i, char in enumerate(text) if char == "\n"}
    previous = ""
    for token in nlp("".join(chars)):
        if token.is_space:
            continue
        if (
            token.idx in line_starts
            and previous
            and token.idx not in sentence_starts
            and not previous.endswith(SENTENCE_END)
            and token.text[0].isupper()
            and token.pos_ not in NOMINAL
        ):
            chars[token.idx] = chars[token.idx].lower()
            end = token.idx + len(token.text)
            changes.append(
                Normalisation(token.idx, end, text[token.idx : end], "".join(chars[token.idx : end]), "verse_start_case")
            )
        previous = token.text

    return "".join(chars), sorted(changes, key=lambda change: change.start), hints


def _stanza_starts(text: str) -> list[int]:
    starts = []
    offset, previous, blank = 0, "", False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            blank = bool(previous)
        else:
            if blank and previous[-1].isalnum():
                starts.append(offset + len(line) - len(line.lstrip()))
            previous, blank = stripped, False
        offset += len(line)
    return starts
