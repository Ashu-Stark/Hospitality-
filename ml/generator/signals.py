"""Extra weekly SYNTHETIC signals (Task T5), derived after the attrition simulation.

One row per weekly_behaviour row (same employee_id, week_start), generated from the "signals"
random stream, so earlier outputs (T2-T4) never change. The signals are observable consequences
of the same overtime and leave that drive exits; they do NOT feed the exit hazard.

  task_score              latent baseline_task_score - fatigue * max(window overtime - ref, 0)
                          + noise, clipped (the baseline is generator-only; the output is not)
  weekly_off_skipped      no weekly day off this week; P = sigmoid(base + per_hour * overtime)
  weekend_off             a 2-day weekend off: leave of >= 2 days, or a weekly off that falls on
                          Sat/Sun (weekend_off_share of weekly offs)
  weeks_since_weekend_off consecutive weeks up to this one without a weekend off
  consecutive_days_worked days worked since the last day off (weekly off or leave), at week end
  leave_before_festival   leave days this week when a festival day falls within the week or the
                          festival_lookahead_days after it

Known limitation: the T4 leave process does not cluster leave before festivals (changing it
would change T4 outputs), so leave_before_festival measures the existing, unclustered leave.
Clustering is visible only in the scripted demo heroes.

Derived tables (consistent with the exit process by construction: built from the same rows):
  leave_records    one row per employee-week with leave_days > 0
  pulse_responses  one row per employee-week with a pulse score (every employed week)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.generator.config import GeneratorConfig

SIGNAL_COLUMNS = [
    "employee_id",
    "week_start",
    "task_score",
    "weekly_off_skipped",
    "weekend_off",
    "weeks_since_weekend_off",
    "consecutive_days_worked",
    "leave_before_festival",
]
DAYS_PER_WEEK = 7
WEEKEND_LEAVE_DAYS = 2  # leave of at least this many days covers a weekend


def festival_dates(calendar: pd.DataFrame) -> np.ndarray:
    cal = calendar.assign(date=pd.to_datetime(calendar["date"]))
    return np.sort(cal.loc[cal["is_festival"].astype(bool), "date"].to_numpy())


def festival_soon(week_start: pd.Series, festivals: np.ndarray, lookahead_days: int) -> np.ndarray:
    """True when a festival day falls in [week_start, week_start + 6 + lookahead]."""
    lo = week_start.to_numpy(dtype="datetime64[ns]")
    hi = lo + np.timedelta64(DAYS_PER_WEEK - 1 + lookahead_days, "D")
    return np.searchsorted(festivals, hi, "right") > np.searchsorted(festivals, lo, "left")


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _running_counters(
    emp: np.ndarray, weekend_off: np.ndarray, day_off: np.ndarray, off_pos: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Per-employee weeks_since_weekend_off and consecutive_days_worked (rows sorted)."""
    weeks, days = np.zeros(len(emp), dtype=int), np.zeros(len(emp), dtype=int)
    prev_emp, w, d = None, 0, 0
    for i in range(len(emp)):
        if emp[i] != prev_emp:
            prev_emp, w, d = emp[i], 0, 0
        w = 0 if weekend_off[i] else w + 1
        d = int(off_pos[i]) if day_off[i] else d + DAYS_PER_WEEK
        weeks[i], days[i] = w, d
    return weeks, days


def compute_weekly_signals(
    behaviour: pd.DataFrame,
    latent: pd.DataFrame,
    calendar: pd.DataFrame,
    cfg: GeneratorConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """SIGNAL_COLUMNS for every weekly_behaviour row (see module docstring)."""
    s = cfg.signals
    window = cfg.attrition.hazard.overtime_window_weeks
    beh = behaviour.assign(week_start=pd.to_datetime(behaviour["week_start"]))
    beh = beh.sort_values(["employee_id", "week_start"]).reset_index(drop=True)
    n = len(beh)

    sustained = beh.groupby("employee_id")["overtime_hours"].transform(
        lambda x: x.rolling(window, min_periods=1).mean()).to_numpy()
    baseline = beh["employee_id"].map(latent.set_index("employee_id")["baseline_task_score"])
    fatigue = s.task_fatigue_per_hour * np.maximum(sustained - s.task_fatigue_ref_hours, 0.0)
    task = np.clip(baseline.to_numpy() - fatigue + rng.normal(0.0, s.task_noise_sd, n),
                   s.task_score_min, s.task_score_max)

    overtime = beh["overtime_hours"].to_numpy()
    leave = beh["leave_days"].to_numpy()
    p_skip = _sigmoid(s.skip_weekly_off_base_logit + s.skip_weekly_off_per_overtime_hour * overtime)
    skipped = (rng.random(n) < p_skip) & (leave == 0)
    weekend_draw = rng.random(n) < s.weekend_off_share
    weekend_off = (leave >= WEEKEND_LEAVE_DAYS) | (~skipped & weekend_draw)
    day_off = ~skipped | (leave > 0)
    off_pos = rng.integers(0, DAYS_PER_WEEK, n)  # days worked after the last day off this week
    weeks_since, consecutive = _running_counters(
        beh["employee_id"].to_numpy(), weekend_off, day_off, off_pos)

    soon = festival_soon(beh["week_start"], festival_dates(calendar), s.festival_lookahead_days)
    return pd.DataFrame({
        "employee_id": beh["employee_id"],
        "week_start": beh["week_start"],
        "task_score": task.round(1),
        "weekly_off_skipped": skipped,
        "weekend_off": weekend_off,
        "weeks_since_weekend_off": weeks_since,
        "consecutive_days_worked": consecutive,
        "leave_before_festival": np.where(soon, leave, 0),
    })[SIGNAL_COLUMNS]


def leave_records(behaviour: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """One row per employee-week with leave (from the same rows as weekly_behaviour)."""
    merged = behaviour.assign(week_start=pd.to_datetime(behaviour["week_start"])).merge(
        signals[["employee_id", "week_start", "leave_before_festival"]],
        on=["employee_id", "week_start"], how="left", validate="one_to_one")
    took = merged[merged["leave_days"] > 0]
    return took[["employee_id", "week_start", "leave_days", "leave_before_festival"]]


def pulse_responses(behaviour: pd.DataFrame) -> pd.DataFrame:
    """One pulse response per employed employee-week (none after an exit)."""
    beh = behaviour.assign(week_start=pd.to_datetime(behaviour["week_start"]))
    return beh[["employee_id", "week_start", "department", "pulse_score"]]
