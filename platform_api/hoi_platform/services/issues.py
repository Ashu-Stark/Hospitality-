"""Guest issue understanding v2: the always-available, rule-based classifier behind the concierge, the request menu and the
worker's "report issue" voice command. Taxonomy and every ASSUMED value: hoi_platform/guest_issues.yaml.

- Bilingual lexicon (English, Hindi in Devanagari, Hinglish in Latin letters with common spellings), whole-word matching with
  Devanagari-safe boundaries, so "room"/"kamra" or a word inside a longer word ("bonfire") never triggers anything.
- Negation for the types marked negatable ("no rat now", "chuha nahi hai", "धुआँ नहीं है").
- Priority = order in the YAML (safety > medical > pest > leak > lock > ...). Several problems in one message: the first is
  the action, the others are returned so the reply can mention them.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml

TAXONOMY_FILE = Path(__file__).resolve().parent.parent / "guest_issues.yaml"
DEV = "ऀ-ॿ"
_FOLD = str.maketrans({"’": "'", "‘": "'", "़": None, "‑": "-", "‐": "-"})  # quotes, nukta, hyphens
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def norm(text: str) -> str:
    return " ".join(str(text or "").lower().translate(_DIGITS).translate(_FOLD).split())


@functools.cache
def taxonomy() -> dict:
    return yaml.safe_load(TAXONOMY_FILE.read_text(encoding="utf-8"))


def _pattern(word: str) -> re.Pattern:
    """Whole-word pattern: Latin words may not touch other letters/digits; Devanagari words may not touch Devanagari."""
    w = norm(word)
    body = re.escape(w).replace(r"\ ", r"\s+")
    if re.search(f"[{DEV}]", w):
        return re.compile(rf"(?<![{DEV}]){body}(?![{DEV}])")
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


@functools.cache
def _compiled() -> list[tuple[str, dict, list[tuple[str, re.Pattern]]]]:
    out = []
    for tid, spec in taxonomy()["types"].items():
        words = [str(w) for lang in ("en", "hi", "hinglish") for w in spec.get("keywords", {}).get(lang, [])]
        assert all(w.strip() and w not in ("True", "False") for w in words), f"{tid}: quote yes/no words in the YAML"
        words = sorted(set(words), key=len, reverse=True)  # longest first: "gas leak" before "leak"
        spec = {**spec, "_exclude": [_pattern(str(x)) for x in spec.get("exclude") or []]}
        out.append((tid, spec, [(w, _pattern(w)) for w in words]))
    return out


@functools.cache
def _neg() -> list[re.Pattern]:
    return [_pattern(str(w)) for w in taxonomy()["negations"] if str(w).strip()]


@functools.cache
def _problem() -> list[re.Pattern]:
    return [_pattern(str(w)) for w in taxonomy()["problem_words"] if str(w).strip()]


def is_problem(text: str) -> bool:
    t = norm(text)
    return any(p.search(t) for p in _problem())


def _negated(t: str, start: int, end: int) -> bool:
    """A negation word within ~3 words before the keyword, or right after it (Hindi word order: "chuha nahi hai")."""
    before = t[max(0, start - 24) : start]
    after = t[end : end + 14]
    return any(p.search(before) for p in _neg()) or any(p.search(after) for p in _neg())


def only_stopwords(text: str) -> bool:
    stop = {norm(w) for w in taxonomy()["stopwords"]}
    words = re.findall(rf"[a-z0-9{DEV}']+", norm(text))
    return bool(words) and all(w in stop for w in words)


def classify(text: str) -> list[dict]:
    """Problems found in the message, highest priority first: [{type, word, department, urgency, ...}]. [] = none."""
    t = norm(text)
    found, taken = [], []
    for tid, spec, pats in _compiled():
        if spec.get("requires_problem") and not is_problem(t):
            continue
        blocked = [m.span() for x in spec["_exclude"] for m in x.finditer(t)]  # "fireplace", "bonfire", "no smoking"
        for word, pat in pats:
            hit = None
            for m in pat.finditer(t):
                if any(m.start() < e and s < m.end() for s, e in taken + blocked):  # inside a higher-priority match ("gas leak")
                    continue
                if spec.get("negatable") and _negated(t, m.start(), m.end()):
                    continue
                hit = m
                break
            if hit:
                taken.append((hit.start(), hit.end()))
                found.append({"type": tid, "word": word, **info(tid)})
                break
    return found


def top(text: str) -> dict | None:
    hits = classify(text)
    return hits[0] if hits else None


def info(tid: str) -> dict:
    spec = taxonomy()["types"].get(tid) or {}
    deps = spec.get("departments") or []
    return {
        "department": deps[0] if deps else None,
        "departments": deps,
        "urgency": spec.get("urgency"),
        "target_minutes": spec.get("target_minutes") or taxonomy().get("targets", {}).get(tid),
        "urgent": spec.get("urgency") == "urgent",
    }


def target_minutes(tid: str) -> int | None:
    spec = taxonomy()["types"].get(tid)
    if spec:
        return spec.get("target_minutes")
    return taxonomy().get("targets", {}).get(tid)


def team(dept: str, lang: str) -> str:
    t = taxonomy()["teams"].get(dept) or {}
    return t.get(lang) or t.get("en") or dept.replace("_", " ")


def teams_phrase(depts: list[str], lang: str) -> str:
    names = [team(d, lang) for d in depts]
    if len(names) <= 1:
        return names[0] if names else ""
    joiner = {"hi": " और ", "hinglish": " aur "}.get(lang, " and ")
    return joiner.join(names)


def menu_entries() -> dict[str, dict]:
    """New request-menu types from the taxonomy, in the shape of rooms.GUEST_MENU."""
    out = {}
    for tid, spec in taxonomy()["types"].items():
        out[tid] = {
            "label": spec["label"]["en"],
            "label_hi": spec["label"]["hi"],
            "dept": (spec.get("departments") or ["front_office"])[0],
            "departments": spec.get("departments") or ["front_office"],
            "urgency": spec.get("urgency", "medium"),
            "target_minutes": spec.get("target_minutes"),
            "offer_seconds": spec.get("offer_seconds"),
            "group": spec.get("menu", "request"),
            "notify_manager": bool(spec.get("notify_manager")),
        }
    return out


def emergency_numbers(tid: str) -> list[dict]:
    return list(taxonomy().get("emergency_numbers", {}).get(tid) or [])


def reply(tid: str, lang: str, *, room: str, word: str = "", room_change: bool = False, also: list[str] | None = None) -> str:
    """The calm, empathetic template reply for a problem type: who is coming and roughly when."""
    spec = taxonomy()["types"][tid]
    tmpl = spec["reply"].get(lang) or spec["reply"]["en"]
    thing = word or spec["label"][("hi" if lang == "hi" else "en")].split(" (")[0].lower()
    rc = ""
    if room_change and spec.get("room_change"):
        rc = {
            "hi": " अगर आप चाहें, तो फ़्रंट डेस्क देख सकता है कि कोई दूसरा कमरा ख़ाली है या नहीं।",
            "hinglish": " Aap chahein toh front desk dekh sakta hai ki koi doosra room khaali hai ya nahi.",
        }.get(lang, " If you'd like, the front desk can check whether another room is free.")
    text = tmpl.format(
        team=teams_phrase(spec.get("departments") or [], lang), room=room, minutes=spec.get("target_minutes"), thing=thing, room_change=rc
    )
    if also:
        names = ", ".join(taxonomy()["types"][a]["label"]["hi" if lang == "hi" else "en"].split(" (")[0].lower() for a in also)
        text += {
            "hi": f" आपने {names} भी बताया; उसके लिए भी अलग से अनुरोध भेज सकते हैं।",
            "hinglish": f" Aapne {names} bhi bataya; uske liye bhi alag se request bhej sakte hain.",
        }.get(lang, f" You also mentioned {names}; I can send that as a separate request too.")
    return text
