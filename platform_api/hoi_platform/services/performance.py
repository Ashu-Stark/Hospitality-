"""Performance score per worker (technical plan section 4.1), computed from dispatch jobs. SYNTHETIC demo data.

A COACHING AID compared with each person's OWN previous period; not for disciplinary use. It never uses or returns
attrition risk bands, and it uses no personal attributes: workers are employee ids only.

Period: the last `days` days (default 14) ending now. Baseline: the `days` days before that, scored the same way.

Components (each 0..1; definitions and thresholds are ASSUMED starting points to tune with real operations data):
  on_time         35%  share of completed jobs finished (accepted_at -> done_at) within the job's target time:
                       job["target_minutes"] when present, else by urgency: high 30, medium 60, low 120 min (ASSUMED).
                       Measured from acceptance, so dispatch delays before the worker said yes do not count against them.
  speed           20%  department median work time / the worker's median work time (started_at -> done_at), capped at 1:
                       at or faster than the department median = full marks, so rushing is not rewarded beyond it.
                       The department median uses every worker's completed jobs in the same period and department.
  quality         25%  inspection pass rate on the worker's inspected cleaning jobs (room inspection pass vs re-clean).
                       Left out when the worker has no inspected cleaning job; the other weights are re-normalised.
  responsiveness  10%  median seconds from offer to accept: <= 10 s full marks, falling linearly to 0 at the tenant's
                       offer window (default 30 s) (ASSUMED).
  reliability     10%  1 - (declines + timeouts) / offers answered (accepted + declined + timed out).

Score = 100 x sum(weight x component) / sum(weights of the components available). Fewer than MIN_JOBS (5) completed
jobs in the period -> status "insufficient_data" with a reason and no score (components still shown for context).
Reasons are plain-language sentences, largest change vs the person's own baseline first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import median

from .. import mongo
from . import dispatch

WEIGHTS = {"on_time": 0.35, "speed": 0.20, "quality": 0.25, "responsiveness": 0.10, "reliability": 0.10}
MIN_JOBS = 5
TARGET_MINUTES = {"urgent": 15, "high": 30, "medium": 60, "low": 120}  # ASSUMED, accept -> done
FAST_ACCEPT_S = 10  # ASSUMED: accepting within 10 s earns full responsiveness
LABELS = {
    "on_time": "On time",
    "speed": "Speed",
    "quality": "Quality",
    "responsiveness": "Responsiveness",
    "reliability": "Reliability",
}
NOTE = "A coaching aid compared with each person's own baseline; not for disciplinary use. SYNTHETIC demo data."


def _aware(dt) -> datetime | None:  # noqa: ANN001
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt).astimezone(UTC)
    return dt.replace(tzinfo=UTC) if isinstance(dt, datetime) and dt.tzinfo is None else dt


def _minutes(a, b) -> float | None:  # noqa: ANN001
    a, b = _aware(a), _aware(b)
    return (b - a).total_seconds() / 60 if a and b else None


def _in(dt, start: datetime, end: datetime) -> bool:  # noqa: ANN001
    """Periods are (start, end]: something that happened exactly `now` belongs to the current period."""
    dt = _aware(dt)
    return dt is not None and start < dt <= end


def _target(job: dict) -> float:
    return float(job.get("target_minutes") or TARGET_MINUTES.get(job.get("urgency") or "medium", 60))


def _period(jobs: list[dict], start: datetime, end: datetime) -> dict[str, dict]:
    """Raw facts per worker for one period: completed jobs, work times, inspections, offers."""
    out: dict[str, dict] = {}

    def w(emp: str) -> dict:
        return out.setdefault(emp, {"done": [], "offers": [], "depts": {}})

    for j in jobs:
        if j.get("status") == "done" and j.get("assigned_to") and _in(j.get("done_at"), start, end):
            r = w(j["assigned_to"])
            r["done"].append(j)
            r["depts"][j["department"]] = r["depts"].get(j["department"], 0) + 1
        for a in j.get("attempts") or []:
            if a.get("outcome") in ("accepted", "declined", "timeout") and _in(a.get("offered_at"), start, end):
                w(a["employee_id"])["offers"].append({**a, "department": j.get("department")})
    return out


def _dept_medians(facts: dict[str, dict]) -> dict[str, float]:
    by: dict[str, list[float]] = {}
    for f in facts.values():
        for j in f["done"]:
            m = _minutes(j.get("started_at"), j.get("done_at"))
            if m is not None:
                by.setdefault(j["department"], []).append(m)
    return {d: median(v) for d, v in by.items() if v}


def _components(f: dict, dept: str | None, dept_median: dict[str, float], offer_s: int) -> dict[str, dict]:
    """Each component: value 0..1 (None = not available) plus the numbers behind it."""
    done = f["done"]
    c: dict[str, dict] = {}
    timed = [(j, _minutes(j.get("accepted_at"), j.get("done_at"))) for j in done]
    timed = [(j, m) for j, m in timed if m is not None]
    on = sum(1 for j, m in timed if m <= _target(j))
    c["on_time"] = {"value": on / len(timed) if timed else None, "on_time": on, "jobs": len(timed)}

    work = [m for m in (_minutes(j.get("started_at"), j.get("done_at")) for j in done) if m is not None]
    own = median(work) if work else None
    ref = dept_median.get(dept or "")
    val = None
    if own is not None and ref is not None:
        val = 1.0 if own <= 0 else min(1.0, ref / own)
    c["speed"] = {
        "value": val,
        "median_minutes": round(own, 1) if own is not None else None,
        "department_median_minutes": round(ref, 1) if ref is not None else None,
    }

    insp = [j for j in done if j.get("kind") == "cleaning" and j.get("inspection") in ("pass", "fail")]
    passed = sum(1 for j in insp if j["inspection"] == "pass")
    c["quality"] = {"value": passed / len(insp) if insp else None, "passed": passed, "inspected": len(insp)}

    waits = [
        (_aware(a.get("at")) - _aware(a.get("offered_at"))).total_seconds()
        for a in f["offers"]
        if a.get("outcome") == "accepted" and a.get("at") and a.get("offered_at")
    ]
    secs = median(waits) if waits else None
    val = None
    if secs is not None:
        span = max(1, offer_s - FAST_ACCEPT_S)
        val = max(0.0, min(1.0, 1 - (secs - FAST_ACCEPT_S) / span))
    c["responsiveness"] = {"value": val, "median_seconds_to_accept": round(secs, 1) if secs is not None else None}

    offers = f["offers"]
    dec = sum(1 for a in offers if a["outcome"] == "declined")
    tout = sum(1 for a in offers if a["outcome"] == "timeout")
    c["reliability"] = {
        "value": 1 - (dec + tout) / len(offers) if offers else None,
        "offers": len(offers),
        "declined": dec,
        "timed_out": tout,
    }
    for k, v in c.items():
        v["weight"] = WEIGHTS[k]
        if v["value"] is not None:
            v["value"] = round(v["value"], 4)
    return c


def _score(comp: dict[str, dict]) -> tuple[float | None, dict[str, float]]:
    avail = {k: v for k, v in comp.items() if v["value"] is not None}
    total = sum(WEIGHTS[k] for k in avail)
    if not total:
        return None, {}
    used = {k: round(WEIGHTS[k] / total, 4) for k in avail}
    return round(100 * sum(used[k] * avail[k]["value"] for k in avail), 1), used


def _fact(k: str, c: dict) -> str:
    """One plain-language sentence for a component."""
    if k == "on_time":
        return f"{c['on_time']} of {c['jobs']} jobs finished within the target time"
    if k == "speed":
        return f"median job time {c['median_minutes']} min vs department median {c['department_median_minutes']} min"
    if k == "quality":
        fails = c["inspected"] - c["passed"]
        return f"{c['passed']} of {c['inspected']} inspected rooms passed first time" + (f" ({fails} needed a re-clean)" if fails else "")
    if k == "responsiveness":
        return f"median {c['median_seconds_to_accept']} s to accept an offer"
    return f"{c['declined']} declined and {c['timed_out']} timed-out of {c['offers']} offers"


def _reasons(comp: dict[str, dict], base: dict[str, dict] | None, limit: int = 3) -> list[str]:
    """Plain-language reasons: changes vs the person's own baseline first (largest weighted change), then parts with no
    baseline (weakest first), then parts that did not change."""
    rows = []
    for k, c in comp.items():
        if c["value"] is None:
            continue
        b = (base or {}).get(k, {}).get("value")
        if b is not None:
            d = c["value"] - b
            trend = "up from" if d > 0.005 else "down from" if d < -0.005 else "about the same as"
            text = f"{LABELS[k]}: {_fact(k, c)}; {trend} {round(b * 100)}% in the previous period."
            rows.append((2 + abs(d) * WEIGHTS[k] if abs(d) > 0.005 else 0, text))
        else:
            text = f"{LABELS[k]}: {_fact(k, c)} ({round(c['value'] * 100)}%)."
            rows.append((1 + (1 - c["value"]) * WEIGHTS[k], text))
    if comp["quality"]["value"] is None:
        rows.append((0.5, "Quality: no inspected cleaning jobs in this period, so its weight is shared across the other parts."))
    return [t for _, t in sorted(rows, key=lambda r: -r[0])[:limit]]


def _worker(emp: str, cur: dict, prev: dict | None, med_now: dict, med_prev: dict, offer_s: int) -> dict:
    depts = cur["depts"] or (prev or {}).get("depts") or {}
    if not depts:
        depts = {o["department"]: 1 for o in cur["offers"] if o.get("department")}
    dept = max(depts, key=depts.get) if depts else None
    comp = _components(cur, dept, med_now, offer_s)
    n = len(cur["done"])
    base_comp, base_score = None, None
    if prev and len(prev["done"]) >= MIN_JOBS:
        base_comp = _components(prev, dept, med_prev, offer_s)
        base_score, _ = _score(base_comp)
    out = {
        "employee_id": emp,
        "department": dept,
        "completed_jobs": n,
        "components": comp,
        "baseline_score": base_score,
    }
    if n < MIN_JOBS:
        return {
            **out,
            "status": "insufficient_data",
            "score": None,
            "delta": None,
            "weights_used": {},
            "reasons": [f"Only {n} completed job{'s' if n != 1 else ''} in this period; at least {MIN_JOBS} are needed for a fair score."],
        }
    score, used = _score(comp)
    reasons = _reasons(comp, base_comp)
    if base_score is None:
        reasons.append(f"No baseline yet: fewer than {MIN_JOBS} completed jobs in the previous period.")
    return {
        **out,
        "status": "ok",
        "score": score,
        "delta": round(score - base_score, 1) if score is not None and base_score is not None else None,
        "weights_used": used,
        "reasons": reasons,
    }


def compute(tid: str, days: int = 14, department: str | None = None, worker: str | None = None, now: datetime | None = None) -> dict:
    """Scores for every worker with jobs or offers in the period (optionally one department or one worker)."""
    dispatch.sweep(tid)  # settle expired offers first, so timeouts count
    now = _aware(now) or mongo.now()
    start, prev_start = now - timedelta(days=days), now - timedelta(days=2 * days)
    # offers happen after creation, completions are found by done_at: together they cover both periods
    flt: dict = {"tenant_id": tid, "$or": [{"created_at": {"$gte": prev_start}}, {"done_at": {"$gte": prev_start}}]}
    jobs = list(mongo.col("jobs").find(flt, {"_id": 0}))
    offer_s = dispatch.offer_seconds(tid)
    cur, prev = _period(jobs, start, now), _period(jobs, prev_start, start)
    med_now, med_prev = _dept_medians(cur), _dept_medians(prev)
    if department:  # scope after the medians: a department's median only uses its own jobs anyway
        jobs_in = {e for e, f in cur.items() if department in f["depts"] or any(o.get("department") == department for o in f["offers"])}
        cur = {e: f for e, f in cur.items() if e in jobs_in}
        for f in cur.values():
            f["done"] = [j for j in f["done"] if j["department"] == department]
            f["offers"] = [o for o in f["offers"] if o.get("department") == department]
            f["depts"] = {department: len(f["done"])} if f["done"] else {}
        for f in prev.values():
            f["done"] = [j for j in f["done"] if j["department"] == department]
            f["offers"] = [o for o in f["offers"] if o.get("department") == department]
            f["depts"] = {department: len(f["done"])} if f["done"] else {}
    if worker:
        cur = {worker: cur.get(worker) or {"done": [], "offers": [], "depts": {}}}
    rows = [_worker(e, f, prev.get(e), med_now, med_prev, offer_s) for e, f in cur.items()]
    rows.sort(key=lambda r: (r["status"] != "ok", -(r["score"] or 0), r["employee_id"]))
    return {
        "period": {"from": mongo.iso(start), "to": mongo.iso(now), "days": days},
        "baseline_period": {"from": mongo.iso(prev_start), "to": mongo.iso(start)},
        "weights": WEIGHTS,
        "min_jobs": MIN_JOBS,
        "targets_minutes": TARGET_MINUTES,
        "department": department,
        "workers": rows,
        "note": NOTE,
        "synthetic": True,
    }
