"""Precompute rosters into the MongoDB roster cache on a FAST machine (roster-precompute).

    python run.py roster-precompute [--weeks N] [--time-limit 60]

For the served hotel (HOI_HOTEL_DATA, default himsagar) it solves the snapshot (demo) week and the
next N weeks, each as a BASELINE roster and a PROTECTED roster (protected-weekend bonus for the
high-band permanent staff the closed loop flags), with CP-SAT in deterministic mode and a generous
wall-clock limit, re-checks every roster with the independent checker (0 hard violations required)
and upserts it into `roster_cache` of the database at MONGODB_URI (environment or the root .env;
never printed). All data is SYNTHETIC.

Weeks after the demo week (ASSUMED inputs, labelled in each entry's occupancy_source):
  - occupancy: the same 7 weekdays 52 weeks earlier from the hotel's synthetic occupancy table
    (the trained forecast only covers the synthetic data range);
  - leave: none (future leave is unknown); staff: the demo-week snapshot;
  - consecutive days and the last shift: carried from the previous precomputed week of the same
    variant, so the rest rule and the 6-day limit hold across week boundaries.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backend.config import REPO_ROOT, hotel_data, make_settings
from backend.db import ensure_seeded
from backend.mongo import database_kind, get_database
from backend.roster import dbcache
from backend.roster.check import hard_violations, summarize
from backend.roster.problem import DAYS, Problem, build_problem
from backend.roster.service import make_problem, snapshot_rows
from backend.roster.solver import infeasibility_causes, solve_cp_sat
from backend.services import ModelService

SAME_WEEK_LAST_YEAR = "same weekdays 52 weeks earlier (synthetic occupancy table; ASSUMED)"


def load_env(path: Path = REPO_ROOT / ".env") -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def past_occupancy(hotel: str, week: date) -> list[float]:
    occ = pd.read_csv(hotel_data(hotel).data_dir / "occupancy_daily.csv").set_index("date")
    start = week - timedelta(weeks=52)
    return [float(occ.loc[str(start + timedelta(days=d)), "occupancy_pct"]) for d in range(DAYS)]


def result_of(problem: Problem, outcome, seconds_limit: float) -> dict:  # noqa: ANN001
    hours = {n: s.hours for n, s in problem.cfg.shifts.items()}
    s = summarize(problem, outcome.assignments)
    return {"week_start": problem.week_start.isoformat(), "method": "cp_sat_precomputed",
            "status": outcome.status, "solve_seconds": round(outcome.solve_seconds, 2),
            "objective": outcome.objective, "protected_ids": sorted(problem.protected),
            "hard_violations": hard_violations(problem, outcome.assignments), "causes": [],
            "coverage": s["coverage"], "cost": s["cost"], "people": s["people"],
            "violated_soft_goals": s["violated_soft_goals"], "time_limit_seconds": seconds_limit,
            "assignments": [{"employee_id": a.employee_id,
                             "date": (problem.week_start + timedelta(days=a.day)).isoformat(),
                             "shift": a.shift, "hours": hours[a.shift]}
                            for a in outcome.assignments]}


def carry_from(problem: Problem, outcome) -> tuple[dict[str, int], dict[str, str]]:  # noqa: ANN001
    days: dict[str, dict[int, str]] = {}
    for a in outcome.assignments:
        days.setdefault(a.employee_id, {})[a.day] = a.shift
    carry, last = {}, {}
    for s in problem.staff:
        d = days.get(s.employee_id, {})
        run = 0
        for k in range(DAYS - 1, -1, -1):
            if k not in d:
                break
            run += 1
        carry[s.employee_id] = min(run + (s.carry_days if run == DAYS else 0),
                                   problem.cfg.max_consecutive_days)
        if DAYS - 1 in d:
            last[s.employee_id] = d[DAYS - 1]
    return carry, last


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Precompute rosters into hoi_ops.roster_cache")
    ap.add_argument("--weeks", type=int, default=4, help="weeks after the demo week (default 4)")
    ap.add_argument("--time-limit", type=float, default=60.0, help="wall-clock seconds per solve")
    args = ap.parse_args(argv)
    load_env()
    settings = make_settings()
    cfg = settings.config.roster
    effort = cfg.model_copy(update={"deterministic": cfg.deterministic.model_copy(update={
        "safety_seconds": args.time_limit,
        "max_deterministic_time": max(cfg.deterministic.max_deterministic_time, args.time_limit)})})
    db = get_database(settings)
    ensure_seeded(db, settings.config.data_source, settings.hotel)
    dbcache.ensure_index(db)
    service = ModelService(settings.hotel)
    week = service.latest_week()
    flagged = sorted(s.employee_id for s in service.score(week, None)
                     if s.band == "high" and s.segment == "resignation")
    print(f"roster precompute: hotel {settings.hotel}, database {database_kind(settings)}, "
          f"demo week {week}, +{args.weeks} weeks, flagged {flagged} (SYNTHETIC)")
    rows = [{**r, "leave_days": 0} for r in snapshot_rows(db)]
    failures = 0
    for name, protected in (("baseline", []), ("protected", flagged)):
        carry = last = None
        for k in range(args.weeks + 1):
            wk = week + timedelta(weeks=k)
            if k == 0:
                problem = make_problem(db, service, cfg, None, protected)
                source = "forecast"
            else:
                problem = build_problem(wk, rows, past_occupancy(settings.hotel, wk), cfg,
                                        frozenset(protected), carry=carry, last_shift=last)
                source = SAME_WEEK_LAST_YEAR
            outcome = solve_cp_sat(replace(problem, cfg=effort), deterministic=True)
            if not outcome.assignments:
                causes = infeasibility_causes(problem) if outcome.status == "infeasible" else []
                print(f"  {name} {wk}: {outcome.status}, NOT cached; {causes[:2]}")
                failures += 1
                break
            res = result_of(problem, outcome, args.time_limit)
            if res["hard_violations"]:
                print(f"  {name} {wk}: {len(res['hard_violations'])} hard violations, NOT cached")
                failures += 1
                break
            stored = dbcache.put(db, cfg, wk, protected, res, True, occupancy_source=source)
            cov = dbcache.get(db, cfg, wk, protected)["quality"]["coverage_pct"]
            print(f"  {name} {wk}: {outcome.status}, objective {outcome.objective:.0f}, coverage "
                  f"{cov}%, overtime {res['cost']['overtime_hours']} h, "
                  f"{outcome.solve_seconds:.1f} s"
                  f"{'' if stored else ' (kept the stored roster: at least as good)'}")
            carry, last = carry_from(problem, outcome)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
