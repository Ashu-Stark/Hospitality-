"""Solve the demo week DETERMINISTICALLY and cache both rosters the closed loop uses: the
baseline (no protection) and the protected roster (protected-weekend bonus for the high-band
permanent staff flagged by attrition.score). A cache file is only used when its input
fingerprint (week, staff, demand, config incl. weights, protected ids) matches exactly.
Run from backend/:  python run.py roster-cache
"""

from __future__ import annotations

from backend.config import default_settings
from backend.db import ensure_seeded
from backend.mongo import get_database
from backend.roster.service import make_problem
from backend.roster.solver import cache_dir, save_cache, solve_cp_sat
from backend.services import ModelService


def main() -> int:
    settings = default_settings()
    service = ModelService(settings.hotel)
    week = service.latest_week()
    flagged = [s.employee_id for s in service.score(week, None)
               if s.band == "high" and s.segment == "resignation"]
    for old in cache_dir(settings.hotel).glob(f"roster_{week}*.json"):
        old.unlink()
    db = get_database(settings)
    ensure_seeded(db, settings.config.data_source, settings.hotel)
    for name, protected in (("baseline", []), ("protected", flagged)):
        problem = make_problem(db, service, settings.config.roster, None, protected)
        outcome = solve_cp_sat(problem, deterministic=True)
        if not outcome.assignments:
            print(f"no {name} roster to cache: {outcome.status}")
            return 1
        print(f"cached {name} {outcome.status} roster (objective {outcome.objective}, "
              f"{len(outcome.assignments)} shifts, {outcome.solve_seconds:.1f}s, "
              f"protected {protected}) -> {save_cache(problem, outcome)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
