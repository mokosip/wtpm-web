from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import islice
from typing import Iterable, Iterator, Sequence

from .config import AnalysisConfig, EXCLUDED_DEPENDENCIES
from .schema import (
    Analysis,
    AnalysisIdentity,
    Denominator,
    Document,
    Occurrence,
    Pattern,
    Token,
)

ENGINE_VERSION = "0.1.0"


def analyze(
    document: Document,
    config: AnalysisConfig,
    identity: AnalysisIdentity | None = None,
) -> Analysis:
    runs = _eligible_runs(document, config)
    word_tokens = [t for t in document.tokens if t.eligible]
    windows = {
        length: _build_windows(runs, length) for length in config.sequence_lengths
    }

    patterns: list[Pattern] = []
    patterns.extend(_pos_counts(word_tokens))
    for length in config.sequence_lengths:
        patterns.extend(_pos_ngrams(windows[length], length))
    patterns.extend(_pos_transitions(word_tokens, runs))
    patterns.extend(_dependency_patterns(document))
    patterns.extend(_morphology(word_tokens))
    if config.surface_sequences:
        patterns.extend(
            _lexical(document, word_tokens, runs, config, kind="surface")
        )
    if config.lemma_sequences:
        patterns.extend(_lexical(document, word_tokens, runs, config, kind="lemma"))
    _annotate_occurrences(document, patterns)

    analysis = Analysis(
        document=document,
        analysis=identity or default_identity(config),
        patterns=_assign_ids(patterns),
        warnings=_warnings(document),
    )
    return analysis


_ANNOTATION_FIELDS = {
    "pos": frozenset({"pos"}),
    "pos_ngram": frozenset({"pos"}),
    "pos_transition": frozenset({"pos"}),
    "dependency": frozenset({"pos", "dep", "head_id"}),
    "morphology": frozenset({"morph"}),
    "lemma": frozenset({"lemma"}),
    "surface": frozenset(),
}


def _annotate_occurrences(document: Document, patterns: Sequence[Pattern]) -> None:
    by_id = {t.id: t for t in document.tokens}
    line_of = {
        token_id: line for line in document.lines for token_id in line.token_ids
    }
    for pattern in patterns:
        fields = _ANNOTATION_FIELDS[pattern.type]
        for occurrence in pattern.occurrences:
            occurrence.manual_token_ids = [
                i for i in occurrence.token_ids if by_id[i].corrected_fields & fields
            ]
            if len(occurrence.token_ids) < 2:
                continue
            lines = [line_of.get(i) for i in occurrence.token_ids]
            spanned = {line.index: line for line in lines if line}
            occurrence.line_ids = [spanned[index].id for index in sorted(spanned)]
            occurrence.crosses_line = len(occurrence.line_ids) > 1
            if pattern.type != "dependency":
                occurrence.line_breaks_after = [
                    position
                    for position in range(len(lines) - 1)
                    if lines[position] is not lines[position + 1]
                ]



def default_identity(config: AnalysisConfig) -> AnalysisIdentity:
    return AnalysisIdentity(
        library="wtpm",
        library_version=ENGINE_VERSION,
        model="fixture",
        model_version="",
        settings=config.to_dict(),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _eligible_runs(document: Document, config: AnalysisConfig) -> list[list[Token]]:
    by_id = {t.id: t for t in document.tokens}
    runs: list[list[Token]] = []
    for sentence in document.sentences:
        current: list[Token] = []
        for token_id in sentence.token_ids:
            token = by_id[token_id]
            if token.eligible:
                if (
                    config.break_on_lines
                    and current
                    and "\n" in document.text[current[-1].end : token.start]
                ):
                    runs.append(current)
                    current = []
                current.append(token)
                continue
            if token.is_space:
                continue
            if config.break_on_punctuation and current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)
    return runs


def _build_windows(
    runs: Sequence[Sequence[Token]], length: int
) -> dict[tuple[str, ...], list[list[Token]]]:
    windows: dict[tuple[str, ...], list[list[Token]]] = defaultdict(list)
    for run in runs:
        for start in range(max(0, len(run) - length + 1)):
            window = list(islice(run, start, start + length))
            windows[tuple(t.pos for t in window)].append(window)
    return windows


def _pos_counts(tokens: Sequence[Token]) -> Iterator[Pattern]:
    counts = Counter(t.pos for t in tokens)
    for pos, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        yield Pattern(
            pattern_id="",
            type="pos",
            values=[pos],
            length=None,
            count=count,
            denominator=Denominator(kind="eligible_word_tokens", count=len(tokens)),
            occurrences=[
                Occurrence(sentence_id=t.sentence_id, token_ids=[t.id])
                for t in tokens
                if t.pos == pos
            ],
        )


def _pos_ngrams(
    windows: dict[tuple[str, ...], list[list[Token]]], length: int
) -> Iterator[Pattern]:
    total = sum(len(v) for v in windows.values())
    for values, occurrences in sorted(
        windows.items(), key=lambda kv: (-len(kv[1]), kv[0])
    ):
        yield Pattern(
            pattern_id="",
            type="pos_ngram",
            values=list(values),
            length=length,
            count=len(occurrences),
            denominator=Denominator(
                kind="eligible_pos_windows", count=total, length=length
            ),
            occurrences=[
                Occurrence(sentence_id=w[0].sentence_id, token_ids=[t.id for t in w])
                for w in occurrences
            ],
        )


def _pos_transitions(
    tokens: Sequence[Token], runs: Sequence[Sequence[Token]]
) -> Iterator[Pattern]:
    transitions: Counter[tuple[str, str]] = Counter()
    outgoing: Counter[str] = Counter()
    occurrences: dict[tuple[str, str], list[Occurrence]] = defaultdict(list)

    for run in runs:
        for current, following in zip(run, run[1:]):
            transitions[(current.pos, following.pos)] += 1
            outgoing[current.pos] += 1
            occurrences[(current.pos, following.pos)].append(
                Occurrence(
                    sentence_id=current.sentence_id,
                    token_ids=[current.id, following.id],
                )
            )

    for (source, target), count in sorted(
        transitions.items(), key=lambda kv: (-kv[1], kv[0])
    ):
        yield Pattern(
            pattern_id="",
            type="pos_transition",
            values=[source, target],
            length=2,
            count=count,
            denominator=Denominator(
                kind="eligible_outgoing_transitions", count=outgoing[source]
            ),
            occurrences=occurrences[(source, target)],
        )


def _dependency_patterns(document: Document) -> Iterator[Pattern]:
    edges: list[tuple[Token, Token]] = []
    by_id = {t.id: t for t in document.tokens}
    for token in document.tokens:
        if token.head_id is None:
            continue
        if token.dep in EXCLUDED_DEPENDENCIES:
            continue
        head = by_id[token.head_id]
        if head.is_punct or token.is_punct:
            continue
        if not token.eligible or not head.eligible:
            continue
        edges.append((head, token))

    grouped: dict[tuple[str, str, str], list[tuple[Token, Token]]] = defaultdict(list)
    for head, dependent in edges:
        grouped[(head.pos, dependent.dep, dependent.pos)].append((head, dependent))

    for values, group in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        yield Pattern(
            pattern_id="",
            type="dependency",
            values=list(values),
            length=None,
            count=len(group),
            denominator=Denominator(kind="eligible_dependency_edges", count=len(edges)),
            occurrences=[
                Occurrence(
                    sentence_id=dependent.sentence_id,
                    token_ids=[head.id, dependent.id],
                    head_after_dependent=head.index > dependent.index,
                )
                for head, dependent in group
            ],
        )


def _morphology(tokens: Sequence[Token]) -> Iterator[Pattern]:
    coverage: Counter[str] = Counter()
    values: Counter[tuple[str, str]] = Counter()
    occurrences: dict[tuple[str, str], list[Occurrence]] = defaultdict(list)

    for token in tokens:
        for feature, value in token.morph.items():
            coverage[feature] += 1
            values[(feature, value)] += 1
            occurrences[(feature, value)].append(
                Occurrence(sentence_id=token.sentence_id, token_ids=[token.id])
            )

    for feature, count in sorted(coverage.items(), key=lambda kv: (-kv[1], kv[0])):
        yield Pattern(
            pattern_id="",
            type="morphology",
            values=[feature],
            length=None,
            count=count,
            denominator=Denominator(kind="eligible_word_tokens", count=len(tokens)),
            occurrences=[
                Occurrence(sentence_id=t.sentence_id, token_ids=[t.id])
                for t in tokens
                if feature in t.morph
            ],
        )

    for (feature, value), count in sorted(
        values.items(), key=lambda kv: (-kv[1], kv[0])
    ):
        yield Pattern(
            pattern_id="",
            type="morphology",
            values=[feature, value],
            length=None,
            count=count,
            denominator=Denominator(
                kind="tokens_with_feature", count=coverage[feature], feature=feature
            ),
            occurrences=occurrences[(feature, value)],
        )


def _surface_key(token: Token, config: AnalysisConfig, kind: str) -> str:
    if kind == "lemma":
        return token.lemma.casefold() if config.surface_comparison != "exact" else token.lemma
    if config.surface_comparison == "case_insensitive":
        return token.text.casefold()
    return token.text


def _lexical(
    document: Document,
    tokens: Sequence[Token],
    runs: Sequence[Sequence[Token]],
    config: AnalysisConfig,
    kind: str,
) -> Iterator[Pattern]:
    unigrams: dict[str, list[Token]] = defaultdict(list)
    for token in tokens:
        unigrams[_surface_key(token, config, kind)].append(token)

    for value, group in sorted(unigrams.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        yield Pattern(
            pattern_id="",
            type=kind,
            values=[value],
            length=1,
            count=len(group),
            denominator=Denominator(kind="eligible_word_tokens", count=len(tokens)),
            occurrences=[
                Occurrence(sentence_id=t.sentence_id, token_ids=[t.id]) for t in group
            ],
        )

    for length in config.sequence_lengths:
        windows: dict[tuple[str, ...], list[str]] = defaultdict(list)
        sentences: dict[tuple[str, ...], str] = {}
        total = 0
        for run in runs:
            for start in range(max(0, len(run) - length + 1)):
                window = run[start : start + length]
                key = tuple(_surface_key(t, config, kind) for t in window)
                windows[key].append([t.id for t in window])
                sentences[key] = window[0].sentence_id
                total += 1
        for key, occurrences in sorted(
            windows.items(), key=lambda kv: (-len(kv[1]), kv[0])
        ):
            yield Pattern(
                pattern_id="",
                type=kind,
                values=list(key),
                length=length,
                count=len(occurrences),
                denominator=Denominator(
                    kind="eligible_windows", count=total, length=length
                ),
                occurrences=[
                    Occurrence(sentence_id=sentences[key], token_ids=ids)
                    for ids in occurrences
                ],
            )


def _warnings(document: Document) -> list[str]:
    warnings: list[str] = []
    if not document.tokens:
        warnings.append("The input contains no tokens.")
        return warnings
    if not any(t.eligible for t in document.tokens):
        warnings.append("The input contains no eligible word tokens.")
    missing = [t.id for t in document.tokens if t.eligible and not t.pos]
    if missing:
        warnings.append(
            f"{len(missing)} eligible tokens have no part-of-speech annotation."
        )
    for sentence in document.sentences:
        if sentence.root_token_id is None and any(
            document.token(i).eligible for i in sentence.token_ids
        ):
            warnings.append(
                f"Sentence {sentence.id} has no word root: the parser rooted it at whitespace."
            )
    return warnings


def _assign_ids(patterns: Iterable[Pattern]) -> list[Pattern]:
    counters: Counter[str] = Counter()
    ordered = sorted(
        patterns,
        key=lambda p: (
            _TYPE_ORDER.index(p.type) if p.type in _TYPE_ORDER else len(_TYPE_ORDER),
            p.length if p.length is not None else 0,
            -p.count,
            p.values,
        ),
    )
    for pattern in ordered:
        counters[pattern.type] += 1
        pattern.pattern_id = f"{_TYPE_PREFIX[pattern.type]}-{counters[pattern.type]:03d}"
    return ordered


_TYPE_ORDER = [
    "pos",
    "pos_ngram",
    "pos_transition",
    "dependency",
    "morphology",
    "surface",
    "lemma",
]

_TYPE_PREFIX = {
    "pos": "pos",
    "pos_ngram": "posn",
    "pos_transition": "post",
    "dependency": "dep",
    "morphology": "morph",
    "surface": "surf",
    "lemma": "lem",
}
