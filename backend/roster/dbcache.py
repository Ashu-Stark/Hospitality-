"""MongoDB roster cache (`hoi_ops.roster_cache`): solved rosters kept in the database. A sleeping
or slow host (Render free tier, ~0.1 CPU: a fresh CP-SAT solve hits the time limit with a poor
roster) answers from a roster solved earlier on a fast machine. All data is SYNTHETIC.

Key = (hotel data id, week_start, sorted protected ids, rules hash):
  - hotel data id: HOI_HOTEL_DATA key + a hash of the hotel's staff / leave / signal tables;
  - rules hash: the roster RULES (shifts, minimums, skills, rest, weights, roster.seed, ...)
    without the solver-effort settings (time limit, workers, deterministic budget), so a roster
    solved with a generous limit serves the API's settings.
The deterministic flag is stored with the entry, not in the key: the better (precomputed) roster
serves every request for that week. Only rosters with ZERO hard violations are stored; a new entry
replaces a stored one only if at least as good (optimal beats feasible, then lower objective).
POST /demo/reset does not drop this collection. The file cache (roster/cache) stays a fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

from pymongo.database import Database

from backend.config import RosterConfig, hotel_data

ROSTER_CACHE = "roster_cache"
SOLVER_EFFORT = (
    "time_limit_seconds",
    "num_workers",
    "deterministic",
)  # not rules (roster.seed places leave)
STATUS_RANK = {"optimal": 3, "feasible": 2, "heuristic": 1, "cached": 1}


@lru_cache(maxsize=8)
def _files_hash(paths: tuple[Path, ...]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def data_id(hotel: str) -> str:
    d = hotel_data(hotel).data_dir
    files = (
        "employee_v2.csv",
        "weekly_behaviour.csv",
        "weekly_signals.csv",
        "employee_skill.csv",
        "pay_changes.csv",
        "occupancy_daily.csv",
    )
    return f"{hotel}:{_files_hash(tuple(d / f for f in files))}"


def rules_hash(cfg: RosterConfig) -> str:
    rules = {k: v for k, v in cfg.rules_dump().items() if k not in SOLVER_EFFORT}
    return hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest()[:16]


def cache_key(cfg: RosterConfig, week: date, protected: list[str]) -> dict:
    return {
        "data_id": data_id(cfg.hotel),
        "week_start": week.isoformat(),
        "protected_ids": sorted(set(protected)),
        "rules_hash": rules_hash(cfg),
    }


def ensure_index(db: Database) -> None:
    db[ROSTER_CACHE].create_index(
        [("data_id", 1), ("week_start", 1), ("protected_ids", 1), ("rules_hash", 1)],
        unique=True,
        name="roster_cache_key",
    )


def get(db: Database, cfg: RosterConfig, week: date, protected: list[str]) -> dict | None:
    return db[ROSTER_CACHE].find_one(cache_key(cfg, week, protected), {"_id": 0})


def solved_on() -> str:
    return "render" if os.environ.get("RENDER") else "local"


def _better(new: dict, old: dict | None) -> bool:
    if old is None:
        return True
    rn, ro = STATUS_RANK.get(new["status"], 0), STATUS_RANK.get(old["status"], 0)
    if rn != ro:
        return rn > ro
    return (new.get("objective") or 0) <= (old.get("objective") or 0)


def put(
    db: Database,
    cfg: RosterConfig,
    week: date,
    protected: list[str],
    result: dict,
    deterministic: bool,
    occupancy_source: str = "forecast",
    force: bool = False,
) -> bool:
    """Store a roster result (a RosterResult dump); refuses hard violations or no assignments.
    Returns True when stored (new, or at least as good as the stored one, or force)."""
    if (
        result.get("hard_violations")
        or not result.get("assignments")
        or result.get("status") == "infeasible"
    ):
        return False
    key = cache_key(cfg, week, protected)
    old = db[ROSTER_CACHE].find_one(key, {"_id": 0, "status": 1, "objective": 1})
    if not force and not _better(result, old):
        return False
    cov = result.get("coverage") or []
    req = sum(c["required_hours"] for c in cov)
    got = sum(min(c["scheduled_hours"], c["required_hours"]) for c in cov)
    doc = {
        **key,
        "hotel": cfg.hotel,
        "deterministic": bool(deterministic),
        "status": result["status"],
        "method": result["method"],
        "objective": result.get("objective"),
        "solve_seconds": result.get("solve_seconds"),
        "quality": {
            "status": result["status"],
            "coverage_pct": round(100 * got / req, 2) if req else 100.0,
            "objective": result.get("objective"),
        },
        "result": json.loads(
            json.dumps({k: v for k, v in result.items() if k != "id"}, default=str)
        ),
        "occupancy_source": occupancy_source,
        "solved_at": datetime.now(UTC),
        "solved_on": solved_on(),
        "synthetic": True,
    }
    db[ROSTER_CACHE].replace_one(key, doc, upsert=True)
    return True
