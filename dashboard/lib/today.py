"""Numbers for the manager's "Today" home: one call per source, each failure-tolerant (a role that may not read a source
gets None for those numbers, never an error). Everything is scoped to the property the session looks at."""

from __future__ import annotations

import re
from datetime import datetime

from . import auth, platform, tenancy

TARGET_MIN = {"high": 30, "medium": 60, "low": 120}  # same ASSUMED targets as the platform's performance score
OPEN = ("offered", "accepted", "in_progress", "unassigned", "new")


def _try(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except platform.PlatformError:
        return None


def _minutes_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso))
    except ValueError:
        return None
    now = datetime.now(t.tzinfo) if t.tzinfo else datetime.now()
    return (now - t).total_seconds() / 60


def gather() -> dict:
    """{rooms, summary, requests, jobs_late, waiting_jobs, on_shift, staff, low_stock, late_checkouts, staffing_pending}."""
    pid = tenancy.property_id()
    out: dict = {"property": tenancy.current_property(), "mode": tenancy.mode()}
    rp = _try(platform.rooms)
    numbers = {r["number"] for r in (rp or {}).get("rooms", [])}
    out["rooms"] = (rp or {}).get("rooms")
    out["summary"] = (rp or {}).get("summary")

    gs = _try(platform.guest_summary)
    reqs = None
    if gs is not None:
        reqs = [q for q in gs.get("open_requests", []) if not numbers or q.get("room") in numbers]
        out["late_checkouts"] = gs.get("late_checkouts_pending", 0)
        if out["late_checkouts"]:  # the rooms and times, for a plain sentence on Today
            rows = _try(platform.late_checkouts)
            rows = rows if isinstance(rows, list) else (rows or {}).get("items") if isinstance(rows, dict) else None
            out["late_checkout_rows"] = [r for r in rows or [] if r.get("status") == "pending"]
        out["checkouts_today"] = (gs.get("checkouts_today") or {}).get("count")
        out["urgent"] = [a for a in gs.get("urgent_alerts", []) if not numbers or a.get("room") in numbers]
    out["requests"] = reqs

    jobs = _try(platform.jobs)
    if jobs is not None:
        mine = [
            j
            for j in jobs
            if (j.get("room") in numbers)
            or (j.get("property_id") == pid)
            or (not j.get("room") and not j.get("property_id") and _is_first(pid))
        ]
        late, waiting = [], []
        for j in mine:
            if j["status"] in ("accepted", "in_progress"):
                m = _minutes_since(j.get("accepted_at"))
                if m is not None and m > TARGET_MIN.get(j.get("urgency") or "medium", 60):
                    late.append(j)
            elif j["status"] in ("unassigned", "new"):
                waiting.append(j)
        out["jobs_late"], out["waiting_jobs"] = late, waiting
        out["open_jobs"] = [j for j in mine if j["status"] in OPEN]
    else:
        out["jobs_late"] = out["waiting_jobs"] = out["open_jobs"] = None

    staff = _try(platform.staff)
    team = None
    if staff is not None:
        first = (tenancy.properties() or [{}])[0].get("id")
        team = [s for s in staff if (s.get("property_id") or first) == pid and s.get("department") != "management"]
    out["staff"] = team
    if tenancy.mode() == "homestay":
        out["on_shift"] = len(team) if team is not None else None  # homestay: the whole small team, no roster
    else:
        ctx = _try(platform.get_context)
        out["context"] = ctx
        ids = {s["employee_id"] for s in team or []}
        out["on_shift"] = len([e for e in (ctx or {}).get("working", {}) if not ids or e in ids]) if ctx is not None else None

    stock = _try(platform.inv, "GET", "/stock")
    items = _try(platform.inv, "GET", "/items")
    if stock is not None and items is not None:
        have = stock.get("on_hand") or {}
        out["low_stock"] = [i for i in items if float(have.get(i["id"], 0) or 0) <= float(i.get("reorder_point") or 0)]
    else:
        out["low_stock"] = None

    sr = _try(platform.staffing_requests) if auth.role() in ("owner", "hr", "dept_head", "platform_admin") else None
    out["staffing_pending"] = [r for r in sr or [] if r.get("status") == "pending_send"]
    return out


def _is_first(pid: str | None) -> bool:
    props = tenancy.properties()
    return not props or props[0]["id"] == pid


def n(x) -> str:
    """Count for a big number; '—' when the role cannot see that source."""
    if x is None:
        return "—"
    return str(len(x)) if isinstance(x, list) else str(x)


def shortfall(ctx: dict | None) -> list[dict]:
    """Departments short of people in the current shift (day + shift from the dispatch context), from the week's shift plan.

    Each row: {department, hours, people}. people = hours short / that shift's usual length in the plan, rounded up
    (an estimate; the plan itself reports hours). Empty when there is no plan, no context or the ML API is unreachable."""
    from . import api_client, data

    if not ctx or not ctx.get("shift"):
        return []
    try:
        rid = data.current_roster_id()
        ro = data.roster(rid) if rid is not None else None
    except api_client.ApiError:
        return []
    if ro is None or not ro.dates:
        return []
    day, shift = ctx.get("day") or ro.dates[0], ctx["shift"]
    if day not in ro.dates:
        return []
    i = ro.dates.index(day)
    rows = [
        {"department": d, "hours": h, "people": people_for_hours(ro, shift, h)}
        for (d, di, sh), h in ro.short_by_cell().items()
        if di == i and sh == shift and h > 0.5
    ]
    return sorted(rows, key=lambda r: -r["hours"])


def people_for_hours(ro, shift: str, hours: float) -> int:
    """Hours short -> about how many people: divided by that shift's usual length in the plan, rounded up (an estimate)."""
    from math import ceil
    from statistics import median

    lengths = [float(a.get("hours") or 0) for a in ro.assignments if a.get("shift") == shift and a.get("hours")]
    shift_h = median(lengths) if lengths else 8.0
    return max(1, ceil(hours / shift_h - 0.15))


# ------------------------------------------------------------------ plain sentences for the "Also needs you" rows
TEAM = {
    "front_office": "the front desk",
    "housekeeping": "housekeeping",
    "maintenance": "maintenance",
    "fnb_service": "the restaurant team",
    "kitchen": "the kitchen",
    "security": "security",
    "management": "the manager",
    "stores": "the store",
}
_ROOM_SUFFIX = re.compile(r"\s*·\s*room\s+\S+\s*$", re.I)


def team(department: str | None) -> str:
    d = str(department or "").strip().lower()
    return TEAM.get(d) or (d.replace("_", " ") if d else "someone")


def waited(minutes: float | None) -> str:
    """40 -> '40 min', 75 -> '1 h 15 min', 1 -> '1 min'."""
    if minutes is None:
        return ""
    m = max(1, int(minutes))
    if m < 60:
        return f"{m} min"
    h, r = divmod(m, 60)
    return f"{h} h {r} min" if r else f"{h} h"


def _lower_first(s: str) -> str:
    """'Fresh towels' -> 'fresh towels', but 'AC / heater not working' stays as it is."""
    return s[:1].lower() + s[1:] if len(s) > 1 and s[1:2].islower() else s


def job_sentence(j: dict) -> str:
    """'Something else: Call on the front desk. · room 101' (front_office) -> 'Room 101 needs the front desk. The guest
    wrote: "Call on the front desk."'. The guest's own words are shown in quotes; the request type in plain words."""
    base = _ROOM_SUFFIX.sub("", str(j.get("title") or "")).strip()
    label, _, note = base.partition(": ")
    label, note = label.strip(), note.strip()
    said = f' The guest wrote: "{note}"' if note else ""
    who = team(j.get("department"))
    if not j.get("room"):
        return f"{base or 'A job'} ({who})."
    if label.lower().startswith("something else"):
        return f"Room {j['room']} needs {who}.{said}"
    return f"Room {j['room']} needs {who}: {_lower_first(label)}.{said}"


def waiting_sentence(j: dict) -> str:
    m = _minutes_since(j.get("created_at"))
    return f"Nobody has taken it for {waited(m)}." if m is not None else "Nobody has taken it yet."


def late_sentence(jobs: list[dict]) -> tuple[str, str]:
    """(title, why) for jobs past their target time."""
    oldest = max(jobs, key=lambda j: _minutes_since(j.get("accepted_at")) or 0)
    m = _minutes_since(oldest.get("accepted_at"))
    title = f"{job_sentence(oldest)} It is taking longer than it should."
    if len(jobs) > 1:
        title = f"{len(jobs)} jobs are taking longer than they should."
        why = f"The oldest: {job_sentence(oldest)} Started {waited(m)} ago." if m is not None else f"The oldest: {job_sentence(oldest)}"
    else:
        why = f"Started {waited(m)} ago." if m is not None else "Past its target time."
    return title, why


def late_checkout_sentence(count: int, rows: list[dict] | None) -> tuple[str, str]:
    """(title, why) for guests waiting for a yes or no on a late checkout."""
    rows = rows or []
    first = min(rows, key=lambda r: str(r.get("created_at") or "")) if rows else None
    if count == 1 and first:
        title = f"Room {first.get('room')} wants to check out late, at {first.get('until')}."
    elif rows:
        rooms = ", ".join(str(r.get("room")) for r in rows[:3]) + (" …" if len(rows) > 3 else "")
        title = f"{count} guests want to check out late (rooms {rooms})."
    else:
        title = f"{count} guest{'s want' if count != 1 else ' wants'} to check out late."
    m = _minutes_since(first.get("created_at")) if first else None
    why = (f"Asked {waited(m)} ago. " if m is not None else "") + "They are waiting for your yes or no."
    return title, why


def names_sentence(names: list[str]) -> str:
    """['HS05'] -> 'HS05', ['HS05', 'HS12'] -> 'HS05 and HS12', 3+ -> 'HS05, HS12 and HS14'."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
