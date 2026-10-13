"""Run the real models for ALL staff of the FICTIONAL Himsagar Ridge Resort (SYNTHETIC data) and store the outputs where
the dashboards read them. Re-runnable: every step is an upsert or idempotent.

    .venv\\Scripts\\python.exe scripts\\run_demo_models.py               # in memory (mongomock): a dry run, nothing saved
    .venv\\Scripts\\python.exe scripts\\run_demo_models.py --live --yes  # the real cluster (MONGODB_URI from env / root .env)

1. Staff (ids, departments, role titles, contract types, skills; no names or personal attributes):
   - hoi_platform: the demo tenant's 20 staff HS01-HS20 upserted on the Himsagar property (HS01 = hotel manager).
   - hoi_ops: employee_snapshot must hold the 19 rostered staff HS02-HS20 of ml/data/hotels/himsagar; reloaded from the
     ml data only when it does not (HS01 is the manager: not rostered and not in the synthetic weekly records, so the
     models cannot score HS01).
   - Both are checked against each other (department and contract type per id).
2. Models (the backend's ml entry points, artifacts in ml/artifacts): forecast.predict (next 7 days from the demo week
   start), attrition.score (everyone), the CP-SAT roster (MongoDB roster_cache first, else a deterministic solve that is
   then cached, so Render's sleep never loses it), and the closed loop (high-chance staff -> follow-up tasks, protected
   roster, attrition.rescore). The loop's tasks are idempotent per week / person / action.
3. Outputs for the dashboards: hoi_ops roster / roster_cache / task / intervention / audit_log ("demo_models.run");
   hoi_platform roster_snapshots (the worker app's shifts) and dispatch_context (who is on shift today + chance-of-leaving
   bands for the retention guard) of the demo tenant only.
Only the demo hotel's documents are added or updated: no collection is dropped. Counts are printed before and after.
MONGODB_URI is a secret: never printed.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "platform_api")]

HOTEL = "himsagar"
SOURCE = "run_demo_models"
OPS_COLLECTIONS = ("employee_snapshot", "roster", "roster_cache", "task", "intervention", "audit_log")
PLATFORM_COLLECTIONS = ("staff", "roster_snapshots", "dispatch_context")
LEVEL = {"low": "low", "watch": "moderate", "high": "high"}


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ------------------------------------------------------------------ connections
def ops_db(uri: str, name: str):  # noqa: ANN201
    from backend.config import make_settings
    from backend.mongo import get_database

    s = make_settings(name, mock=False, mongodb_uri=uri, hotel=HOTEL)
    return s, get_database(s)


def platform_modules(uri: str, name: str):  # noqa: ANN201
    os.environ["MONGODB_URI"] = uri
    os.environ["HOI_PLATFORM_DB"] = name
    os.environ.setdefault("HOI_SEED_DEMO", "true")
    os.environ.setdefault("HOI_DEMO_LOGIN", "true")
    os.environ.pop("HOI_ADMIN_PASSWORD", None)  # never create or change the platform admin from here
    from hoi_platform import config

    config.reload()
    from hoi_platform import mongo, seed
    from hoi_platform.services import dispatch, tenants

    return mongo, seed, dispatch, tenants


def counts(ops, pmongo, tid: str) -> dict[str, int]:  # noqa: ANN001
    out = {f"hoi_ops.{c}": ops[c].count_documents({}) for c in OPS_COLLECTIONS}
    out.update({f"hoi_platform.{c} (demo tenant)": pmongo.col(c).count_documents({"tenant_id": tid}) for c in PLATFORM_COLLECTIONS})
    return out


def print_counts(title: str, c: dict[str, int], before: dict[str, int] | None = None) -> None:
    print(f"\n{title}")
    for k, v in c.items():
        delta = f"  ({v - before[k]:+d})" if before is not None else ""
        print(f"  {k:<42} {v:>6}{delta}")


# ------------------------------------------------------------------ steps
def ensure_platform_staff(seed, tenants, pmongo) -> tuple[str, list[dict]]:  # noqa: ANN001
    """Upsert the 20 staff on the Himsagar property; returns (property id, staff rows)."""
    if pmongo.col("tenants").find_one({"id": seed.DEMO_ID}, {"_id": 1}) is None:
        seed.ensure_demo()  # demo tenant missing (fresh database): create it
    prop = next(p for p in tenants.properties(seed.DEMO_ID) if p["name"] == seed.HOTEL_NAME)
    rows = [{**r, "property_id": prop["id"]} for r in seed.staff_rows()]
    tenants.import_staff(seed.DEMO_ID, rows)
    have = [s for s in tenants.staff(seed.DEMO_ID) if s.get("property_id") == prop["id"]]
    return prop["id"], have


def ensure_ops_snapshot(db) -> list[dict]:  # noqa: ANN001
    from backend.config import hotel_data
    from backend.db import EMPLOYEES, NO_ID, ensure_indexes, seed, snapshot_frame

    ensure_indexes(db)
    want = snapshot_frame(hotel_data(HOTEL).data_dir)
    want_key = sorted(zip(want["employee_id"], want["department"], want["week_start"], strict=True))
    have = list(db[EMPLOYEES].find({}, NO_ID))
    have_key = sorted((r["employee_id"], r["department"], r["week_start"]) for r in have)
    if have_key != want_key:
        print(f"  hoi_ops employee_snapshot differs from the {HOTEL} data ({len(have)} rows): reloading it from ml/data")
        seed(db, SOURCE, hotel=HOTEL)
        have = list(db[EMPLOYEES].find({}, NO_ID))
    return have


def check_consistency(platform_staff: list[dict], ops_staff: list[dict]) -> list[str]:
    p = {s["employee_id"]: s for s in platform_staff}
    problems = []
    for r in ops_staff:
        s = p.get(r["employee_id"])
        if s is None:
            problems.append(f"{r['employee_id']} is in hoi_ops but not on the platform")
        elif (s["department"], s.get("contract_type")) != (r["department"], r["contract_type"]):
            problems.append(f"{r['employee_id']}: platform {s['department']}/{s.get('contract_type')} vs ops {r['department']}/{r['contract_type']}")
    extra = sorted(set(p) - {r["employee_id"] for r in ops_staff})
    if extra != ["HS01"]:
        problems.append(f"platform-only staff should be just HS01 (hotel manager), got {extra}")
    return problems


def today_cover(roster, demand: dict) -> dict:  # noqa: ANN001
    """Day 1 of the roster week: required hours (forecast-driven demand) vs the hours left short."""
    day = roster.week_start
    on = [a for a in roster.assignments if a.date == day]
    short = [g for g in roster.violated_soft_goals if g.get("goal") == "understaffed" and int(g.get("day", -1)) == 0]
    required = sum(v for (_, d, _), v in demand.items() if d == 0)
    hours_short = sum(g.get("hours_short", 0) for g in short)
    return {"date": day.isoformat(), "people_on_shift": len({a.employee_id for a in on}), "by_shift": dict(Counter(a.shift for a in on)),
            "required_hours": round(required, 1), "hours_short": round(hours_short, 1),
            "coverage": round(1 - hours_short / required, 4) if required else 1.0, "understaffed_shifts": len(short)}


def run(uri: str, ops_name: str = "hoi_ops", platform_name: str = "hoi_platform") -> dict | None:
    """The whole run. Returns the summary, or None when the staff do not match or the roster week is impossible."""
    from backend import loop
    from backend.db import audit
    from backend.roster.service import RosterRequest, generate, make_problem
    from backend.services import ModelService

    settings, ops = ops_db(uri, ops_name)
    pmongo, seed, dispatch, tenants = platform_modules(uri, platform_name)
    tid = seed.DEMO_ID
    before = counts(ops, pmongo, tid)
    print_counts("Counts BEFORE", before)

    print("\n1. Staff (ids and roles only)")
    pid, pstaff = ensure_platform_staff(seed, tenants, pmongo)
    ostaff = ensure_ops_snapshot(ops)
    problems = check_consistency(pstaff, ostaff)
    print(f"  platform: {len(pstaff)} staff on the Himsagar property; hoi_ops: {len(ostaff)} rostered staff "
          f"({ostaff[0]['employee_id']}..{ostaff[-1]['employee_id']}); HS01 = hotel manager (platform only, not rostered)")
    if problems:
        print("  MISMATCH:\n   - " + "\n   - ".join(problems))
        return None
    print("  departments and contract types match for every id")

    service = ModelService(HOTEL)
    week = service.latest_week()
    print(f"\n2. Models (demo week {week}, SYNTHETIC data)")
    fc = service.forecast(week, week + timedelta(days=6), None)
    scores = service.score(week, None)
    levels = Counter(LEVEL.get(s.band, s.band) for s in scores)
    roster = generate(ops, service, settings.config.roster, RosterRequest(use_cache=True, deterministic=True), SOURCE)
    if roster.status == "infeasible":
        print("  roster infeasible: " + "; ".join(roster.causes))
        return None
    tasks_before = ops["task"].count_documents({})
    result = loop.run_loop(ops, service, settings.config, datetime.now(UTC), SOURCE)
    tasks_new = ops["task"].count_documents({}) - tasks_before
    week_cov = loop.coverage(roster)
    today = today_cover(roster, make_problem(ops, service, settings.config.roster, None, []).demand)

    print("\n3. Publish to the platform (demo tenant only)")
    dept = {r["employee_id"]: r["department"] for r in ostaff}
    dispatch.publish_roster(tid, week.isoformat(), [a.model_dump(mode="json") for a in roster.assignments])
    morning = {a.employee_id: dept[a.employee_id] for a in roster.assignments if a.date == week and a.shift == "morning"}
    dispatch.set_context(tid, week.isoformat(), "morning", morning, {s.employee_id: s.band for s in scores}, seed.FLOORS)
    print(f"  roster_snapshots: {len(roster.assignments)} shifts; dispatch_context: {len(morning)} on the morning shift, "
          f"{len(scores)} chance-of-leaving bands")

    summary = {
        "week_start": week.isoformat(), "staff_scored": len(scores), "levels": dict(levels),
        "high": sorted(s.employee_id for s in scores if s.band == "high"),
        "roster_id": roster.id, "roster_method": roster.method, "week_coverage": week_cov,
        "today": today, "loop_tasks_new": tasks_new, "loop_interventions": len(result.interventions),
        "forecast": [{"date": d.date.isoformat(), "occupancy": round(d.mean, 3), "low": round(d.low, 3), "high": round(d.high, 3)}
                     for d in fc.days],
        "synthetic": True,
    }
    audit(ops, "demo_models.run", summary, SOURCE)
    print_counts("Counts AFTER", counts(ops, pmongo, tid), before)

    print("\nSUMMARY (fictional Himsagar Ridge Resort, SYNTHETIC data)")
    print(f"  Chance of leaving, {len(scores)} staff scored (HS01 manager not scored): "
          f"high {levels.get('high', 0)}, moderate {levels.get('moderate', 0)}, low {levels.get('low', 0)}")
    for s in sorted(scores, key=lambda x: -x.risk):
        if s.band != "low":
            print(f"    {s.employee_id} {dept[s.employee_id]:<13} {LEVEL[s.band]:<9} {s.risk:.1%}  "
                  f"reasons: {', '.join(d.category for d in s.drivers[:3]) or 'contract ends'}")
    print(f"  Roster {roster.id} ({roster.method}, {len(roster.hard_violations)} rule breaks): week coverage {week_cov:.1%}; today {week}: "
          f"coverage {today['coverage']:.1%} ({today['required_hours']} h needed, {today['hours_short']} h short in "
          f"{today['understaffed_shifts']} shift(s)), {today['people_on_shift']} people on shift {today['by_shift']}")
    print(f"  Follow-up tasks: {len(result.interventions)} for {len(result.flagged)} high-chance staff "
          f"({', '.join(result.flagged) or 'none'}); {tasks_new} new this run (idempotent)")
    print("  Occupancy forecast, next 7 days (80% band):")
    for d in fc.days:
        flag = " HIGH DEMAND" if d.high_demand_alert else (" LOW DEMAND" if d.low_demand_alert else "")
        print(f"    {d.date} {d.date.strftime('%a')}  {d.mean:.0%}  ({d.low:.0%}-{d.high:.0%}){flag}")
    return summary


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run the models for all Himsagar staff and store the outputs (SYNTHETIC data).")
    ap.add_argument("--live", action="store_true", help="use MONGODB_URI (the real cluster) instead of an in-memory database")
    ap.add_argument("--yes", action="store_true", help="really write to the cluster (with --live)")
    args = ap.parse_args(argv)
    if not args.live:
        print("Dry run on an in-memory database (mongomock): nothing is saved. Use --live --yes for the cluster.")
        tag = uuid.uuid4().hex[:6]
        return 0 if run("mongomock://", f"hoi_ops_dry_{tag}", f"hoi_platform_dry_{tag}") else 1
    load_env()
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri or uri.startswith("mongomock"):
        print("MONGODB_URI is not set (or is mongomock://): nothing to do.")
        return 1
    if not args.yes:
        print("Add --yes to write to the cluster (only the demo hotel's documents in hoi_ops and hoi_platform).")
        return 2
    print("Live run on the cluster in MONGODB_URI (hoi_ops, hoi_platform demo tenant).")
    return 0 if run(uri) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
