"""Per employee-week SYNTHETIC behaviour: overtime, pulse, leave and exit hazard.

Small pure functions on scalar inputs so each can be tested by hand. The attrition
simulator (attrition.py) calls them once per active employee per week.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from ml.generator.config import AttritionConfig, HazardConfig, RaiseConfig

PULSE_RANGE = (1.0, 5.0)
PULSE_AUTOCORR = 0.7  # pulse_t = 0.7 * pulse_{t-1} + 0.3 * target + noise
OVERTIME_GAMMA_SHAPE = 4.0  # spread of weekly overtime around its mean
WORKDAYS_PER_WEEK = 6
WEEKS_PER_YEAR = 52.0
DAYS_PER_MONTH = 30.44

# Observable resignation drivers, in the order they are reported.
DRIVERS = (
    "overtime",
    "no_leave",
    "low_pulse",
    "pulse_drop",
    "pay_gap",
    "stalled",
    "load",
    "peer_exits",
    "new_hire",
)


@dataclass(frozen=True)
class DriverInputs:
    """Observable state of one employee at the end of one week (all derivable from outputs)."""

    overtime_avg: float  # mean overtime hours over the last hazard.overtime_window_weeks
    weeks_without_leave: int  # consecutive weeks up to and including this one with no leave
    pulse_4wk: float  # mean pulse over this and the previous 3 weeks
    pulse_drop_4wk: float  # pulse 4 weeks ago minus pulse now (0 if < 5 weeks of history)
    pay_ratio: float  # current monthly pay / role pay_mean
    months_since_raise: float
    load_ratio: float
    peer_exits: int  # department exits in the previous peer_exit_window_weeks
    tenure_years: float


def compute_weekly_overtime(
    rng: np.random.Generator,
    overtime_propensity: float,
    load_ratio: float,
    standard_weekly_hours: float,
    cfg: AttritionConfig,
) -> float:
    """Overtime hours this week; 0 unless load_ratio exceeds the trigger.

    Mean = propensity * (load_ratio - trigger) * standard_weekly_hours, i.e. each person
    covers their share of the missing hours scaled by their propensity. Gamma-distributed
    around that mean and capped at overtime_hours_cap_weekly.
    """
    excess = load_ratio - cfg.overtime_trigger_load_ratio
    if excess <= 0:
        return 0.0
    mean = overtime_propensity * excess * standard_weekly_hours
    hours = rng.gamma(OVERTIME_GAMMA_SHAPE, mean / OVERTIME_GAMMA_SHAPE) if mean > 0 else 0.0
    return float(min(hours, cfg.overtime_hours_cap_weekly))


def pulse_target(
    baseline_pulse: float,
    latent_frustration: float,
    load_ratio: float,
    overtime_hours: float,
    cfg: AttritionConfig,
) -> float:
    """Where pulse settles under this week's conditions (before noise and clipping).

    Higher latent_frustration lowers pulse, so it enters as a negative offset.
    """
    return (
        baseline_pulse
        - latent_frustration
        + cfg.pulse_load_sensitivity * max(load_ratio - 1.0, 0.0)
        + cfg.pulse_overtime_sensitivity * overtime_hours
    )


def compute_weekly_pulse(
    rng: np.random.Generator,
    baseline_pulse: float,
    latent_frustration: float,
    load_ratio: float,
    overtime_hours: float,
    prev_pulse: float | None,
    cfg: AttritionConfig,
) -> float:
    """AR(1)-style pulse: 0.7 * previous + 0.3 * target + noise, clipped to [1, 5].

    A new employee's previous pulse is their baseline_pulse.
    """
    prev = baseline_pulse if prev_pulse is None else prev_pulse
    target = pulse_target(baseline_pulse, latent_frustration, load_ratio, overtime_hours, cfg)
    value = PULSE_AUTOCORR * prev + (1 - PULSE_AUTOCORR) * target
    value += rng.normal(0, cfg.pulse_noise_sd)
    return float(np.clip(value, *PULSE_RANGE))


def compute_weekly_leave(rng: np.random.Generator, week_start: date, cfg: AttritionConfig) -> int:
    """Leave days this week: annual rate ~ N(mean, sd) floored at 0, then Poisson(rate / 52).

    Capped at WORKDAYS_PER_WEEK; 0 in any ISO week listed in leave_seasonal_block_weeks.
    """
    annual = max(rng.normal(cfg.leave_days_per_year_mean, cfg.leave_days_per_year_sd), 0.0)
    days = int(min(rng.poisson(annual / WEEKS_PER_YEAR), WORKDAYS_PER_WEEK))
    if week_start.isocalendar().week in cfg.leave_seasonal_block_weeks:
        return 0
    return days


def driver_contributions(d: DriverInputs, h: HazardConfig) -> dict[str, float]:
    """Logit contribution of each observable driver (0 when the driver is inactive).

    Works element-wise too: pass numpy arrays in DriverInputs to get arrays back.
    """
    zero = 0.0
    return {
        "overtime": h.coef_overtime_per_hour * np.maximum(d.overtime_avg - h.overtime_ref_hours,
                                                          zero),
        "no_leave": h.coef_no_leave_per_week * np.maximum(
            np.asarray(d.weeks_without_leave) - h.no_leave_ref_weeks, zero),
        "low_pulse": h.coef_low_pulse * np.maximum(h.low_pulse_ref - d.pulse_4wk, zero),
        "pulse_drop": h.coef_pulse_drop * np.maximum(d.pulse_drop_4wk - h.pulse_drop_ref, zero),
        "pay_gap": h.coef_pay_gap * np.maximum(h.pay_ratio_ref - d.pay_ratio, zero),
        "stalled": h.coef_stalled_per_month * np.maximum(
            d.months_since_raise - h.stalled_ref_months, zero),
        "load": h.coef_load * np.maximum(d.load_ratio - h.load_ref, zero),
        "peer_exits": h.coef_peer_exit * np.asarray(d.peer_exits, dtype=float),
        "new_hire": h.coef_new_hire * (np.asarray(d.tenure_years) < h.new_hire_years).astype(float),
    }


def compute_exit_hazard(
    intercept: float,
    contributions: dict[str, float],
    latent_frustration: float,
    noise: float,
    h: HazardConfig,
) -> float:
    """Weekly resignation probability: sigmoid(intercept + drivers + hidden + noise), capped.

    `noise` is one draw of N(0, h.noise_sd) for this employee-week.
    """
    logit = (
        intercept
        + float(sum(contributions.values()))
        + h.coef_latent_frustration * latent_frustration
        + noise
    )
    return float(min(1.0 / (1.0 + math.exp(-logit)), h.max_weekly_hazard))


def draw_raise(rng: np.random.Generator, months_since_raise: float, r: RaiseConfig) -> float:
    """Raise fraction this week (0 if none).

    Both draws are consumed on every call, so random streams stay aligned.
    """
    happens = rng.random() < r.weekly_prob_when_eligible
    pct = max(rng.normal(r.pct_mean, r.pct_sd), 0.0)
    return pct if happens and months_since_raise >= r.eligible_after_months else 0.0


def draw_vacancy_days(rng: np.random.Generator, cfg: AttritionConfig) -> int:
    """Days from exit to replacement start: min + Exponential(scale = mean - min),
    truncated to [min, max] by inverse CDF, rounded to whole days."""
    lo, hi = cfg.vacancy_days_min, cfg.vacancy_days_max
    scale = cfg.vacancy_days_mean - lo
    u_max = 1 - np.exp(-(hi - lo) / scale)
    gap = lo - scale * np.log(1 - rng.uniform(0, u_max))
    return int(np.clip(round(gap), lo, hi))
