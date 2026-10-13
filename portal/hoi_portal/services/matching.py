"""Transparent match score between a job (or a candidate search) and a job-seeker profile.

score = 100 x sum(weight_i x part_i) / sum(weight_i) over the criteria the job/search actually sets:
  skills        mean over required skills: exact skill -> min_credit + (1 - min_credit) x min(years, full)/full;
                same-category skill -> related_credit; otherwise 0
  district      preferred district 1.0, "any district" 0.75, same division 0.4, otherwise 0
  availability  job-type factor (same type 1, else type_mismatch) x share of the job's season the seeker is available
  language      share of the job's languages the seeker speaks
Weights and credits live in hoi_portal/hiring.yaml (ASSUMED). Deterministic: same inputs, same score and reasons.
Only those four inputs exist on a profile; there are no protected attributes to use.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .. import miniyaml
from ..seed.districts import BY_ID as DISTRICTS
from ..seed.skills import BY_KEY as SKILLS

CONFIG_PATH = Path(__file__).resolve().parent.parent / "hiring.yaml"
CFG: dict = miniyaml.load(CONFIG_PATH)


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _skills(job: dict, prof: dict) -> tuple[float, list[dict]] | None:
    req = job.get("skills") or []
    if not req:
        return None
    c = CFG["skills"]
    full, lo, rel = float(c["full_credit_years"]), float(c["min_credit"]), float(c["related_credit"])
    have = {s["key"]: int(s.get("years") or 0) for s in prof.get("skills") or []}
    total, why = 0.0, []
    for k in req:
        label = SKILLS[k]["label"] if k in SKILLS else k
        if k in have:
            y = have[k]
            total += lo + (1 - lo) * min(y, full) / full
            why.append({"ok": True, "text": f"{label}: {y} yr{'s' if y != 1 else ''}"})
            continue
        cat = SKILLS.get(k, {}).get("category")
        related = sorted(h for h in have if SKILLS.get(h, {}).get("category") == cat and cat)
        if related:
            total += rel
            why.append({"ok": True, "partial": True, "text": f"Related skill: {SKILLS[related[0]]['label']}"})
        else:
            why.append({"ok": False, "text": f"No {label.lower()}"})
    return total / len(req), why


def _district(job: dict, prof: dict) -> tuple[float, list[dict]] | None:
    d = job.get("district")
    if not d or d not in DISTRICTS:
        return None
    c = CFG["district"]
    prefs = prof.get("districts") or []
    name = DISTRICTS[d]["name"]
    if not prefs:
        return float(c["any"]), [{"ok": True, "partial": True, "text": "Open to any district"}]
    if d in prefs:
        return float(c["preferred"]), [{"ok": True, "text": f"Prefers {name}"}]
    div = DISTRICTS[d]["division"]
    if any(DISTRICTS.get(p, {}).get("division") == div for p in prefs):
        return float(c["same_division"]), [{"ok": True, "partial": True, "text": f"Prefers nearby {div} districts"}]
    return 0.0, [{"ok": False, "text": f"Prefers other districts, not {name}"}]


def _availability(job: dict, prof: dict) -> tuple[float, list[dict]] | None:
    jtype, jf, jt = job.get("job_type"), _d(job.get("season_from")), _d(job.get("season_to"))
    if not jtype and not (jf and jt):
        return None
    why = []
    factor = 1.0
    ptype = prof.get("availability")
    if jtype and ptype and ptype != jtype:
        factor = float(CFG["availability"]["type_mismatch"])
        why.append({"ok": False, "partial": True, "text": f"Looking for {ptype.replace('_', '-')} work"})
    overlap = 1.0
    if jf and jt and jt >= jf:
        pf, pt = _d(prof.get("available_from")), _d(prof.get("available_to"))
        lo, hi = max(jf, pf or jf), min(jt, pt or jt)
        span = (jt - jf).days + 1
        overlap = max(0, (hi - lo).days + 1) / span if hi >= lo else 0.0
        if not pf and not pt:
            why.append({"ok": True, "text": "Available any time"})
        elif overlap >= 0.999:
            why.append({"ok": True, "text": "Available for the whole period"})
        elif overlap > 0:
            why.append({"ok": True, "partial": True, "text": f"Available for {round(overlap * 100)}% of the period"})
        else:
            why.append({"ok": False, "text": "Not available in this period"})
    elif factor == 1.0:
        why.append({"ok": True, "text": f"Wants {jtype.replace('_', '-')} work" if jtype else "Available"})
    return factor * overlap, why


def _language(job: dict, prof: dict) -> tuple[float, list[dict]] | None:
    langs = job.get("languages") or []
    if not langs:
        return None
    have = set(prof.get("languages") or [])
    spoken = [x for x in langs if x in have]
    missing = [x for x in langs if x not in have]
    why = [{"ok": True, "text": "Speaks " + ", ".join(spoken)}] if spoken else []
    if missing:
        why.append({"ok": False, "text": "No " + ", ".join(missing)})
    return len(spoken) / len(langs), why


PARTS = (
    ("skills", "Skills", _skills),
    ("district", "District", _district),
    ("availability", "Availability", _availability),
    ("language", "Language", _language),
)


def score(job: dict, prof: dict) -> dict:
    """`job` needs any of skills, district, job_type, season_from/to, languages. Returns score (0-100 or None), parts, why."""
    weights = CFG["weights"]
    parts, why, num, den = [], [], 0.0, 0.0
    for key, label, fn in PARTS:
        r = fn(job, prof)
        if r is None:
            continue
        value, reasons = r
        w = float(weights[key])
        num += w * value
        den += w
        parts.append({"key": key, "label": label, "value": round(value, 3), "weight": w})
        why += reasons
    return {
        "score": round(100 * num / den) if den else None,
        "parts": parts,
        "why": why,
        "basis": "Skills and experience, district, availability and language only. Weights are ASSUMED (hiring.yaml).",
    }
