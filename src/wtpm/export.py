from __future__ import annotations

import json
from typing import Any

from .schema import Analysis


def to_json(analysis: Analysis, indent: int | None = 2) -> str:
    return json.dumps(
        analysis.to_dict(), ensure_ascii=False, indent=indent, sort_keys=False
    )


def write_json(analysis: Analysis, path: str, indent: int | None = 2) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(to_json(analysis, indent=indent))
        handle.write("\n")


def summary(analysis: Analysis) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for pattern in analysis.patterns:
        counts[pattern.type] = counts.get(pattern.type, 0) + 1
    return {
        "language": analysis.document.language,
        "model": analysis.analysis.model,
        "tokens": len(analysis.document.tokens),
        "eligible_tokens": sum(1 for t in analysis.document.tokens if t.eligible),
        "sentences": len(analysis.document.sentences),
        "lines": len(analysis.document.lines),
        "paragraphs": len(analysis.document.paragraphs),
        "pattern_groups": counts,
        "annotation_review": analysis.annotation_review(),
        "warnings": analysis.warnings,
    }
