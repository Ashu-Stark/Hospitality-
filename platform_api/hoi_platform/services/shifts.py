"""Live shift clock: which rostered shift is running now, in hotel local time. Pure functions (no database).

Shift windows are ASSUMED (backend/hotels/himsagar.yaml: front office 06:00-23:00 as morning + evening, security
night 22:00-07:00; the same windows as scripts/hoi_scenarios.py SHIFT_WINDOWS). They overlap by an hour at each
hand-over, so both teams count as on shift then. A hotel can set its own in tenant settings "shift_windows"
({"morning": ["06:00", "15:00"], ...}). A window whose end is not after its start runs past midnight: at 02:00 the
night shift that started the previous evening is the one running, and it belongs to the PREVIOUS date.

Roster week mapping: a published roster covers one week. When that week does not contain today (the demo week is in
2029), each real date maps to the same weekday of the published week, so the roster repeats every week.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

DEFAULT_WINDOWS: dict[str, tuple[str, str]] = {"morning": ("06:00", "15:00"), "evening": ("14:00", "23:00"), "night": ("22:00", "07:00")}


def _min(hhmm: str) -> int:
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def windows(settings: dict | None = None) -> dict[str, tuple[int, int]]:
    """shift -> (start minute, length in minutes) from the hotel's settings, else the defaults."""
    raw = (settings or {}).get("shift_windows") or DEFAULT_WINDOWS
    out = {}
    for name, (start, end) in raw.items():
        s, e = _min(start), _min(end)
        out[name] = (s, (e - s) % 1440 or 1440)
    return out


def running(now_local: datetime, wins: dict[str, tuple[int, int]]) -> list[dict]:
    """Shifts running at `now_local` (naive or aware local time): [{shift, date, start, end}], latest start first."""
    out = []
    for name, (s, length) in wins.items():
        for back in (0, 1):  # a shift that started today, or yesterday and runs past midnight
            d = now_local.date() - timedelta(days=back)
            start = datetime(d.year, d.month, d.day, tzinfo=now_local.tzinfo) + timedelta(minutes=s)
            end = start + timedelta(minutes=length)
            if start <= now_local < end:
                out.append({"shift": name, "date": d, "start": start, "end": end})
    return sorted(out, key=lambda r: r["start"], reverse=True)


def map_to_week(d: date, week_start: str | None, dates: list[str]) -> str:
    """The roster date for a real date: itself when the published week contains it, else the same weekday in that week."""
    if d.isoformat() in dates:
        return d.isoformat()
    ws = date.fromisoformat(week_start) if week_start else (min(date.fromisoformat(x) for x in dates) if dates else d)
    return (ws + timedelta(days=(d.weekday() - ws.weekday()) % 7)).isoformat()
