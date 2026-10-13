"""Roster problem inputs (B2), from SYNTHETIC data.

- Staff: the employee snapshot (active staff + demo heroes, who join their department as extra
  staff so the closed loop can roster them; labelled is_demo_hero).
- Demand: required hours per department and day from the ml workload standards (config.yaml
  `workload`: base_hours per week + per_occupied_room_night_hours), spread by the occupancy
  FORECAST for each day: base / 7 + per_room_night x rooms x forecast occupancy. Split across the
  department's shifts by roster.demand_share.
- Leave: the synthetic leave table gives leave DAYS PER WEEK, not dates. They are placed as a
  consecutive block at a seeded offset per employee (documented assumption).
- Carry-in: consecutive days worked at the end of the previous week (ml weekly_signals /
  hero_weekly), so max_consecutive_days holds across the week boundary.
"""

from __future__ import annotations

import hashlib
import json
import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from backend.config import RosterConfig, hotel_data

DAYS = 7


@dataclass(frozen=True)
class Staff:
    employee_id: str
    department: str
    skills: frozenset[str]
    monthly_pay: float
    leave_days: frozenset[int]  # day indexes 0..6 (Mon..Sun) on approved leave
    carry_days: int  # consecutive days worked at the end of the previous week
    is_demo_hero: bool = False
    # shift worked on the last day of the previous week, when known (rolling rosters): the minimum
    # rest rule then also holds across the week boundary (e.g. Sunday evening -> Monday morning)
    last_shift: str | None = None


@dataclass
class Problem:
    week_start: date
    staff: list[Staff]
    demand: dict[tuple[str, int, str], float]  # (department, day, shift) -> required hours
    cfg: RosterConfig
    standard_weekly_hours: float
    protected: frozenset[str] = field(default_factory=frozenset)

    @property
    def days(self) -> list[date]:
        return [self.week_start + timedelta(days=d) for d in range(DAYS)]

    def shifts_of(self, department: str) -> list[str]:
        return self.cfg.department_shifts[department]

    def fingerprint(self) -> str:
        """Hash of every input, so a cached roster is only reused for the same problem."""
        payload = {
            "week": str(self.week_start), "protected": sorted(self.protected),
            "staff": [[s.employee_id, s.department, sorted(s.skills), sorted(s.leave_days),
                       s.carry_days] + ([s.last_shift] if s.last_shift else [])
                      for s in self.staff],
            "demand": sorted([list(k) + [round(v, 3)] for k, v in self.demand.items()]),
            "cfg": self.cfg.rules_dump(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def place_leave(employee_id: str, n_days: int, seed: int) -> frozenset[int]:
    """n leave days as a consecutive block at a seeded, per-employee offset (Mon = 0)."""
    n = max(0, min(int(n_days), DAYS))
    if n == 0:
        return frozenset()
    rng = np.random.default_rng([seed, zlib.crc32(employee_id.encode())])
    start = int(rng.integers(0, DAYS - n + 1))
    return frozenset(range(start, start + n))


def daily_demand(occupancy: list[float], cfg: RosterConfig) -> dict[tuple[str, int, str], float]:
    """Required hours per (department, day, shift) from the hotel's ml workload standards."""
    ml = hotel_data(cfg.hotel).ml
    out = {}
    for dept, shifts in cfg.department_shifts.items():
        std = ml.workload[dept]
        for d, occ in enumerate(occupancy):
            rooms = ml.property.rooms
            hours = std.base_hours / DAYS + std.per_occupied_room_night_hours * rooms * occ
            for s in shifts:
                out[(dept, d, s)] = hours * cfg.demand_share[dept][s]
    return out


def carry_in(week_start: date, cfg: RosterConfig) -> dict[str, int]:
    """consecutive_days_worked in the previous week (ml signals + demo heroes), capped."""
    prev = str(week_start - timedelta(days=DAYS))
    data = hotel_data(cfg.hotel).data_dir
    frames = [pd.read_csv(data / "weekly_signals.csv"),
              pd.read_csv(data / "demo" / "hero_weekly.csv")]
    rows = pd.concat([f[["employee_id", "week_start", "consecutive_days_worked"]] for f in frames])
    rows = rows[rows["week_start"].astype(str) == prev]
    return {e: min(int(c), cfg.max_consecutive_days)
            for e, c in zip(rows["employee_id"], rows["consecutive_days_worked"], strict=True)}


def build_problem(week_start: date, snapshot: list[dict], occupancy: list[float],
                  cfg: RosterConfig, protected: frozenset[str] = frozenset(),
                  carry: dict[str, int] | None = None,
                  last_shift: dict[str, str] | None = None) -> Problem:
    carry = carry if carry is not None else carry_in(week_start, cfg)
    staff = [Staff(employee_id=r["employee_id"], department=r["department"],
                   skills=frozenset(json.loads(r["skills"])), monthly_pay=float(r["monthly_pay"]),
                   leave_days=place_leave(r["employee_id"], r["leave_days"], cfg.seed),
                   carry_days=carry.get(r["employee_id"], 0),
                   last_shift=(last_shift or {}).get(r["employee_id"]),
                   is_demo_hero=bool(r["is_demo_hero"]))
             for r in snapshot if r["department"] in cfg.department_shifts]
    return Problem(week_start=week_start, staff=staff, demand=daily_demand(occupancy, cfg),
                   cfg=cfg,
                   standard_weekly_hours=hotel_data(cfg.hotel).ml.staff.standard_weekly_hours,
                   protected=protected)


def forbidden_pairs(cfg: RosterConfig) -> list[tuple[str, str]]:
    """(shift on day d, shift on day d+1) pairs with less than min_rest_hours between them."""
    out = []
    for a, sa in cfg.shifts.items():
        for b, sb in cfg.shifts.items():
            rest = 24 + sb.start - (sa.start + sa.hours)
            if rest < cfg.min_rest_hours:
                out.append((a, b))
    return out
