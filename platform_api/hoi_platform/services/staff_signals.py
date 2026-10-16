"""Staff signals for the staff-leaving estimate: what actually happens in HOI, week by week. Employee ids only.

The ops API's attrition model (ml/attrition/live_signals.py) turns these weekly facts into its features. This module only
collects facts the platform already holds, plus four small owner / HR inputs:

  roster_history  every published roster week (PUT /dispatch/roster also keeps the week here; roster_snapshots keeps
                  only the latest one for the live shift clock)
  jobs            dispatch jobs: finished, on time (same targets as performance.py), offers declined / timed out,
                  offer -> accept seconds, finishes after the person's shift end
  recognition     thank-you points per week (recognition._facts, the same ways to earn)
  staff_hr        owner / HR only: joining date, contract end, pay band or monthly pay, last raise date, left on, role code
  staff_leave     leave / absence marks: a date and "leave" or "absent". No reason text and no health information.
  pulse_answers   the optional 1-tap "How was your week?" (good / ok / hard), only with the worker's consent
                  (pulse_consent); opting out deletes that worker's answers.

Not here: logged "We talked" check-ins live in the ops API (hoi_ops) and are added there. Planned roster hours are a
plan, not attendance (there is no clock-in). Thresholds are ASSUMED (MIN_REST_HOURS = the backend roster's 10 h rule).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from .. import mongo
from . import dispatch, performance, recognition, shifts, tenants, worklog
from .errors import Invalid, NotFound

DEFAULT_WEEKS = 12
MAX_WEEKS = 26
MIN_REST_HOURS = 10  # ASSUMED: the backend roster's minimum rest between two shifts
PULSE_ANSWERS = ("good", "ok", "hard")
LEAVE_KINDS = ("leave", "absent")
PAY_BANDS = ("below", "at", "above")
HR_DATES = ("joining_date", "contract_end_date", "last_raise_date", "left_on")
PAY_FIELDS = ("pay_band", "monthly_pay")
NOTE = (
    "Facts from HOI (published rosters, dispatch jobs, thank-you points, leave marks, consented weekly answers, the HR "
    "record). Roster hours are planned, not attendance. Employee ids only. Demo hotel: SYNTHETIC demo data."
)
PULSE_NOTE = (
    "Optional. One tap a week. Your answer helps the owner spot when work is getting too heavy. "
    "You can stop at any time; stopping deletes your answers."
)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _local_today(now: datetime | None = None) -> date:
    return (now or mongo.now()).astimezone(worklog.local_tz()).date()


def _local_date(dt) -> date | None:  # noqa: ANN001
    v = performance._aware(dt)
    return v.astimezone(worklog.local_tz()).date() if v else None


def _iso_date(v: str | None, what: str) -> str | None:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise Invalid(f"{what} must be a real date, YYYY-MM-DD.") from None


def _staff(tid: str, employee_id: str) -> dict:
    s = mongo.col("staff").find_one({"tenant_id": tid, "employee_id": employee_id.strip().upper()}, {"_id": 0})
    if not s:
        raise NotFound("No staff member with this id.")
    return s


# ------------------------------------------------------------------ roster history
def keep_roster_week(tid: str, week_start: str | None, assignments: list[dict]) -> str | None:
    """Store a published roster under its week (Monday). Called by dispatch.publish_roster."""
    dates = sorted(a["date"] for a in assignments if a.get("date"))
    try:
        ws = _monday(date.fromisoformat(week_start or dates[0]))
    except (IndexError, ValueError):
        return None
    mongo.col("roster_history").update_one(
        {"tenant_id": tid, "week_start": ws.isoformat()},
        {"$set": {"assignments": assignments, "published_at": mongo.now()}},
        upsert=True,
    )
    return ws.isoformat()


# ------------------------------------------------------------------ HR record (owner / HR only)
def hr_record(tid: str, employee_id: str) -> dict:
    s = _staff(tid, employee_id)
    r = mongo.col("staff_hr").find_one({"tenant_id": tid, "employee_id": s["employee_id"]}, {"_id": 0, "tenant_id": 0}) or {}
    return {"employee_id": s["employee_id"], "department": s["department"], **mongo.clean(r)}


def hr_records(tid: str) -> list[dict]:
    return mongo.find("staff_hr", {"tenant_id": tid}, [("employee_id", 1)])


def set_hr_record(tid: str, actor: str, employee_id: str, fields: dict) -> dict:
    s = _staff(tid, employee_id)
    sets: dict = {}
    for k in HR_DATES:
        if k in fields:
            sets[k] = _iso_date(fields[k], k.replace("_", " "))
    if "pay_band" in fields:
        if fields["pay_band"] not in (None, "", *PAY_BANDS):
            raise Invalid("Pay band must be below, at or above the role's usual pay.")
        sets["pay_band"] = fields["pay_band"] or None
    if "monthly_pay" in fields:
        v = fields["monthly_pay"]
        if v is not None and (not isinstance(v, int | float) or v < 0 or v > 10_000_000):
            raise Invalid("Monthly pay must be a number of rupees, 0 or more.")
        sets["monthly_pay"] = v
    if "role" in fields:
        sets["role"] = (str(fields["role"] or "").strip().lower()[:40]) or None
    if not sets:
        raise Invalid("Nothing to save.")
    sets["updated_at"] = mongo.now()
    mongo.col("staff_hr").update_one({"tenant_id": tid, "employee_id": s["employee_id"]}, {"$set": sets}, upsert=True)
    # field names only: pay values never go to the audit log
    tenants.audit(tid, actor, "staff.hr_record", f"{s['employee_id']} " + ",".join(sorted(k for k in sets if k != "updated_at")))
    return hr_record(tid, s["employee_id"])


# ------------------------------------------------------------------ leave / absence marks (no reasons)
def mark_leave(tid: str, actor: str, employee_id: str, day: str, kind: str = "leave") -> dict:
    s = _staff(tid, employee_id)
    if kind not in LEAVE_KINDS:
        raise Invalid("Kind must be leave or absent.")
    d = _iso_date(day, "Date")
    doc = {"tenant_id": tid, "employee_id": s["employee_id"], "date": d, "kind": kind, "created_by": actor, "created_at": mongo.now()}
    try:
        mongo.col("staff_leave").insert_one(doc)
    except DuplicateKeyError:  # one mark per person and day: a repeat updates the kind
        mongo.col("staff_leave").update_one({"tenant_id": tid, "employee_id": s["employee_id"], "date": d}, {"$set": {"kind": kind}})
    tenants.audit(tid, actor, "staff.leave_marked", f"{s['employee_id']} {d} {kind}")
    return {"employee_id": s["employee_id"], "department": s["department"], "date": d, "kind": kind}


def unmark_leave(tid: str, actor: str, employee_id: str, day: str) -> dict:
    s = _staff(tid, employee_id)
    d = _iso_date(day, "Date")
    n = mongo.col("staff_leave").delete_one({"tenant_id": tid, "employee_id": s["employee_id"], "date": d}).deleted_count
    if n:
        tenants.audit(tid, actor, "staff.leave_unmarked", f"{s['employee_id']} {d}")
    return {"employee_id": s["employee_id"], "date": d, "removed": bool(n)}


def leave_marks(tid: str, date_from: str, date_to: str, department: str | None = None) -> list[dict]:
    d0, d1 = _iso_date(date_from, "From"), _iso_date(date_to, "To")
    rows = mongo.find("staff_leave", {"tenant_id": tid, "date": {"$gte": d0, "$lte": d1}}, [("date", 1), ("employee_id", 1)])
    out = [{k: r[k] for k in ("employee_id", "date", "kind")} for r in rows]
    if department:
        dept = {s["employee_id"]: s["department"] for s in tenants.staff(tid)}
        out = [r for r in out if dept.get(r["employee_id"]) == department]
    return out


# ------------------------------------------------------------------ "How was your week?" (worker, consented)
def pulse_status(tid: str, employee_id: str, now: datetime | None = None) -> dict:
    week = _monday(_local_today(now)).isoformat()
    c = mongo.col("pulse_consent").find_one({"tenant_id": tid, "employee_id": employee_id}) or {}
    a = mongo.col("pulse_answers").find_one({"tenant_id": tid, "employee_id": employee_id, "week_start": week}) or {}
    return {
        "week_start": week,
        "consent": bool(c.get("consent")),
        "asked": bool(c),  # the worker has answered the consent question once (yes or no)
        "answer": a.get("answer"),
        "options": list(PULSE_ANSWERS),
        "note": PULSE_NOTE,
    }


def set_pulse_consent(tid: str, employee_id: str, consent: bool, now: datetime | None = None) -> dict:
    mongo.col("pulse_consent").update_one(
        {"tenant_id": tid, "employee_id": employee_id}, {"$set": {"consent": bool(consent), "at": mongo.now()}}, upsert=True
    )
    if not consent:  # opting out deletes the answers already given
        mongo.col("pulse_answers").delete_many({"tenant_id": tid, "employee_id": employee_id})
    tenants.audit(tid, employee_id, "pulse.consent", "yes" if consent else "no (answers deleted)")
    return pulse_status(tid, employee_id, now)


def answer_pulse(tid: str, employee_id: str, answer: str, now: datetime | None = None) -> dict:
    if answer not in PULSE_ANSWERS:
        raise Invalid("Answer good, ok or hard.")
    c = mongo.col("pulse_consent").find_one({"tenant_id": tid, "employee_id": employee_id}) or {}
    if not c.get("consent"):
        raise Invalid("Say yes to the weekly question first.")
    week = _monday(_local_today(now)).isoformat()
    mongo.col("pulse_answers").update_one(
        {"tenant_id": tid, "employee_id": employee_id, "week_start": week}, {"$set": {"answer": answer, "at": mongo.now()}}, upsert=True
    )
    return pulse_status(tid, employee_id, now)


# ------------------------------------------------------------------ weekly records
def _shift_span(day: date, shift: str, wins: dict[str, tuple[int, int]], hours: float) -> tuple[datetime, datetime]:
    start_min, length = wins.get(shift, (9 * 60, int(hours * 60)))
    start = datetime(day.year, day.month, day.day, tzinfo=worklog.local_tz()) + timedelta(minutes=start_min)
    return start, start + timedelta(minutes=length)


def _rec(out: dict, emp: str, week: date) -> dict:
    return out.setdefault(
        (emp, week),
        {
            "employee_id": emp,
            "week_start": week.isoformat(),
            "roster_published": False,
            "worked_days": set(),
            "shift_hours": 0.0,
            "night_shifts": 0,
            "short_rest": 0,
            "late_finish_minutes": None,
            "leave_days": set(),
            "jobs_offered": 0,
            "jobs_declined": 0,
            "jobs_timed_out": 0,
            "jobs_done": 0,
            "jobs_on_time": 0,
            "team_jobs_done": 0,
            "_responses": [],
            "recognition_points": None,
            "checkins": 0,
            "pulse": None,
        },
    )


def weekly_signals(
    tid: str,
    weeks: int = DEFAULT_WEEKS,
    include_current: bool = False,
    department: str | None = None,
    include_pay: bool = True,
    property_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Per staff member and week: the facts above, in the shape ml/attrition/live_signals.LiveSignals reads.
    include_pay False (department heads): pay and the weekly answers are left out (owner / HR only)."""
    weeks = max(1, min(int(weeks), MAX_WEEKS))
    this_monday = _monday(_local_today(now))
    last = this_monday if include_current else this_monday - timedelta(days=7)
    first = last - timedelta(days=7 * (weeks - 1))
    week_list = [first + timedelta(days=7 * i) for i in range(weeks)]
    tz = worklog.local_tz()
    t0 = datetime(first.year, first.month, first.day, tzinfo=tz).astimezone(UTC)
    t1 = (datetime(last.year, last.month, last.day, tzinfo=tz) + timedelta(days=7)).astimezone(UTC)

    prop = tenants.get_property(tid, property_id) if property_id else None
    pmap = tenants.staff_property_map(tid) if prop else {}
    staff = [
        s
        for s in tenants.staff(tid)
        if (not department or s["department"] == department) and (not prop or pmap.get(s["employee_id"]) == prop["id"])
    ]
    dept = {s["employee_id"]: s["department"] for s in staff}
    hr = {r["employee_id"]: r for r in hr_records(tid) if r["employee_id"] in dept}
    out: dict = {}

    def in_window(d: date | None) -> bool:
        return d is not None and first <= d < last + timedelta(days=7)

    # roster: planned shifts per day, nights, short rests, hours
    wins = shifts.windows(dispatch._settings(tid))
    spans: dict[str, list[tuple[datetime, datetime]]] = {}
    shift_of: dict[tuple[str, date], list[tuple[datetime, datetime]]] = {}
    published = set()
    for snap in mongo.col("roster_history").find(
        {"tenant_id": tid, "week_start": {"$gte": first.isoformat(), "$lte": last.isoformat()}}, {"_id": 0}
    ):
        ws = date.fromisoformat(snap["week_start"])
        published.add(ws)
        for e in dept:
            _rec(out, e, ws)["roster_published"] = True
        for a in snap.get("assignments") or []:
            e = a.get("employee_id")
            try:
                d = date.fromisoformat(str(a.get("date")))
            except ValueError:
                continue
            if e not in dept or _monday(d) != ws:
                continue
            r = _rec(out, e, ws)
            hours = float(a.get("hours") or 8)
            r["worked_days"].add(d.weekday())
            r["shift_hours"] += hours
            r["night_shifts"] += a.get("shift") == "night"
            span = _shift_span(d, str(a.get("shift")), wins, hours)
            spans.setdefault(e, []).append(span)
            shift_of.setdefault((e, d), []).append(span)
    for e, ss in spans.items():
        ss.sort()
        for (_, end_a), (start_b, _) in zip(ss, ss[1:], strict=False):
            if (start_b - end_a) < timedelta(hours=MIN_REST_HOURS):
                _rec(out, e, _monday(start_b.date()))["short_rest"] += 1

    # jobs: finished, on time, finishes after the shift end, offers answered
    late: dict[tuple[str, date], float] = {}
    team: dict[tuple[str, date], int] = {}
    span = {"$gte": t0, "$lt": t1}
    for j in mongo.col("jobs").find({"tenant_id": tid, "$or": [{"created_at": span}, {"done_at": span}]}, {"_id": 0}):
        emp = j.get("assigned_to")
        dd = _local_date(j.get("done_at")) if j.get("status") == "done" else None
        if emp in dept and in_window(dd):
            r = _rec(out, emp, _monday(dd))
            r["jobs_done"] += 1
            m = performance._minutes(j.get("accepted_at"), j.get("done_at"))
            r["jobs_on_time"] += m is not None and m <= performance._target(j)
            team[(dept[emp], _monday(dd))] = team.get((dept[emp], _monday(dd)), 0) + 1
            done = performance._aware(j["done_at"])
            cands = [s for k in (dd, dd - timedelta(days=1)) for s in shift_of.get((emp, k), []) if s[0] <= done]
            if cands:
                over = (done - max(cands)[1]).total_seconds() / 60
                if over > 0:
                    late[(emp, dd)] = max(late.get((emp, dd), 0.0), over)
        for a in j.get("attempts") or []:
            e, outcome = a.get("employee_id"), a.get("outcome")
            ad = _local_date(a.get("at"))
            if e not in dept or outcome not in ("accepted", "declined", "timeout") or not in_window(ad):
                continue
            r = _rec(out, e, _monday(ad))
            r["jobs_offered"] += 1
            r["jobs_declined"] += outcome == "declined"
            r["jobs_timed_out"] += outcome == "timeout"
            if outcome == "accepted":
                s = performance._minutes(a.get("offered_at"), a.get("at"))
                if s is not None:
                    r["_responses"].append(s * 60)
    for (e, d), m in late.items():
        r = _rec(out, e, _monday(d))
        r["late_finish_minutes"] = round((r["late_finish_minutes"] or 0) + m, 1)

    # leave / absence marks, consented weekly answers
    for m in mongo.col("staff_leave").find(
        {"tenant_id": tid, "date": {"$gte": first.isoformat(), "$lt": (last + timedelta(days=7)).isoformat()}}, {"_id": 0}
    ):
        if m["employee_id"] in dept:
            d = date.fromisoformat(m["date"])
            _rec(out, m["employee_id"], _monday(d))["leave_days"].add(d.weekday())
    consented = {
        c["employee_id"] for c in mongo.col("pulse_consent").find({"tenant_id": tid, "consent": True}, {"employee_id": 1})
    }
    for a in mongo.col("pulse_answers").find(
        {"tenant_id": tid, "week_start": {"$gte": first.isoformat(), "$lte": last.isoformat()}}, {"_id": 0}
    ):
        if include_pay and a["employee_id"] in dept and a["employee_id"] in consented:  # owner / HR only
            _rec(out, a["employee_id"], date.fromisoformat(a["week_start"]))["pulse"] = a.get("answer")

    # thank-you points per week (only for weeks the person already has a record)
    if out:
        rprop = prop or tenants.get_property(tid, None)
        cfg = recognition.settings_for(rprop)
        members = {e: d for e, d in dept.items() if d not in recognition.NOT_COUNTED_DEPARTMENTS}
        for ws in week_list:
            s0 = datetime(ws.year, ws.month, ws.day, tzinfo=tz).astimezone(UTC)
            facts = recognition._facts(tid, members, s0, s0 + timedelta(days=7), cfg)
            for e, f in facts.items():
                if (e, ws) in out:
                    out[(e, ws)]["recognition_points"] = sum(f[k] * cfg["weights"][k] for k in cfg["weights"])

    # drop weeks after someone left / before they joined; finish the records
    records = []
    for (e, ws), r in sorted(out.items(), key=lambda x: (x[0][0], x[0][1])):
        h = hr.get(e, {})
        if h.get("left_on") and date.fromisoformat(h["left_on"]) <= ws:
            continue
        if h.get("joining_date") and date.fromisoformat(h["joining_date"]) >= ws + timedelta(days=7):
            continue
        resp = sorted(r.pop("_responses"))
        r["median_response_seconds"] = round(resp[len(resp) // 2], 1) if resp else None
        r["team_jobs_done"] = team.get((dept[e], ws), 0)
        r["worked_days"], r["leave_days"] = sorted(r["worked_days"]), sorted(r["leave_days"])
        records.append(r)

    profiles = []
    for s in staff:
        e = s["employee_id"]
        h = hr.get(e, {})
        p = {
            "employee_id": e,
            "department": s["department"],
            "role_title": s.get("role_title") or "",
            "contract_type": s.get("contract_type") if s.get("contract_type") in ("permanent", "seasonal") else "permanent",
            "role": h.get("role"),
            **{k: h.get(k) for k in HR_DATES},
        }
        if include_pay:
            p.update({k: h.get(k) for k in PAY_FIELDS})
        else:
            p["pay_withheld"] = True
        profiles.append(p)
    t = tenants.get_tenant(tid)
    return {
        "weeks": [w.isoformat() for w in week_list],
        "week_start": last.isoformat(),
        "roster_weeks": sorted(w.isoformat() for w in published),
        "profiles": profiles,
        "records": records,
        "leave_marks_used": mongo.col("staff_leave").find_one({"tenant_id": tid}, {"_id": 1}) is not None,
        "festival_dates": None,
        "note": NOTE,
        "synthetic": bool(t.get("is_demo")),
    }
