"""Hotel setup (voice) page helpers: show a draft field as one editable text cell and read it back.

Pure functions (no Streamlit), so the formats stay in one place:
  departments  "housekeeping: 3, kitchen: 2"      head_roles "kitchen: head chef"
  shifts       "morning 07:00-15:00; evening 15:00-23:00"
  peak_months  "5, 6, 12"                         numbers / text as typed
"""

from __future__ import annotations

from typing import Any

LABELS = {
    "hotel_name": "Hotel name",
    "hotel_type": "Hotel type",
    "rooms": "Rooms",
    "location": "Location",
    "peak_months": "Peak months (1-12)",
    "departments": "Departments: headcount",
    "head_roles": "Head of each department",
    "shifts": "Shifts",
    "standard_weekly_hours": "Standard weekly hours",
    "weekly_off_days": "Weekly off days",
    "min_rest_hours": "Minimum rest between shifts (h)",
    "max_consecutive_days": "Max consecutive working days",
    "overtime_rate_multiplier": "Overtime rate (x normal)",
    "incentive_monthly_budget_cap": "Monthly incentive budget cap (INR)",
}
INT_FIELDS = {"rooms", "standard_weekly_hours", "weekly_off_days", "max_consecutive_days", "incentive_monthly_budget_cap"}
FLOAT_FIELDS = {"min_rest_hours", "overtime_rate_multiplier"}
SOURCE_LABEL = {"template": "template", "voice": "voice", "typed": "typed", "default": "not set"}


def format_value(field: str, value: Any) -> str:
    if value is None:
        return ""
    if field in ("departments", "head_roles"):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    if field == "shifts":
        return "; ".join(f"{s['name']} {s['start']}-{s['end']}" for s in value)
    if field == "peak_months":
        return ", ".join(str(m) for m in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def parse_value(field: str, text: str) -> Any:
    """The cell text as the API value; ValueError with a plain message when it cannot be read."""
    t = (text or "").strip()
    if not t:
        return None
    if field in INT_FIELDS:
        v = float(t)
        if not v.is_integer():
            raise ValueError(f"{LABELS[field]} must be a whole number")
        return int(v)
    if field in FLOAT_FIELDS:
        return float(t)
    if field == "peak_months":
        return [int(x) for x in t.replace(";", ",").split(",") if x.strip()]
    if field in ("departments", "head_roles"):
        out: dict[str, Any] = {}
        for part in t.split(","):
            if not part.strip():
                continue
            if ":" not in part:
                raise ValueError(f"write {LABELS[field]} as 'name: value, name: value'")
            k, v = (x.strip() for x in part.split(":", 1))
            out[k] = int(v) if field == "departments" else v
        return out
    if field == "shifts":
        shifts = []
        for part in t.split(";"):
            if not part.strip():
                continue
            name, _, times = part.strip().rpartition(" ")
            start, _, end = times.partition("-")
            if not name or not start or not end:
                raise ValueError("write shifts as 'morning 07:00-15:00; evening 15:00-23:00'")
            shifts.append({"name": name.strip(), "start": start.strip(), "end": end.strip()})
        return shifts
    return t


def confidence_badge(conf: float, accept: float = 0.6) -> tuple[str, str]:
    """(band tone for theme.band_chip, label)."""
    if conf >= 0.85:
        return "low", f"{conf:.0%} high"
    if conf >= accept:
        return "watch", f"{conf:.0%} medium"
    return "high", f"{conf:.0%} check"
