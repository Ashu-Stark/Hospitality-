"""Transcript -> structured JSON (Task T11): deterministic, glossary-based extraction.

No model and no network: phrases from glossary.yaml are matched as whole words (Devanagari and
Latin script), the earliest matching issue term sets issue + department (ties: the longest
phrase), urgency comes from the urgency terms (high wins over low, default from config), and the
room is the digits after a room word. The result is validated against the Extraction schema and
the glossary, so an issue or department outside the glossary can never be returned.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, model_validator

from ml.voice.config import Glossary, VoiceConfig

# A "word" boundary that also works for Devanagari (vowel signs count as letters; the
# dandas U+0964 / U+0965 are punctuation).
_EDGE = r"(?<![\w\u0900-\u0963\u0966-\u097F]){}(?![\w\u0900-\u0963\u0966-\u097F])"


class Extraction(BaseModel):
    room: str | None
    issue: str | None
    department: str | None
    urgency: str
    matched_terms: list[str]
    synthetic: bool = True

    @model_validator(mode="after")
    def _shape(self) -> Extraction:
        if self.room is not None and not self.room.isdigit():
            raise ValueError("room must be digits")
        if (self.issue is None) != (self.department is None):
            raise ValueError("issue and department are set together")
        return self


def validate_against(extraction: Extraction, glossary: Glossary) -> Extraction:
    if extraction.issue is not None and extraction.issue not in glossary.issues:
        raise ValueError(f"issue {extraction.issue!r} is not in the glossary")
    if extraction.department is not None and extraction.department not in glossary.departments:
        raise ValueError(f"department {extraction.department!r} is not in the glossary")
    if extraction.urgency not in glossary.urgency_levels:
        raise ValueError(f"urgency {extraction.urgency!r} is not a glossary level")
    return extraction


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


def _find(text: str, phrase: str) -> list[re.Match]:
    pattern = _EDGE.format(re.escape(normalise(phrase)).replace(r"\ ", r"\s+"))
    return list(re.finditer(pattern, text))


def find_room(text: str, glossary: Glossary, cfg: VoiceConfig) -> str | None:
    lo, hi = cfg.room_digits
    words = sorted((normalise(w) for w in glossary.room_words), key=len, reverse=True)
    alternatives = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words)
    m = re.search(rf"(?:{alternatives})\s*(?:no\.?|number|नंबर)?\s*(\d{{{lo},{hi}}})(?!\d)", text)
    return m.group(1) if m else None


def find_urgency(text: str, glossary: Glossary, cfg: VoiceConfig) -> str:
    for level in ("high", "low"):  # high wins when both appear
        if any(_find(text, p) for p in glossary.urgency_terms.get(level, [])):
            return level
    return cfg.default_urgency


def extract_fields(transcript: str, glossary: Glossary, cfg: VoiceConfig) -> Extraction:
    text = normalise(transcript)
    hits = []  # (start, -length, term)
    for term in glossary.terms:
        for phrase in term.phrases:
            hits += [(m.start(), -(m.end() - m.start()), term) for m in _find(text, phrase)]
    hits.sort(key=lambda h: (h[0], h[1]))
    first = hits[0][2] if hits else None
    matched = list(dict.fromkeys(h[2].id for h in hits))
    return validate_against(Extraction(
        room=find_room(text, glossary, cfg), issue=first.issue if first else None,
        department=first.department if first else None,
        urgency=find_urgency(text, glossary, cfg), matched_terms=matched), glossary)
