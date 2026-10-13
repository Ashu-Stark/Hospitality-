"""Checks for the T5 weekly signals, leave / pulse tables and the scripted demo heroes.

Run from ml/:  python run.py validate
(or from the repo root: python -m ml.generator.validate_heroes)
Exits 1 if any check fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ml.generator.behaviour import DAYS_PER_MONTH
from ml.generator.config import GeneratorConfig, load_config
from ml.generator.heroes import HeroFile, load_heroes
from ml.generator.run_signals import DATA_DIR, SignalOutputs, build_outputs
from ml.generator.validate_occupancy import Check, frame_hash, print_table

LINE_TOLERANCE = 0.05  # scripted straight lines must match to this precision
TOP_SHARE = 0.10  # "top-10% task score"
MONTH_TOLERANCE = 0.5


def signal_checks(out: SignalOutputs, behaviour: pd.DataFrame, cfg: GeneratorConfig,
                  rerun_hash: str) -> list[Check]:
    s, keys = out.signals, ["employee_id", "week_start"]
    beh_keys = set(zip(behaviour["employee_id"], pd.to_datetime(behaviour["week_start"]),
                       strict=True))
    sig_keys = set(zip(s["employee_id"], s["week_start"], strict=True))
    leave_ok = (out.leave["leave_days"] > 0).all() and int(out.leave["leave_days"].sum()) == int(
        behaviour["leave_days"].sum())
    pulse_ok = len(out.pulse) == len(behaviour) and set(
        zip(out.pulse["employee_id"], out.pulse["week_start"], strict=True)) == beh_keys
    lo, hi = cfg.signals.task_score_min, cfg.signals.task_score_max
    h = frame_hash(pd.concat([s, out.leave, out.pulse], keys=["s", "l", "p"]))
    return [
        Check("one signal row per weekly_behaviour row", sig_keys == beh_keys
              and not s.duplicated(keys).any(), f"{len(s)} rows"),
        Check(f"task_score in [{lo:g}, {hi:g}]", bool(s["task_score"].between(lo, hi).all()),
              f"mean {s['task_score'].mean():.1f}"),
        Check("no weekend off whenever the weekly off was skipped",
              not (s["weekly_off_skipped"] & s["weekend_off"]).any(), "ok"),
        Check("leave_records match weekly leave (no rows after exit)", bool(leave_ok),
              f"{len(out.leave)} rows"),
        Check("pulse_responses match employed weeks (no rows after exit)", bool(pulse_ok),
              f"{len(out.pulse)} rows"),
        Check("same seed -> identical hash (signals)", h == rerun_hash,
              f"{h[:12]} vs {rerun_hash[:12]}"),
    ]


def _first_last(w: pd.DataFrame, col: str) -> tuple[float, float]:
    return float(w[col].iloc[0]), float(w[col].iloc[-1])


def _line_ok(w: pd.DataFrame, col: str, pair: tuple[float, float]) -> bool:
    first, last = _first_last(w, col)
    return abs(first - pair[0]) <= LINE_TOLERANCE and abs(last - pair[1]) <= LINE_TOLERANCE


def hero_checks(out: SignalOutputs, script: HeroFile, cfg: GeneratorConfig,
                employee_ids: set[str]) -> list[Check]:
    emp = out.hero_employees.set_index("employee_id")
    weekly = out.hero_weekly
    last = pd.to_datetime(weekly["week_start"]).max()
    checks = [
        Check("heroes are fictional ids, not in the training employee table",
              not set(emp.index) & employee_ids, f"{len(emp)} heroes"),
        Check(f"each hero has exactly {script.weeks} scripted weeks",
              bool((weekly.groupby("employee_id").size() == script.weeks).all()), "ok"),
    ]
    top_cut = out.signals["task_score"].quantile(1 - TOP_SHARE)
    for hid, h in script.heroes.items():
        w = weekly[weekly["employee_id"] == hid].sort_values("week_start")
        e = emp.loc[hid]
        ok = all(_line_ok(w, c, getattr(h, c)) for c in
                 ("overtime_hours", "pulse_score", "task_score"))
        tenure = (last - pd.Timestamp(e["hire_date"])).days / DAYS_PER_MONTH
        since = (last - pd.Timestamp(e["last_raise_date"])).days / DAYS_PER_MONTH
        pay_ratio = e["monthly_pay"] / cfg.roles[h.department][h.role].pay_mean
        ok &= abs(tenure - h.tenure_months) <= MONTH_TOLERANCE
        ok &= abs(since - h.months_since_raise) <= MONTH_TOLERANCE
        ok &= abs(pay_ratio - h.pay_ratio) <= LINE_TOLERANCE / 5
        if h.no_weekend_off_last_weeks:  # exactly that many final weeks without a weekend off
            ok &= int(w["weeks_since_weekend_off"].iloc[-1]) == h.no_weekend_off_last_weeks
        else:  # regular weekend offs: never more than one week in a row without one
            ok &= int(w["weeks_since_weekend_off"].max()) <= 1
        detail = (f"OT {_first_last(w, 'overtime_hours')}, pulse {_first_last(w, 'pulse_score')}"
                  f", task {_first_last(w, 'task_score')}, tenure {tenure:.0f}m, raise "
                  f"{since:.0f}m ago, pay ratio {pay_ratio:.2f}, weeks w/o weekend off "
                  f"{int(w['weeks_since_weekend_off'].iloc[-1])}")
        if h.contract_end_in_days:
            days_left = (pd.Timestamp(e["contract_end_date"]) - last).days
            ok &= days_left == h.contract_end_in_days and e["contract_type"] == "seasonal"
            detail += f", contract ends in {days_left}d"
        if hid == "H902":  # Rajesh: top-10% task score
            ok &= float(w["task_score"].min()) >= top_cut
            detail += f", task >= population 90th pct {top_cut:.1f}"
        checks.append(Check(f"hero {hid} ({h.story}) matches script", bool(ok), detail))
    sunita = weekly[weekly["employee_id"] == "H901"]
    checks.append(Check("H901 leave is clustered before a festival",
                        int(sunita["leave_before_festival"].sum()) == int(
                            sunita["leave_days"].sum()) > 0,
                        f"{int(sunita['leave_before_festival'].sum())} of "
                        f"{int(sunita['leave_days'].sum())} leave days before a festival"))
    return checks


def main(data_dir: Path = DATA_DIR) -> int:
    cfg = load_config()
    out = build_outputs(cfg, data_dir)
    again = build_outputs(cfg, data_dir)
    behaviour = pd.read_csv(data_dir / "weekly_behaviour.csv")
    employee_ids = set(pd.read_csv(data_dir / "employee_v2.csv")["employee_id"])
    rerun = frame_hash(pd.concat([again.signals, again.leave, again.pulse], keys=["s", "l", "p"]))
    checks = signal_checks(out, behaviour, cfg, rerun) + hero_checks(
        out, load_heroes(), cfg, employee_ids)
    print("Validation of SYNTHETIC weekly signals and demo heroes\n")
    print_table(checks)
    print(f"\nweekend off in {out.signals['weekend_off'].mean():.1%} of weeks; weekly off skipped "
          f"in {out.signals['weekly_off_skipped'].mean():.1%}; mean task score "
          f"{out.signals['task_score'].mean():.1f}; "
          f"{np.mean(out.signals['leave_before_festival']):.3f} pre-festival leave days per week")
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
