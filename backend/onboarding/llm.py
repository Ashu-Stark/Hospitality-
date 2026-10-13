"""LLM extractor (Part C) with a small, swappable chat adapter (standard library only).

There was no LLM adapter in ml/voice (only speech-to-text adapters), so this adds one in the same
style as ml/voice/providers.py: urllib, no new dependency, the key only from the environment.
GroqChat calls Groq's OpenAI-compatible chat completions endpoint (config: onboarding.yaml llm)
at temperature 0 in JSON mode. Tests inject a fake adapter through the ChatAdapter protocol.

extract() = the rule-based extractor, plus the LLM when an adapter is available:
- the prompt has the JSON schema, the department glossary and the current question;
- the reply must be JSON that validates against LlmFields, otherwise it is rejected;
- every number the LLM returns is CROSS-CHECKED against the number normaliser's reading of the
  transcript: a number that was not said gets confidence `mismatch` (0.3) and the note "please
  confirm", so it is never silently accepted;
- no key, a failed call or a rejected reply -> the rule-based result, with fallback_reason set.
PRIVACY: free AI tiers give no privacy guarantee; the API only calls this with the owner's
consent and a config flag (see service.py), and tests / eval use SYNTHETIC text only.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.onboarding.config import LlmConfig, OnboardingConfig, load_config
from backend.onboarding.extract import (
    ExtractionResult,
    Guess,
    Lexicon,
    extract_rules,
    load_lexicon,
)
from backend.onboarding.flow import load_questions
from backend.onboarding.numbers import numbers_in
from backend.onboarding.schema import HotelType, Shift

NUMERIC_FIELDS = ("rooms", "standard_weekly_hours", "weekly_off_days", "min_rest_hours",
                  "max_consecutive_days", "overtime_rate_multiplier",
                  "incentive_monthly_budget_cap")
TOLERANCE = 1e-6
NOON = 12
MISMATCH_NOTE = "please confirm: this number was not heard in the answer"


class LlmUnavailable(RuntimeError):
    """The LLM adapter cannot run here (no key, disabled)."""


class ChatAdapter(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def complete_json(self, system: str, user: str) -> str: ...


@dataclass
class GroqChat:
    settings: LlmConfig
    name: str = "groq_chat"

    def available(self) -> tuple[bool, str]:
        if not self.settings.enabled:
            return False, "LLM extractor disabled in onboarding.yaml"
        ok = bool(os.environ.get(self.settings.api_key_env))
        return ok, "ok" if ok else f"set {self.settings.api_key_env}"

    def complete_json(self, system: str, user: str) -> str:
        s = self.settings
        body: dict = {"model": s.model, "temperature": s.temperature, "max_tokens": s.max_tokens,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]}
        if s.json_mode:
            body["response_format"] = {"type": "json_object"}
        if s.reasoning_effort:
            body["reasoning_effort"] = s.reasoning_effort
        key = os.environ.get(s.api_key_env)
        if not key:
            raise LlmUnavailable(f"set {s.api_key_env}")
        req = urllib.request.Request(
            s.url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "User-Agent": "hoi-onboarding/1"})
        with urllib.request.urlopen(req, timeout=s.timeout_seconds) as resp:  # noqa: S310
            out = json.loads(resp.read().decode("utf-8"))
        return str(out["choices"][0]["message"]["content"])


class LlmFields(BaseModel):
    """What the LLM may return: every field optional, strict types, glossary departments."""

    model_config = ConfigDict(extra="forbid")

    hotel_name: str | None = None
    hotel_type: HotelType | None = None
    rooms: int | None = Field(default=None, ge=0)
    location: str | None = None
    peak_months: list[int] | None = None
    departments: dict[str, int] | None = None
    shifts: list[Shift] | None = None
    standard_weekly_hours: int | None = Field(default=None, ge=0)
    weekly_off_days: int | None = Field(default=None, ge=0)
    min_rest_hours: float | None = Field(default=None, ge=0)
    max_consecutive_days: int | None = Field(default=None, ge=0)
    overtime_rate_multiplier: float | None = Field(default=None, ge=0)
    incentive_monthly_budget_cap: int | None = Field(default=None, ge=0)

    @field_validator("peak_months")
    @classmethod
    def _months(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and not all(1 <= m <= 12 for m in v):
            raise ValueError("peak_months must be 1-12")
        return v

    @field_validator("departments")
    @classmethod
    def _departments(cls, v: dict[str, int] | None) -> dict[str, int] | None:
        if v is None:
            return v
        unknown = set(v) - set(load_lexicon().departments)
        if unknown or any(n < 0 for n in v.values()):
            raise ValueError(f"unknown departments or negative headcounts: {sorted(unknown)}")
        return v


def build_prompt(transcript: str, current: str | None, lex: Lexicon) -> tuple[str, str]:
    schema = json.dumps(LlmFields.model_json_schema(), ensure_ascii=False)
    glossary = json.dumps(lex.departments, ensure_ascii=False)
    question = load_questions().questions[current].en if current else "(none)"
    system = (
        "You extract hotel setup facts from an owner's answer (English, Hindi or Hinglish). "
        "Reply with ONE JSON object that validates against this JSON schema, using only keys you "
        "are sure of; leave out anything not said. Never guess or invent numbers. Department "
        "keys must be these ids (synonyms in brackets): " + glossary + ". Shift times are "
        "24-hour HH:MM. JSON schema: " + schema)
    user = (f"Question asked (field {current or 'none'}): {question}\n"
            f"Owner's answer: {transcript}")
    return system, user


def _close(v: float, heard: set[float]) -> bool:
    return any(abs(v - h) < TOLERANCE for h in heard)


def _hour_heard(t: str, heard: set[float]) -> bool:
    h = int(t.split(":")[0])
    return _close(h, heard) or _close(h - NOON, heard) or (h == 0 and _close(NOON, heard))


def cross_check(fields: LlmFields, transcript: str, cfg: OnboardingConfig
                ) -> tuple[dict[str, Guess], list[str]]:
    """LLM fields as guesses; numbers not heard by the normaliser are flagged (conf 0.3)."""
    heard = numbers_in(transcript)
    c = cfg.confidence
    out: dict[str, Guess] = {}
    mismatches = []
    for name, value in fields.model_dump(exclude_none=True).items():
        if name in NUMERIC_FIELDS:
            ok = _close(float(value), heard)
        elif name == "departments":
            ok = all(_close(float(n), heard) for n in value.values())
        elif name == "shifts":
            ok = all(_hour_heard(s["start"], heard) and _hour_heard(s["end"], heard)
                     for s in value)
        else:
            out[name] = Guess(value=value, confidence=c.llm_unchecked)
            continue
        if ok:
            out[name] = Guess(value=value, confidence=c.llm_checked)
        else:
            mismatches.append(name)
            out[name] = Guess(value=value, confidence=c.mismatch, note=MISMATCH_NOTE)
    return out, mismatches


def extract(transcript: str, current: str | None, adapter: ChatAdapter | None,
            cfg: OnboardingConfig | None = None) -> ExtractionResult:
    cfg = cfg or load_config()
    lex = load_lexicon()
    rules = extract_rules(transcript, current, cfg, lex)
    if adapter is None:
        return rules.model_copy(update={"fallback_reason": "no LLM adapter (rules only)"})
    ok, why = adapter.available()
    if not ok:
        return rules.model_copy(update={"fallback_reason": f"LLM unavailable: {why}"})
    system, user = build_prompt(transcript, current, lex)
    try:
        raw = adapter.complete_json(system, user)
    except (urllib.error.URLError, TimeoutError, OSError, LlmUnavailable, KeyError,
            IndexError, ValueError) as e:
        return rules.model_copy(update={"fallback_reason": f"LLM call failed ({type(e).__name__})"})
    try:
        parsed = LlmFields.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        return rules.model_copy(update={"fallback_reason": "LLM reply rejected: not valid JSON "
                                                           "for the schema"})
    guesses, mismatches = cross_check(parsed, transcript, cfg)
    merged = {**rules.fields, **guesses}   # the LLM wins where it answered; rules fill gaps
    return ExtractionResult(method="llm", fields=merged, mismatches=mismatches)


def default_adapter(cfg: OnboardingConfig | None = None) -> GroqChat:
    return GroqChat((cfg or load_config()).llm)
