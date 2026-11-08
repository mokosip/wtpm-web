from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import spacy

from .analysis import analyze
from .config import AnalysisConfig
from .corrections import Correction, apply_corrections
from .ingest import build_document, model_info
from .normalise import normalise
from .schema import Analysis


DEFAULT_MODELS = {"de": "de_dep_news_trf", "en": "en_core_web_sm"}
SENTENCE_FINAL = (".", "!", "?")


@dataclass
class Pipeline:
    language: str = "de"
    model: str | None = None
    _nlp: object = field(default=None, init=False, repr=False)
    _info: object = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        model = self.model or DEFAULT_MODELS.get(self.language, f"{self.language}_core_news_sm")
        self._nlp = spacy.load(model)
        self._info = model_info(self._nlp)

    @property
    def model_name(self) -> str:
        return self._info.name

    def analyze(
        self,
        text: str,
        config: AnalysisConfig | None = None,
        corrections: Sequence[Correction] = (),
    ) -> Analysis:
        config = config or AnalysisConfig()
        normalisations, hints = [], []
        parser_input = text
        if config.normalise_parser_input and self._info.lang == "de":
            parser_input, normalisations, hints = normalise(text, self._nlp)
        doc = self._parse(parser_input, {hint.start for hint in hints})
        document = build_document(doc, text, self._info.lang, normalisations, hints)
        apply_corrections(document, corrections)
        return analyze(document, config, identity=self._info.identity(config.to_dict()))

    def _parse(self, text: str, sentence_starts: set[int]):
        if not sentence_starts:
            return self._nlp(text)
        doc = self._nlp.make_doc(text)
        previous = None
        for token in doc:
            if token.idx in sentence_starts:
                token.is_sent_start = True
                previous = token
            elif previous is not None:
                if "\n" in token.text:
                    previous = None
                    continue
                if not previous.text.endswith(SENTENCE_FINAL):
                    token.is_sent_start = False
                previous = token
        return self._nlp(doc)
