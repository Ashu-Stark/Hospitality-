"""Work log: one day's dispatch jobs with their timings and photo proof. SYNTHETIC demo data, employee ids only.

A job belongs to a day (hotel local time, config.hotel_utc_offset_minutes, default IST) when it was created, started or
finished that day. Times come from the job's own stamps (server clock), so they show when the work happened in the app,
not attendance: there is no clock-in / clock-out.

Minutes per job (None when a stamp is missing):
  wait      created  -> accepted   how long the request waited for someone to take it
  response  offered  -> accepted   the accepted offer only (the person who did the job)
  work      started  -> done       time on the job itself
  total     created  -> done
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median

from .. import config, mongo
from .performance import _aware, _minutes

FIELDS = ("id", "title", "kind", "room", "department", "assigned_to", "status", "created_at", "accepted_at", "started_at", "done_at")
NOTE = "Times are the app's job stamps (server clock), not attendance. SYNTHETIC demo data."


def local_tz() -> timezone:
    return timezone(timedelta(minutes=config.settings.hotel_utc_offset_minutes))


def today() -> str:
    return datetime.now(local_tz()).date().isoformat()


def _bounds(day: str) -> tuple[datetime, datetime]:
    d = date.fromisoformat(day)
    start = datetime(d.year, d.month, d.day, tzinfo=local_tz())
    return start, start + timedelta(days=1)


def _r(v: float | None) -> float | None:
    return round(v, 1) if v is not None else None


def _response(job: dict) -> float | None:
    """Offer -> accept for the accepted offer (the attempt of the person who took the job)."""
    for a in reversed(job.get("attempts") or []):
        if a.get("outcome") == "accepted" and a.get("employee_id") == job.get("assigned_to"):
            return _minutes(a.get("offered_at"), a.get("at"))
    return None


def _row(job: dict, pics: dict[str, str]) -> dict:
    out = {k: job.get(k) for k in FIELDS}
    for k in ("created_at", "accepted_at", "started_at", "done_at"):
        v = _aware(job.get(k))
        out[k] = v.astimezone(local_tz()).isoformat() if v else None  # hotel local time with its offset
    out["minutes"] = {
        "wait": _r(_minutes(job.get("created_at"), job.get("accepted_at"))),
        "response": _r(_response(job)),
        "work": _r(_minutes(job.get("started_at"), job.get("done_at"))),
        "total": _r(_minutes(job.get("created_at"), job.get("done_at"))),
    }
    out["photos"] = {"before": pics.get("before"), "after": pics.get("after")}
    return out


def _photos(tid: str, ids: list[str]) -> dict[str, dict[str, str]]:
    """job id -> {kind: latest photo id}."""
    out: dict[str, dict[str, str]] = {}
    if not ids:
        return out
    rows = (
        mongo.col("photos")
        .find({"tenant_id": tid, "job_id": {"$in": ids}}, {"id": 1, "job_id": 1, "kind": 1})
        .sort([("server_ts", 1), ("_id", 1)])
    )
    for p in rows:
        out.setdefault(p["job_id"], {})[p["kind"]] = p["id"]
    return out


def _people(rows: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for r in rows:
        if r["assigned_to"]:
            by.setdefault(r["assigned_to"], []).append(r)
    out = []
    for emp, jobs in by.items():
        done = [j for j in jobs if j["status"] == "done"]
        work = [j["minutes"]["work"] for j in done if j["minutes"]["work"] is not None]
        depts = [j["department"] for j in jobs if j["department"]]
        out.append(
            {
                "employee_id": emp,
                "department": max(set(depts), key=depts.count) if depts else None,
                "jobs": len(jobs),
                "jobs_done": len(done),
                "total_work_minutes": _r(sum(work)) if work else 0,
                "median_work_minutes": _r(median(work)) if work else None,
                "jobs_with_photos": sum(1 for j in done if j["photos"]["before"] or j["photos"]["after"]),
            }
        )
    out.sort(key=lambda p: (-p["jobs_done"], p["employee_id"]))
    return out


def _totals(rows: list[dict]) -> dict:
    done = [r for r in rows if r["status"] == "done"]
    work = [r["minutes"]["work"] for r in done if r["minutes"]["work"] is not None]
    waits = [r for r in rows if r["minutes"]["wait"] is not None]
    longest = max(waits, key=lambda r: r["minutes"]["wait"]) if waits else None
    return {
        "jobs": len(rows),
        "jobs_done": len(done),
        "total_work_minutes": _r(sum(work)) if work else 0,
        "avg_work_minutes": _r(sum(work) / len(work)) if work else None,
        "median_work_minutes": _r(median(work)) if work else None,
        "jobs_with_photos": sum(1 for r in done if r["photos"]["before"] or r["photos"]["after"]),
        "longest_wait_minutes": longest["minutes"]["wait"] if longest else None,
        "longest_wait_job": longest["id"] if longest else None,
    }


def compute(tid: str, day: str | None = None, employee_id: str | None = None, department: str | None = None) -> dict:
    day = day or today()
    start, end = _bounds(day)
    span = {"$gte": start, "$lt": end}
    flt: dict = {"tenant_id": tid, "$or": [{"created_at": span}, {"started_at": span}, {"done_at": span}]}
    if department:
        flt["department"] = department
    if employee_id:
        flt["assigned_to"] = employee_id
    jobs = list(mongo.col("jobs").find(flt, {"_id": 0}).sort([("created_at", 1), ("id", 1)]))
    pics = _photos(tid, [j["id"] for j in jobs])
    rows = [_row(j, pics.get(j["id"], {})) for j in jobs]
    return {
        "date": day,
        "timezone_offset_minutes": config.settings.hotel_utc_offset_minutes,
        "employee_id": employee_id,
        "department": department,
        "summary": _totals(rows),
        "people": _people(rows),
        "jobs": rows,
        "note": NOTE,
        "synthetic": True,
    }
