"""Rule-based extractor (Part C): transcript + current question -> profile fields. No network.

Numbers are first rewritten as digits by the number normaliser (numbers.py), then:
- rooms: a number next to a room word ("12 kamre", "45 rooms"); a bare number answers the rooms
  question.
- departments: department words from lexicon.yaml (keys = ml/voice/glossary.yaml department ids)
  with the nearest number ("housekeeping mein 4", "2 cooks"); within headcount_window_words.
- peak_months: English / Hindi month names and ranges ("may se june"), only when the question is
  about peak months or a season word is present ("may" is also an English verb).
- hotel_type: homestay / guest house / resort words. location: a known place, or the cleaned
  answer to the location question. hotel_name: after "named" / "naam".
- shifts: time ranges ("subah 7 se 3", "evening 3 to 11", "10pm-6am"), am / pm from the shift
  name, the end time chosen so the shift length is within the allowed range.
- overtime multiplier ("double", "dedh guna", "2x"), rest hours ("10 ghante aaram"), weekly
  hours ("48 hours a week"), weekly off ("ek din chhutti"), consecutive days ("lagatar 6 din"),
  incentive budget ("budget 5 hazaar").
Confidence: rules_pattern when the value sits next to its keyword, rules_context when a bare
value is read from the question asked, rules_free_text for a free-text location.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.onboarding.config import ONBOARDING_DIR, OnboardingConfig, load_config
from backend.onboarding.numbers import nfc, normalise
from backend.onboarding.schema import HOURS_PER_DAY
from ml.voice.config import load_glossary

LEXICON_PATH = ONBOARDING_DIR / "lexicon.yaml"
LETTERS = r"\wऀ-ॣ०-ॿ"
EDGE = r"(?<![" + LETTERS + r"]){}(?![" + LETTERS + r"])"
NUMBER = r"\d+(?:\.\d+)?"
WORD = re.compile(r"[" + LETTERS + r"&']+")
NOON = 12


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Lexicon(_Strict):
    review: dict[str, str | bool]
    departments: dict[str, list[str]]
    months: dict[int, list[str]]
    range_words: list[str]
    hotel_types: dict[str, list[str]]
    places: list[str]
    places_hindi: dict[str, list[str]]
    location_filler: list[str]
    shift_names: dict[str, list[str]]
    time_connectors: list[str]
    pm_words: list[str]
    am_words: list[str]
    clock_words: list[str]
    units: dict[str, list[str]]
    name_markers: list[str]
    season_words: list[str]
    shift_words: list[str]

    @model_validator(mode="after")
    def _glossary_departments(self) -> Lexicon:
        unknown = set(self.departments) - set(load_glossary().departments)
        if unknown:
            raise ValueError(f"lexicon departments not in ml/voice/glossary.yaml: {unknown}")
        if set(self.months) != set(range(1, 13)):
            raise ValueError("lexicon months must be 1-12")
        return self


class Guess(_Strict):
    value: Any
    confidence: float = Field(ge=0, le=1)
    note: str | None = None


class ExtractionResult(_Strict):
    method: Literal["rules", "llm"]
    fields: dict[str, Guess] = Field(default_factory=dict)
    fallback_reason: str | None = None    # why the LLM was not used (rules only)
    mismatches: list[str] = Field(default_factory=list)   # LLM numbers the normaliser did not hear


@lru_cache(maxsize=2)
def load_lexicon(path: Path = LEXICON_PATH) -> Lexicon:
    return Lexicon.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def alternation(phrases: list[str]) -> str:
    words = sorted({nfc(p.lower()) for p in phrases}, key=len, reverse=True)
    return "(?:" + "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words) + ")"


def find_all(text: str, phrases: list[str]) -> list[re.Match]:
    return list(re.finditer(EDGE.format(alternation(phrases)), text))


def has(text: str, phrases: list[str]) -> bool:
    return bool(find_all(text, phrases))


class _Ctx:
    """Per-call state: the normalised text and the number spans already used by a field."""

    def __init__(self, transcript: str, current: str | None, cfg: OnboardingConfig,
                 lex: Lexicon) -> None:
        self.original = transcript
        self.text = normalise(transcript).text
        self.current, self.cfg, self.lex = current, cfg, lex
        self.claimed: list[tuple[int, int]] = []
        self.out: dict[str, Guess] = {}

    def free(self, m: re.Match, group: int = 1) -> bool:
        a, b = m.span(group)
        return not any(a < y and x < b for x, y in self.claimed)

    def claim(self, m: re.Match, group: int = 1) -> None:
        self.claimed.append(m.span(group))

    def put(self, field: str, value: Any, kind: str) -> None:
        if field not in self.out:
            self.out[field] = Guess(value=value, confidence=getattr(self.cfg.confidence, kind))

    def numbers(self) -> list[re.Match]:
        return [m for m in re.finditer(rf"(?<![\d:.])({NUMBER})(?![\d:])", self.text)
                if self.free(m)]

    def unit(self, name: str) -> str:
        return alternation(self.lex.units[name])

    def search(self, pattern: str) -> re.Match | None:
        for m in re.finditer(pattern, self.text):
            if self.free(m):
                return m
        return None


def _num(s: str) -> float | int:
    v = float(s)
    return int(v) if v.is_integer() else v


def _hotel_type(c: _Ctx) -> None:
    for t, words in c.lex.hotel_types.items():
        if has(c.text, words):
            c.put("hotel_type", t, "rules_pattern")
            return


def _rooms(c: _Ctx) -> None:
    rooms = c.unit("rooms")
    m = c.search(rf"(?<![\d.])(\d+)\s*{rooms}(?![{LETTERS}])")
    if m:
        c.claim(m)
        c.put("rooms", int(m.group(1)), "rules_pattern")


def _labelled_numbers(c: _Ctx) -> None:
    """Numbers whose meaning is given by the words around them."""
    hours, days, week, off = c.unit("hours"), c.unit("days"), c.unit("week"), c.unit("off")
    consecutive, times = c.unit("consecutive"), c.unit("times")
    sep = r"\s*(?:[a-zऀ-ॿ]+\s+){0,2}?"
    m = c.search(rf"({NUMBER})\s*{hours}\s*(?:[a-zऀ-ॿ]+\s+){{0,2}}?{week}")
    if m:
        c.claim(m)
        c.put("standard_weekly_hours", int(float(m.group(1))), "rules_pattern")
    m = c.search(rf"(\d+)\s*{days}{sep}{consecutive}") or c.search(
        rf"{consecutive}\s*(\d+)\s*{days}")
    if m:
        c.claim(m)
        c.put("max_consecutive_days", int(m.group(1)), "rules_pattern")
    m = c.search(rf"(\d+)\s*(?:{days})?{sep}{off}") or c.search(rf"{off}\s*(\d+)\s*{days}")
    if m:
        c.claim(m)
        c.put("weekly_off_days", int(m.group(1)), "rules_pattern")
    m = c.search(rf"({NUMBER})\s*{times}(?![{LETTERS}])")
    if m:
        c.claim(m)
        c.put("overtime_rate_multiplier", _num(m.group(1)), "rules_pattern")
    if has(c.text, c.lex.units["rest"]) or c.current == "min_rest_hours":
        m = c.search(rf"({NUMBER})\s*{hours}(?![{LETTERS}])")
        if m:
            c.claim(m)
            c.put("min_rest_hours", _num(m.group(1)), "rules_pattern")
    if has(c.text, c.lex.units["budget"]):
        nums = c.numbers()
        if nums:
            c.claim(nums[-1])
            c.put("incentive_monthly_budget_cap", int(float(nums[-1].group(1))), "rules_pattern")


def _departments(c: _Ctx) -> None:
    mentions = []
    for dept, words in c.lex.departments.items():
        mentions += [(m.start(), m.end(), dept) for m in find_all(c.text, words)]
    mentions.sort()
    kept = []
    for s, e, d in mentions:  # longest-first alternation already; drop overlaps
        if not kept or s >= kept[-1][1]:
            kept.append((s, e, d))
    if not kept:
        return
    window = c.cfg.extraction.headcount_window_words
    nums = [(m.start(1), m.end(1), int(float(m.group(1))), m) for m in c.numbers()
            if float(m.group(1)).is_integer()]

    def words_between(a: int, b: int) -> int:
        return len(WORD.findall(c.text[a:b]))

    first_start = kept[0][0]
    number_first = any(e <= first_start and words_between(e, first_start) <= window
                       for _, e, _, _ in nums)
    used: set[int] = set()
    counts: dict[str, int] = {}
    for i, (s, e, dept) in enumerate(kept):
        lo = kept[i - 1][1] if i else 0
        hi = kept[i + 1][0] if i + 1 < len(kept) else len(c.text)
        if number_first:
            cands = [n for n in nums if lo <= n[0] and n[1] <= s
                     and words_between(n[1], s) <= window and n[0] not in used]
            pick = cands[-1] if cands else None
        else:
            cands = [n for n in nums if e <= n[0] and n[1] <= hi
                     and words_between(e, n[0]) <= window and n[0] not in used]
            pick = cands[0] if cands else None
        if pick is None:
            continue
        used.add(pick[0])
        c.claim(pick[3])
        counts[dept] = counts.get(dept, 0) + pick[2]
    if counts:
        c.put("departments", counts, "rules_pattern")


def _months(c: _Ctx) -> None:
    if c.current != "peak_months" and not has(c.text, c.lex.season_words):
        return
    hits = []
    for month, words in c.lex.months.items():
        hits += [(m.start(), m.end(), month) for m in find_all(c.text, words)]
    hits.sort()
    if not hits:
        return
    rng = alternation(c.lex.range_words)
    months: list[int] = []
    i = 0
    while i < len(hits):
        s, e, a = hits[i]
        if i + 1 < len(hits) and re.fullmatch(rf"\s*{rng}\s*", c.text[e:hits[i + 1][0]]):
            b = hits[i + 1][2]
            span = (b - a) % 12
            months += [(a - 1 + k) % 12 + 1 for k in range(span + 1)]
            i += 2
            continue
        months.append(a)
        i += 1
    c.put("peak_months", sorted(set(months)), "rules_pattern")


def _band(hour: int, band: list[int]) -> bool:
    lo, hi = band
    return lo <= hour <= hi if lo <= hi else hour >= lo or hour <= hi


def _shifts(c: _Ctx) -> None:
    lex, ext = c.lex, c.cfg.extraction
    names = {nfc(w.lower()): n for n, ws in lex.shift_names.items() for w in ws}
    name_re = alternation(list(names))
    conn = alternation(lex.time_connectors)
    ampm = alternation(lex.pm_words + lex.am_words)
    clock = alternation(lex.clock_words)
    t = rf"(\d{{1,2}})(?::(\d{{2}}))?\s*({ampm})?\s*(?:{clock})?"
    pattern = rf"(?:({name_re})\s*(?:shift|शिफ्ट)?\s*(?:[a-zऀ-ॿ]+\s+)?)?{t}\s*{conn}\s*{t}"
    timed = (c.current == "shifts" or has(c.text, lex.shift_words)
             or has(c.text, lex.clock_words) or has(c.text, list(names)))
    if not timed:
        return
    pm = {nfc(w.lower()) for w in lex.pm_words}
    out = []
    for m in re.finditer(pattern, c.text):
        name = names.get(re.sub(r"\s+", " ", m.group(1))) if m.group(1) else None
        h1, m1, p1, h2, m2, p2 = (m.group(k) for k in range(2, 8))
        explicit = name is not None or p1 or p2 or c.current == "shifts"
        if not explicit and not has(m.group(0), lex.clock_words):
            continue
        start = int(h1) % HOURS_PER_DAY
        if p1:
            start = start % NOON + (NOON if nfc(p1) in pm else 0)
        elif name in ext.pm_shift_names:
            cands = [(start + NOON) % HOURS_PER_DAY, start]
            start = next((h for h in cands if _band(h, ext.shift_name_by_start_hour[name])),
                         cands[0])
        elif name is None and start < ext.earliest_unnamed_am_hour:
            start += NOON
        end_h = int(h2) % HOURS_PER_DAY
        if p2:
            ends = [end_h % NOON + (NOON if nfc(p2) in pm else 0)]
        else:
            ends = [end_h, (end_h + NOON) % HOURS_PER_DAY]
        lo, hi = c.cfg.ranges.shift_hours.min, c.cfg.ranges.shift_hours.max
        mins1, mins2 = int(m1 or 0), int(m2 or 0)

        def length(end: int, a: int = start, b: int = mins1, d: int = mins2) -> float:
            return ((end * 60 + d) - (a * 60 + b)) % (HOURS_PER_DAY * 60) / 60

        end = next((x for x in ends if lo <= length(x) <= hi), ends[0])
        if name is None:
            name = next((n for n, band in ext.shift_name_by_start_hour.items()
                         if _band(start, band)), "shift")
        out.append({"name": name, "start": f"{start:02d}:{mins1:02d}",
                    "end": f"{end:02d}:{mins2:02d}"})
        for g in (2, 5):
            c.claimed.append(m.span(g))
    if out:
        c.put("shifts", out, "rules_pattern")


def _location(c: _Ctx) -> None:
    for place in c.lex.places:
        if has(c.text, [place] + c.lex.places_hindi.get(place, [])):
            c.put("location", place, "rules_pattern")
            return
    if c.current != "location":
        return
    filler = {nfc(w.lower()) for w in c.lex.location_filler}
    words = [w for w in re.findall(rf"[{LETTERS}]+", nfc(c.original)) if w.lower() not in filler]
    if words and not any(ch.isdigit() for ch in "".join(words)):
        c.put("location", " ".join(w if not w.islower() else w.title() for w in words),
              "rules_free_text")


def _hotel_name(c: _Ctx) -> None:
    marker = alternation(c.lex.name_markers)
    m = re.search(rf"(?i){marker}\s+(?:hai\s+|है\s+)?([{LETTERS}' ]+?)(?:\s+(?:hai|है)|[,.।]|$)",
                  nfc(c.original))
    if m and m.group(1).strip():
        c.put("hotel_name", m.group(1).strip(), "rules_pattern")


def _bare_number(c: _Ctx) -> None:
    """A bare number answers the numeric question that was asked ("barah" -> rooms)."""
    numeric = {"rooms": int, "min_rest_hours": _num, "overtime_rate_multiplier": _num,
               "standard_weekly_hours": int, "weekly_off_days": int, "max_consecutive_days": int,
               "incentive_monthly_budget_cap": int}
    if c.current not in numeric or c.current in c.out:
        return
    nums = c.numbers()
    if len(nums) == 1:
        c.put(c.current, numeric[c.current](float(nums[0].group(1))), "rules_context")


def extract_rules(transcript: str, current: str | None = None,
                  cfg: OnboardingConfig | None = None,
                  lex: Lexicon | None = None) -> ExtractionResult:
    c = _Ctx(transcript, current, cfg or load_config(), lex or load_lexicon())
    for step in (_hotel_type, _rooms, _shifts, _labelled_numbers, _departments, _months,
                 _location, _hotel_name, _bare_number):
        step(c)
    return ExtractionResult(method="rules", fields=c.out)
