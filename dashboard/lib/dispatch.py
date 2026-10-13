"""Frontend helpers for dispatch. The engine itself (ranking, offers, expiry) runs in the platform API;
this module only works out who is on shift from the roster and labels things for the UI."""

from __future__ import annotations

from datetime import date, datetime

DEPARTMENTS = ["housekeeping", "maintenance", "fnb_service", "front_office", "security", "kitchen"]
DEPT_KEYWORDS = {
    "maintenance": ["ac", "a/c", "geyser", "leak", "light", "bulb", "tv", "wifi", "plumb", "tap", "fan", "repair", "heater", "socket"],
    "housekeeping": ["towel", "clean", "bed", "sheet", "linen", "amenit", "toilet paper", "dust", "turndown", "pillow", "blanket"],
    "fnb_service": ["food", "order", "tea", "coffee", "breakfast", "dinner", "water bottle", "room service", "menu"],
    "front_office": ["checkout", "check-out", "check in", "key card", "bill", "invoice", "taxi", "luggage"],
    "security": ["noise", "suspicious", "parking", "guard", "lost", "fight"],
    "kitchen": ["kitchen", "cook", "allergy", "special meal"],
}


def guess_department(text: str) -> str:
    """UI pre-fill only; the server makes its own inference when no department is sent."""
    t = f" {text.lower()} "
    for dept, words in DEPT_KEYWORDS.items():
        if any((f" {w} " in t) if len(w) <= 3 else (w in t) for w in words):
            return dept
    return "housekeeping"


def shift_for_hour(h: int) -> str:
    return "morning" if 6 <= h < 14 else "evening" if 14 <= h < 22 else "night"


def on_shift(roster, staff_rows: list[dict], day: str | None, shift: str) -> dict[str, str]:
    """employee_id -> department for people working (day, shift). Falls back to imported staff without a roster."""
    if roster is not None and roster.assignments:
        dept = roster.dept_of
        d = day or roster.dates[0]
        return {
            a["employee_id"]: dept.get(a["employee_id"], "unknown") for a in roster.assignments if a["date"] == d and a["shift"] == shift
        }
    return {r["employee_id"]: r["department"] for r in staff_rows}


def ops_context(roster) -> tuple[str | None, str]:
    """Default operating day/shift: today's weekday mapped onto the roster week, shift from the clock."""
    now = datetime.now()
    day = None
    if roster is not None and roster.dates:
        day = next((d for d in roster.dates if date.fromisoformat(d).weekday() == now.weekday()), roster.dates[0])
    return day, shift_for_hour(now.hour)
