"""Worker recognition points: a positive-only incentive scheme per property and month. SYNTHETIC demo data.

Points are EARNED, never taken away, and are never used for discipline (stated in every response and in the apps).
They come from finished dispatch jobs only; no attrition risk bands and no personal attributes are used (employee ids only).

Ways to earn (ASSUMED default weights; the owner can change them per property, all must be >= 0):
  on_time_job          10  a finished job, accepted -> done within its target time (same targets as services/performance.py)
  after_photo           2  the finished job has its after photo (proof of work)
  inspection_pass       5  a cleaning job whose room passed inspection first time
  guest_feedback_good   5  a guest rated the stay >= 4 within 72 h after a guest request this worker finished in that room

Fairness safeguards (ASSUMED defaults, configurable per property):
  - no negative points: only the events above add points; nothing subtracts
  - max_points_per_worker (400 / month): points above the cap are not counted, so nobody is pushed to overwork
  - min_jobs (5 finished jobs in the month) before a reward share is estimated; points still show below it
  - max_share (25 %): one person's reward is at most this share of the budget
  - the reward pool is the property's monthly incentive budget cap (onboarding's `incentive_monthly_budget_cap`);
    estimate = points share x budget, capped; what is not allocated stays with the owner (nothing is redistributed)
  - visibility: a worker sees only their own points plus team totals. Owners/HR/department heads see per-person rows
    (needed to pay rewards), listed by employee id, not ranked. A ranked leaderboard exists only if the owner opts in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .. import config, mongo
from . import performance, tenants
from .errors import Invalid

DEFAULTS = {
    "weights": {"on_time_job": 10, "after_photo": 2, "inspection_pass": 5, "guest_feedback_good": 5},
    "max_points_per_worker": 400,
    "min_jobs": 5,
    "max_share": 0.25,
    "good_feedback_min": 4,
    "feedback_window_hours": 72,
}
ROUND_TO_INR = 10
LABELS = {
    "on_time_job": "Job finished on time",
    "after_photo": "After photo added",
    "inspection_pass": "Room passed inspection first time",
    "guest_feedback_good": "Guest rated the stay 4 or 5 stars after your request",
}
HOW_TO_EARN = [
    "Finish a job within its target time.",
    "Add the after photo when you finish.",
    "Clean so the room passes inspection the first time.",
    "Serve guest requests well: a 4 or 5 star rating adds points.",
]
NOT_COUNTED_DEPARTMENTS = {"management"}  # the manager / owner side is not part of the staff scheme
NOTE = (
    "Recognition only: points are earned, never taken away, and are never used for discipline or pay deductions. "
    "Rewards are an estimate until the owner confirms them. SYNTHETIC demo data."
)


def settings_for(prop: dict) -> dict:
    """Defaults merged with the property's own `recognition` settings (only known keys, never negative)."""
    own = prop.get("recognition") or {}
    w = {k: max(0, int((own.get("weights") or {}).get(k, v))) for k, v in DEFAULTS["weights"].items()}
    return {
        "weights": w,
        "max_points_per_worker": max(1, int(own.get("max_points_per_worker", DEFAULTS["max_points_per_worker"]))),
        "min_jobs": max(0, int(own.get("min_jobs", DEFAULTS["min_jobs"]))),
        "max_share": min(1.0, max(0.01, float(own.get("max_share", DEFAULTS["max_share"])))),
        "good_feedback_min": DEFAULTS["good_feedback_min"],
        "feedback_window_hours": DEFAULTS["feedback_window_hours"],
    }


def validate_config(cfg: dict) -> dict:
    """Owner input -> stored `recognition` settings. Rejects negative weights (points are positive only)."""
    out: dict = {}
    if "weights" in cfg and cfg["weights"] is not None:
        bad = [k for k in cfg["weights"] if k not in DEFAULTS["weights"]]
        if bad:
            raise Invalid(f"Unknown way to earn points: {bad[0]}")
        if any(int(v) < 0 for v in cfg["weights"].values()):
            raise Invalid("Points are positive only: weights cannot be negative.")
        out["weights"] = {k: int(v) for k, v in cfg["weights"].items()}
    for k in ("max_points_per_worker", "min_jobs"):
        if cfg.get(k) is not None:
            if int(cfg[k]) < 0:
                raise Invalid(f"{k} cannot be negative.")
            out[k] = int(cfg[k])
    if cfg.get("max_share") is not None:
        if not 0 < float(cfg["max_share"]) <= 1:
            raise Invalid("max_share must be above 0 and at most 1.")
        out["max_share"] = float(cfg["max_share"])
    return out


def _aware(dt) -> datetime | None:  # noqa: ANN001
    return performance._aware(dt)


def month_window(month: str | None, now: datetime | None = None) -> tuple[str, datetime, datetime]:
    """(YYYY-MM, start, end) in UTC for the hotel's local calendar month (HOI_HOTEL_UTC_OFFSET_MINUTES)."""
    off = timedelta(minutes=config.settings.hotel_utc_offset_minutes)
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            local = datetime(y, m, 1)
        except ValueError:
            raise Invalid("Month must look like 2026-10.") from None
    else:
        n = (_aware(now) or datetime.now(UTC)) + off
        local = datetime(n.year, n.month, 1)
    nxt = datetime(local.year + (local.month == 12), local.month % 12 + 1, 1)
    return f"{local.year:04d}-{local.month:02d}", (local - off).replace(tzinfo=UTC), (nxt - off).replace(tzinfo=UTC)


def _members(tid: str, prop: dict, first_id: str) -> dict[str, str]:
    return {
        s["employee_id"]: s["department"]
        for s in tenants.staff(tid)
        if (s.get("property_id") or first_id) == prop["id"] and s["department"] not in NOT_COUNTED_DEPARTMENTS
    }


def _facts(tid: str, members: dict[str, str], start: datetime, end: datetime, cfg: dict) -> dict[str, dict]:
    """Per member: counts of each way to earn in the month."""
    out = {e: {"jobs_done": 0, **dict.fromkeys(DEFAULTS["weights"], 0)} for e in members}
    jobs = [
        j
        for j in mongo.col("jobs").find(
            {"tenant_id": tid, "status": "done", "assigned_to": {"$in": list(members)}, "done_at": {"$gte": start, "$lt": end}},
            {"_id": 0},
        )
    ]
    ids = [j["id"] for j in jobs]
    with_after = {p["job_id"] for p in mongo.col("photos").find({"tenant_id": tid, "job_id": {"$in": ids}, "kind": "after"}, {"job_id": 1})}
    for j in jobs:
        f = out[j["assigned_to"]]
        f["jobs_done"] += 1
        m = performance._minutes(j.get("accepted_at"), j.get("done_at"))
        if m is not None and m <= performance._target(j):
            f["on_time_job"] += 1
        if j["id"] in with_after:
            f["after_photo"] += 1
        if j.get("kind") == "cleaning" and j.get("inspection") == "pass":
            f["inspection_pass"] += 1
    # guest feedback >= 4 credits the workers who finished a guest request in that room shortly before
    window = timedelta(hours=cfg["feedback_window_hours"])
    good = mongo.col("guest_feedback").find(
        {"tenant_id": tid, "rating": {"$gte": cfg["good_feedback_min"]}, "created_at": {"$gte": start, "$lt": end}},
        {"room_id": 1, "created_at": 1},
    )
    for fb in good:
        at = _aware(fb["created_at"])
        served = mongo.col("jobs").find(
            {
                "tenant_id": tid,
                "room_id": fb.get("room_id"),
                "kind": "guest",
                "status": "done",
                "assigned_to": {"$in": list(members)},
                "done_at": {"$gte": at - window, "$lte": at},
            },
            {"assigned_to": 1},
        )
        for emp in {j["assigned_to"] for j in served}:  # once per feedback and worker
            out[emp]["guest_feedback_good"] += 1
    return out


def _breakdown(f: dict, w: dict) -> list[dict]:
    return [{"key": k, "label": LABELS[k], "count": f[k], "points_each": w[k], "points": f[k] * w[k]} for k in DEFAULTS["weights"]]


def compute(tid: str, property_id: str | None = None, month: str | None = None, now: datetime | None = None) -> dict:
    """Points, caps and the reward estimate for every counted staff member of one property in one month."""
    prop = tenants.get_property(tid, property_id)
    first = tenants.properties(tid)[0]["id"]
    cfg = settings_for(prop)
    label, start, end = month_window(month, now)
    members = _members(tid, prop, first)
    facts = _facts(tid, members, start, end, cfg)
    w, cap = cfg["weights"], cfg["max_points_per_worker"]
    rows = []
    for emp, f in facts.items():
        raw = sum(f[k] * w[k] for k in w)  # every term is >= 0: points can never be negative
        pts = min(raw, cap)
        rows.append(
            {
                "employee_id": emp,
                "department": members[emp],
                "points": pts,
                "raw_points": raw,
                "capped": raw > cap,
                "jobs_done": f["jobs_done"],
                "eligible": f["jobs_done"] >= cfg["min_jobs"],
                "breakdown": _breakdown(f, w),
            }
        )
    budget = int(prop.get("incentive_monthly_budget_cap") or 0)
    pool = sum(r["points"] for r in rows if r["eligible"])
    for r in rows:
        share = r["points"] / pool if r["eligible"] and pool else 0.0
        est = min(share, cfg["max_share"]) * budget
        r["share"] = round(share, 4)
        r["estimated_reward_inr"] = int(est // ROUND_TO_INR * ROUND_TO_INR)
    rows.sort(key=lambda r: r["employee_id"])  # listed by id, never ranked
    allocated = sum(r["estimated_reward_inr"] for r in rows)
    earning = [r for r in rows if r["points"] > 0]
    team = {
        "members": len(rows),
        "people_with_points": len(earning),
        "eligible": sum(1 for r in rows if r["eligible"]),
        "total_points": sum(r["points"] for r in rows),
        "average_points": round(sum(r["points"] for r in rows) / len(rows), 1) if rows else 0,
        "jobs_done": sum(r["jobs_done"] for r in rows),
    }
    out = {
        "month": label,
        "period": {"from": mongo.iso(start), "to": mongo.iso(end)},
        "property": {"id": prop["id"], "name": prop["name"], "mode": prop["mode"]},
        "config": cfg,
        "how_to_earn": HOW_TO_EARN,
        "budget_inr": budget,
        "budget_set": budget > 0,
        "allocated_inr": allocated,
        "unallocated_inr": max(0, budget - allocated),
        "team": team,
        "workers": rows,
        "leaderboard_opt_in": bool(prop.get("recognition_leaderboard_opt_in")),
        "note": NOTE,
        "synthetic": True,
    }
    if out["leaderboard_opt_in"]:
        top = sorted(earning, key=lambda r: (-r["points"], r["employee_id"]))[:5]
        out["leaderboard"] = [{"employee_id": r["employee_id"], "points": r["points"]} for r in top]
    return out


def for_worker(tid: str, employee_id: str, month: str | None = None, now: datetime | None = None) -> dict:
    """What one worker may see: their own points and estimate, plus team totals (never colleagues' rows)."""
    prop = tenants.property_of_staff(tid, employee_id)
    if prop is None:
        raise Invalid("No property set up yet.")
    full = compute(tid, prop["id"], month, now)
    me = next((r for r in full["workers"] if r["employee_id"] == employee_id), None)
    if me is None:  # e.g. a manager account without a staff record
        me = {
            "employee_id": employee_id,
            "points": 0,
            "raw_points": 0,
            "capped": False,
            "jobs_done": 0,
            "eligible": False,
            "share": 0.0,
            "estimated_reward_inr": 0,
            "breakdown": _breakdown({k: 0 for k in DEFAULTS["weights"]}, full["config"]["weights"]),
        }
    out = {
        "month": full["month"],
        "period": full["period"],
        "property": full["property"],
        "employee_id": employee_id,
        "points": me["points"],
        "capped": me["capped"],
        "max_points": full["config"]["max_points_per_worker"],
        "jobs_done": me["jobs_done"],
        "min_jobs": full["config"]["min_jobs"],
        "eligible": me["eligible"],
        "estimated_reward_inr": me["estimated_reward_inr"],
        "budget_set": full["budget_set"],
        "breakdown": me["breakdown"],
        "how_to_earn": full["how_to_earn"],
        "weights": full["config"]["weights"],
        "team": {k: full["team"][k] for k in ("members", "people_with_points", "total_points", "average_points")},
        "note": full["note"],
        "synthetic": True,
    }
    if full.get("leaderboard") is not None:
        out["leaderboard"] = full["leaderboard"]
    return out
