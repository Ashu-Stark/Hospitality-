"""Roster stress test (B2): random scenarios on the real demo-week staff, SYNTHETIC data.

Each scenario draws, from a seeded generator, approved leave (0-2 days per person), daily
occupancy (0.30-1.00) and the carried-in consecutive days (0-6), solves with the production
solve() and re-checks every HARD rule with the independent checker. Some random weeks are
genuinely impossible (e.g. 3 of the 5 security staff must rest on Monday after a 6-day run):
they must come back as status "infeasible" with causes and no roster.
Run from backend/:  python run.py roster-stress   (the slow test runs the same 100 scenarios)
"""

from __future__ import annotations

import statistics
import sys
from collections import Counter
from dataclasses import replace

import numpy as np

from backend.config import load_backend_config
from backend.db import snapshot_frame
from backend.roster.problem import DAYS, build_problem
from backend.roster.solver import solve

LEAVE_DAYS, LEAVE_P = [0, 1, 2], [0.7, 0.2, 0.1]
OCC_RANGE = (0.30, 1.00)


def scenarios(n: int, seed: int) -> list:
    cfg = load_backend_config().roster
    rows = snapshot_frame().to_dict("records")
    rng = np.random.default_rng([seed, n])
    out = []
    for _ in range(n):
        occ = rng.uniform(*OCC_RANGE, DAYS).round(3).tolist()
        carry = {r["employee_id"]: int(rng.integers(0, 7)) for r in rows}
        base = build_problem(cfg.demo_week, rows, occ, cfg, carry=carry)
        staff = []
        for s in base.staff:
            k = int(rng.choice(LEAVE_DAYS, p=LEAVE_P))
            start = int(rng.integers(0, DAYS - k + 1))
            staff.append(replace(s, leave_days=frozenset(range(start, start + k))))
        out.append(replace(base, staff=staff))
    return out


def run(n: int = 100, seed: int | None = None) -> dict:
    cfg = load_backend_config().roster
    results = []
    for p in scenarios(n, cfg.seed if seed is None else seed):
        o = solve(p)
        results.append({"method": o.method, "status": o.status, "seconds": o.solve_seconds,
                        "published": bool(o.assignments), "causes": o.causes,
                        "hard_violations": len(o.hard_violations),
                        "understaffed_shifts": o.summary["cost"]["understaffed_shifts"],
                        "overtime_hours": o.summary["cost"]["overtime_hours"]})
    secs = [r["seconds"] for r in results if r["method"] == "cp_sat"]
    solved = [r for r in results if r["published"]]
    infeasible = [r for r in results if r["status"] == "infeasible"]
    return {
        "scenarios": n,
        "solved": len(solved),
        "infeasible": len(infeasible),
        "infeasible_with_causes": sum(bool(r["causes"]) for r in infeasible),
        "hard_violations_total": sum(r["hard_violations"] for r in results),
        "hit_time_limit": sum(r["seconds"] >= cfg.time_limit_seconds for r in results),
        "methods": dict(Counter(r["method"] for r in results)),
        "statuses": dict(Counter(r["status"] for r in results)),
        "solve_seconds": {"mean": round(statistics.mean(secs), 2),
                          "median": round(statistics.median(secs), 2),
                          "p95": round(float(np.percentile(secs, 95)), 2),
                          "max": round(max(secs), 2)} if secs else {},
        "understaffed_shifts_mean_solved": round(statistics.mean(
            r["understaffed_shifts"] for r in solved), 1) if solved else None,
        "results": results,
    }


def main(argv: list[str]) -> int:
    n = int(argv[0]) if argv else 100
    report = run(n)
    print(f"Roster stress test (SYNTHETIC): {n} scenarios")
    for k, v in report.items():
        if k != "results":
            print(f"  {k}: {v}")
    for i, r in enumerate(report["results"]):
        if r["status"] == "infeasible":
            print(f"  scenario {i} infeasible: " + " | ".join(r["causes"]))
    return 0 if report["hard_violations_total"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
