from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

SurfaceComparison = Literal["case_insensitive", "exact", "lemma"]
BoundaryPolicy = Literal[
    "sentence",
    "sentence_and_punctuation",
    "sentence_and_line",
    "sentence_punctuation_and_line",
]


@dataclass(frozen=True)
class AnalysisConfig:
    sequence_lengths: tuple[int, ...] = (2, 3, 4)
    surface_comparison: SurfaceComparison = "case_insensitive"
    break_on_punctuation: bool = True
    break_on_lines: bool = False
    lemma_sequences: bool = True
    surface_sequences: bool = True
    normalise_parser_input: bool = True

    @property
    def boundary_policy(self) -> BoundaryPolicy:
        if self.break_on_punctuation and self.break_on_lines:
            return "sentence_punctuation_and_line"
        if self.break_on_punctuation:
            return "sentence_and_punctuation"
        if self.break_on_lines:
            return "sentence_and_line"
        return "sentence"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sequence_lengths"] = list(self.sequence_lengths)
        payload["boundary_policy"] = self.boundary_policy
        return payload


EXCLUDED_DEPENDENCIES = frozenset({"ROOT", "root", "punct", ""})
