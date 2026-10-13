"""Deterministic number normaliser (Part C): English, Hinglish and Devanagari number words.

normalise(text) -> Reading: the text in lower case (Unicode NFC) with every number phrase
rewritten as digits ("barah kamre" -> "12 kamre", "ek sau bees" -> "120", "dedh guna" ->
"1.5 guna", "double" -> "2 guna", "१२" -> "12"), plus the list of numbers read. The word table is
numbers.yaml (flagged for HM-student review). No model and no network: the same input always
gives the same output, so it can cross-check what an LLM claims was said.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from backend.onboarding.config import ONBOARDING_DIR

NUMBERS_PATH = ONBOARDING_DIR / "numbers.yaml"
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
# a word: Latin / digits / Devanagari letters and marks (not the dandas U+0964 / U+0965);
# numbers may carry a decimal part ("1.5") or be a clock time ("7:30", kept as one token).
TOKEN = re.compile(r"\d+(?:[.:]\d+)?|[a-z'ऀ-ॣ०-ॿ]+")
TENS_MIN, TENS_MAX, TEN, HUNDRED = 20, 90, 10, 100
MULTIPLIER_SUFFIX = "guna"
AND = "and"
HYPHEN_IN_WORDS = re.compile(r"(?<=[a-z])-(?=[a-z])")   # "twenty-one"; "10pm-6am" keeps it


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ambiguity(_Strict):
    not_after: list[str]
    not_before: list[str]


class NumberTable(_Strict):
    review: dict[str, str | bool]
    english: dict[int, list[str]]
    hindi_roman: dict[int, list[str]]
    hindi_devanagari: dict[int, list[str]]
    scale_words: dict[int, list[str]]
    fractions: dict[float, list[str]]
    multipliers: dict[float, list[str]]
    ambiguous: dict[str, Ambiguity]


@dataclass(frozen=True)
class Entry:
    value: float
    kind: str        # "word" | "digit" | "scale" | "fraction" | "multiplier"
    english: bool    # English tens + units compose ("twenty one"); Hindi words never do


@dataclass(frozen=True)
class Reading:
    text: str                 # lower-case NFC text with number phrases rewritten as digits
    numbers: tuple[float, ...]


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


@lru_cache(maxsize=2)
def load_table(path: Path = NUMBERS_PATH) -> NumberTable:
    return NumberTable.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=2)
def phrase_index(path: Path = NUMBERS_PATH) -> dict[tuple[str, ...], Entry]:
    """Every phrase (as a token tuple) -> its entry; longer phrases are matched first."""
    t = load_table(path)
    out: dict[tuple[str, ...], Entry] = {}

    def add(words: list[str], entry: Entry) -> None:
        for w in words:
            key = tuple(TOKEN.findall(nfc(w.lower())))
            if key:
                out[key] = entry

    for table, english in ((t.english, True), (t.hindi_roman, False),
                           (t.hindi_devanagari, False)):
        for v, words in table.items():
            add(words, Entry(float(v), "word", english))
    for v, words in t.scale_words.items():
        add(words, Entry(float(v), "scale", False))
    for v, words in t.fractions.items():
        add(words, Entry(float(v), "fraction", False))
    for v, words in t.multipliers.items():
        add(words, Entry(float(v), "multiplier", False))
    return out


def _blocked(tokens: list[str], i: int, table: NumberTable) -> bool:
    rule = table.ambiguous.get(tokens[i])
    if rule is None:
        return False
    before = tokens[i - 1] if i > 0 else None
    after = tokens[i + 1] if i + 1 < len(tokens) else None
    return before in rule.not_after or after in rule.not_before


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _match(tokens: list[str], i: int, index: dict[tuple[str, ...], Entry],
           longest: int) -> tuple[Entry, int] | None:
    for n in range(min(longest, len(tokens) - i), 0, -1):
        e = index.get(tuple(tokens[i:i + n]))
        if e is not None:
            return e, n
    return None


def _tens(e: Entry) -> bool:
    return e.english and TENS_MIN <= e.value <= TENS_MAX and e.value % TEN == 0


def _compose(run: list[Entry]) -> list[float]:
    """Combine a run of adjacent number words into numbers ("ek sau bees" -> [120],
    "twenty one" -> [21], "do lakh pachaas hazaar" -> [250000], "12 15" -> [12, 15])."""
    out: list[float] = []
    total = cur = 0.0
    started = after_scale = tens = False
    for e in run:
        v = e.value
        scale = e.kind == "scale" or (v == HUNDRED and e.kind == "word" and 0 < cur < HUNDRED)
        if scale:
            cur = (cur or 1) * v
            if v > HUNDRED:
                total, cur = total + cur, 0.0
            started, after_scale, tens = True, True, False
        elif tens and e.english and v < TEN:
            cur, tens, after_scale = cur + v, False, False
        elif after_scale and v < HUNDRED:
            cur, tens, after_scale = cur + v, _tens(e), False
        else:
            if started:
                out.append(total + cur)
            total, cur, started = 0.0, v, True
            tens, after_scale = _tens(e), v == HUNDRED
    if started:
        out.append(total + cur)
    return out


def normalise(text: str, path: Path = NUMBERS_PATH) -> Reading:
    table, index = load_table(path), phrase_index(path)
    longest = max(len(k) for k in index)
    s = HYPHEN_IN_WORDS.sub(" ", nfc(text.lower()).translate(DEVANAGARI_DIGITS))
    matches = list(TOKEN.finditer(s))
    tokens = [m.group(0) for m in matches]
    pieces: list[str] = []
    numbers: list[float] = []
    pos = i = 0
    while i < len(tokens):
        hit = None if _blocked(tokens, i, table) else _match(tokens, i, index, longest)
        digit = tokens[i].replace(".", "", 1).isdigit()
        if hit is None and not digit:
            i += 1
            continue
        start = matches[i].start()
        run: list[Entry] = []
        special: Entry | None = None
        while i < len(tokens):
            if run and s[matches[i - 1].end():matches[i].start()].strip():
                break  # punctuation between two numbers: "100, 20" is two numbers
            if (tokens[i] == AND and run and run[-1].kind == "scale" and i + 1 < len(tokens)
                    and _match(tokens, i + 1, index, longest)):
                i += 1  # "one hundred and five"
                continue
            if tokens[i].replace(".", "", 1).isdigit():
                run.append(Entry(float(tokens[i]), "digit", False))
                i += 1
                continue
            hit = None if _blocked(tokens, i, table) else _match(tokens, i, index, longest)
            if hit is None:
                break
            entry, n = hit
            if entry.kind in ("fraction", "multiplier"):
                if run:
                    break
                special, i = entry, i + n
                break
            run.append(entry)
            i += n
        end = matches[i - 1].end()
        if special is not None:
            numbers.append(special.value)
            word = _fmt(special.value)
            if special.kind == "multiplier":
                word = f"{word} {MULTIPLIER_SUFFIX}"
        else:
            values = _compose(run)
            numbers.extend(values)
            word = " ".join(_fmt(v) for v in values)
        pieces += [s[pos:start], word]
        pos = end
    pieces.append(s[pos:])
    return Reading(text="".join(pieces), numbers=tuple(numbers))


def parse_number(word: str) -> float | None:
    """A number phrase on its own -> its value (None unless exactly one number is read)."""
    r = normalise(word)
    return r.numbers[0] if len(r.numbers) == 1 else None


def numbers_in(text: str) -> set[float]:
    """Every number said in the text (for the LLM cross-check); clock times give their hour."""
    r = normalise(text)
    out = set(r.numbers)
    for m in re.finditer(r"(\d+):(\d+)", r.text):
        out.update({float(m.group(1)), float(m.group(2))})
    return out
