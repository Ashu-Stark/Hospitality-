"""Deterministic question flow (Part B): no AI.

The fields in onboarding.yaml required_order are asked in that fixed order. The next question is
always about the first field that has not been answered (or skipped) yet, so a field already
filled by an answer, even one given early ("12 rooms in Mussoorie" answers rooms AND location),
is never asked again. A field with no usable answer is asked at most max_asks_per_field times,
and never more than max_questions questions are asked in total: the flow always ends. Every other
field comes from the template and is shown at confirm time, not asked. "skip" keeps the template
value.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.onboarding.config import ONBOARDING_DIR, OnboardingConfig

QUESTIONS_PATH = ONBOARDING_DIR / "questions.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionText(_Strict):
    en: str
    hi: str
    example_en: str
    example_hi: str


class Questions(_Strict):
    review: dict[str, str | bool]
    languages: list[str]
    questions: dict[str, QuestionText]
    skip_words: list[str]
    messages: dict[str, dict[str, str]]

    @model_validator(mode="after")
    def _bilingual(self) -> Questions:
        for key, texts in self.messages.items():
            if set(texts) != set(self.languages):
                raise ValueError(f"message {key!r} must exist in {self.languages}")
        return self

    def message(self, key: str, language: str) -> str:
        return self.messages[key][language]


class Question(_Strict):
    field: str
    language: str
    text: str
    example: str
    number: int = Field(ge=1, description="1-based question number")
    max_questions: int
    needs_hm_review: bool = True   # the wording is a DRAFT until the HM student reviews it


class FlowState(_Strict):
    asked: list[str] = Field(default_factory=list)      # every question asked, in order
    answered: list[str] = Field(default_factory=list)   # fields filled by an answer
    skipped: list[str] = Field(default_factory=list)    # fields the owner skipped
    current: str | None = None                          # the open question's field


@lru_cache(maxsize=2)
def load_questions(path: Path = QUESTIONS_PATH) -> Questions:
    return Questions.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def is_skip(text: str, questions: Questions) -> bool:
    cleaned = text.strip().lower().strip(".!?।")
    return cleaned in {w.lower() for w in questions.skip_words}


def next_field(state: FlowState, cfg: OnboardingConfig) -> str | None:
    """The field to ask next, or None when the flow is done (ready for the summary)."""
    if len(state.asked) >= cfg.max_questions:
        return None
    for f in cfg.required_order:
        if f in state.answered or f in state.skipped:
            continue
        if state.asked.count(f) >= cfg.max_asks_per_field:
            continue
        return f
    return None


def advance(state: FlowState, cfg: OnboardingConfig) -> FlowState:
    """Open the next question (records it as asked) or close the flow (current=None)."""
    f = next_field(state, cfg)
    return state.model_copy(update={"asked": [*state.asked, f] if f else state.asked,
                                     "current": f})


def record_answer(state: FlowState, filled: list[str], skipped: bool) -> FlowState:
    """After an answer: the fields it filled (any field, not only the one asked) and a skip."""
    answered = list(dict.fromkeys([*state.answered, *filled]))
    skip = [*state.skipped, state.current] if skipped and state.current else state.skipped
    return state.model_copy(update={"answered": answered, "skipped": list(dict.fromkeys(skip))})


def render(field: str, language: str, state: FlowState, cfg: OnboardingConfig,
           questions: Questions | None = None) -> Question:
    qs = questions or load_questions()
    q = qs.questions[field]
    lang = language if language in qs.languages else qs.languages[0]
    return Question(field=field, language=lang, text=getattr(q, lang),
                    example=getattr(q, f"example_{lang}"), number=len(state.asked),
                    max_questions=cfg.max_questions)
