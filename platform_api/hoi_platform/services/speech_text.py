"""Text normalisation before speaking a reply aloud (server TTS path; mirrored in static/shared/voice.js for the browser).

Hindi: "11:00" -> "ग्यारह बजे", "07:30" -> "साढ़े सात बजे", "13:00" -> "दोपहर एक बजे", "₹180" -> "एक सौ अस्सी रुपये",
room "204" -> "दो सौ चार", "07:30-10:30" -> "साढ़े सात बजे से साढ़े दस बजे तक".
English: "11:00" -> "eleven o'clock", "13:30" -> "one thirty p.m.", "₹180" -> "180 rupees".
Both: emoji and markdown symbols removed. Pure functions, no I/O.
"""

from __future__ import annotations

import re

HI_0_99 = (
    "शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
    "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस "
    "अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन "
    "तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर "
    "इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी "
    "छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे"
).split()
assert len(HI_0_99) == 100
EN_0_19 = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
EN_TENS = "_ _ twenty thirty forty fifty".split()

_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿️‍]")
_MD = re.compile(r"[*_#`>~|]+")
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
TIME = r"([01]?\d|2[0-3])[:.]([0-5]\d)"


def hi_number(n: int) -> str:
    """0 .. 99,99,999 in Hindi words (Indian grouping: हज़ार, लाख)."""
    if n < 100:
        return HI_0_99[n]
    parts = []
    for size, word in ((100000, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        if n >= size:
            parts.append(f"{hi_number(n // size)} {word}")
            n %= size
    if n:
        parts.append(HI_0_99[n])
    return " ".join(parts)


def _hi_hour(h: int) -> str:
    return HI_0_99[h % 12 or 12]


def hi_time(h: int, m: int) -> str:
    period = "दोपहर " if 12 <= h < 16 else "शाम " if 16 <= h < 20 else "रात " if h >= 20 or h < 4 else ""
    if m == 0:
        core = f"{_hi_hour(h)} बजे"
    elif m == 30:
        core = {1: "डेढ़ बजे", 2: "ढाई बजे"}.get(h % 12, f"साढ़े {_hi_hour(h)} बजे")
    elif m == 15:
        core = f"सवा {_hi_hour(h)} बजे"
    elif m == 45:
        core = f"पौने {_hi_hour(h + 1)} बजे"
    else:
        core = f"{_hi_hour(h)} बजकर {HI_0_99[m]} मिनट"
    return period + core


def _en_small(n: int) -> str:
    if n < 20:
        return EN_0_19[n]
    t, u = divmod(n, 10)
    return EN_TENS[t] + ("-" + EN_0_19[u] if u else "")


def en_time(h: int, m: int) -> str:
    h12 = h % 12 or 12
    if m == 0:
        if h == 12:
            return "twelve noon"
        return f"{_en_small(h12)} o'clock" if h < 12 else f"{_en_small(h12)} p.m."
    mins = f"oh {_en_small(m)}" if m < 10 else _en_small(m)
    return f"{_en_small(h12)} {mins}" + (" p.m." if h >= 12 else "")


def for_speech(text: str, lang: str) -> str:
    t = _MD.sub(" ", _EMOJI.sub("", str(text or "").translate(_DEV_DIGITS)))
    hi = lang == "hi"
    tf = hi_time if hi else en_time

    def rng(mt: re.Match) -> str:
        a, b = tf(int(mt[1]), int(mt[2])), tf(int(mt[3]), int(mt[4]))
        return f"{a} से {b} तक" if hi else f"{a} to {b}"

    t = re.sub(TIME + r"\s*[-–]\s*" + TIME, rng, t)
    t = re.sub(r"(?<![\d:])" + TIME + r"(?![\d:])", lambda mt: tf(int(mt[1]), int(mt[2])), t)
    if hi:
        t = re.sub(r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)", lambda mt: f"{hi_number(int(mt[1].replace(',', '')))} रुपये", t, flags=re.I)
        t = re.sub(r"(\d[\d,]*)\s*(?:₹|rupees|rs\.?|inr)", lambda mt: f"{hi_number(int(mt[1].replace(',', '')))} रुपये", t, flags=re.I)
        t = re.sub(r"\bext\.?\s*", "एक्सटेंशन ", t, flags=re.I)
        t = re.sub(r"\d{1,7}", lambda mt: hi_number(int(mt[0])), t)
        t = t.replace("Wi-Fi", "वाई-फ़ाई")
        t = re.sub(r"बजे\s+बजे", "बजे", re.sub(r"तक\s+तक", "तक", t))
    else:
        t = re.sub(r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)", r"\1 rupees", t, flags=re.I)
        t = re.sub(r"\bext\.\s*", "extension ", t, flags=re.I)
    return " ".join(t.split())


def sentences(text: str) -> list[str]:
    """Split on । . ? ! so long replies are spoken (and can be stopped) sentence by sentence."""
    return [s.strip() for s in re.split(r"(?<=[।.?!])\s+", text) if s.strip()]
