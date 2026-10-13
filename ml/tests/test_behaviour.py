from datetime import date

import numpy as np
import pytest

from ml.generator.behaviour import (
    DRIVERS,
    DriverInputs,
    compute_exit_hazard,
    compute_weekly_leave,
    compute_weekly_overtime,
    compute_weekly_pulse,
    draw_raise,
    draw_vacancy_days,
    driver_contributions,
    pulse_target,
)
from ml.generator.config import HazardConfig


@pytest.fixture
def a(cfg):
    return cfg.attrition


def _quiet(a):
    """Same config with no pulse noise, so pulse is exactly hand-computable."""
    return a.model_copy(update={"pulse_noise_sd": 0.0})


# --- overtime ---------------------------------------------------------------------------


@pytest.mark.parametrize("load", [0.5, 0.99, 1.0])
def test_no_overtime_at_or_below_trigger(a, load: float) -> None:
    assert compute_weekly_overtime(np.random.default_rng(0), 1.0, load, 48, a) == 0.0


def test_overtime_mean_and_cap(a) -> None:
    rng = np.random.default_rng(1)
    # load 1.1, propensity 1, 48h -> mean 0.1 * 48 = 4.8 hours
    ot = np.array([compute_weekly_overtime(rng, 1.0, 1.1, 48, a) for _ in range(20_000)])
    assert ot.mean() == pytest.approx(4.8, rel=0.03)
    big = [compute_weekly_overtime(rng, 2.0, 2.0, 48, a) for _ in range(500)]
    assert max(big) == a.overtime_hours_cap_weekly and min(big) >= 0


def test_zero_propensity_no_overtime(a) -> None:
    assert compute_weekly_overtime(np.random.default_rng(0), 0.0, 1.5, 48, a) == 0.0


# --- pulse ------------------------------------------------------------------------------


def test_pulse_target_hand_values(a) -> None:
    # load 1.0 -> no load drift; 0 overtime; frustration 0 -> target is the baseline
    assert pulse_target(3.8, 0.0, 1.0, 0.0, a) == pytest.approx(3.8)
    # 3.8 - 0.2 + (-1.2 * 0.5) + (-0.05 * 10) = 2.5
    assert pulse_target(3.8, 0.2, 1.5, 10.0, a) == pytest.approx(2.5)


def test_pulse_steady_at_baseline_when_unloaded(a) -> None:
    p = compute_weekly_pulse(np.random.default_rng(0), 3.8, 0.0, 1.0, 0.0, None, _quiet(a))
    assert p == pytest.approx(3.8)


def test_pulse_autocorrelated_step(a) -> None:
    # prev 4.0, target 3.8 - 0.6 = 3.2 -> 0.7 * 4.0 + 0.3 * 3.2 = 3.76
    p = compute_weekly_pulse(np.random.default_rng(0), 3.8, 0.0, 1.5, 0.0, 4.0, _quiet(a))
    assert p == pytest.approx(3.76)


def test_pulse_clipped(a) -> None:
    rng = np.random.default_rng(0)
    assert compute_weekly_pulse(rng, 1.0, 2.0, 3.0, 20.0, 1.0, _quiet(a)) == 1.0
    assert compute_weekly_pulse(rng, 5.0, -2.0, 1.0, 0.0, 5.0, _quiet(a)) == 5.0


def test_pulse_noise_reproducible(a) -> None:
    args = (3.8, 0.1, 1.2, 5.0, 3.5, a)
    p1 = compute_weekly_pulse(np.random.default_rng(5), *args)
    p2 = compute_weekly_pulse(np.random.default_rng(5), *args)
    assert p1 == p2


# --- leave ------------------------------------------------------------------------------


def test_leave_rate_matches_annual_mean(a) -> None:
    rng = np.random.default_rng(2)
    days = [compute_weekly_leave(rng, date(2024, 3, 4), a) for _ in range(52 * 400)]
    assert sum(days) / 400 == pytest.approx(a.leave_days_per_year_mean, rel=0.05)
    assert 0 <= min(days) and max(days) <= 6


def test_leave_zero_in_blocked_week(a) -> None:
    blocked = a.model_copy(
        update={"leave_seasonal_block_weeks": [22], "leave_days_per_year_mean": 300}
    )
    monday_week_22 = date(2024, 5, 27)
    assert monday_week_22.isocalendar().week == 22
    rng = np.random.default_rng(0)
    assert all(compute_weekly_leave(rng, monday_week_22, blocked) == 0 for _ in range(50))


# --- exit hazard (Task T4: logistic driver model) ----------------------------------------


@pytest.fixture
def hz() -> HazardConfig:
    """Fixed hazard settings, NOT read from config.yaml, so the hand-checked values below
    survive recalibration. Every coefficient is 1.0 to make the arithmetic easy."""
    return HazardConfig(
        overtime_window_weeks=10, overtime_ref_hours=4, coef_overtime_per_hour=1.0,
        no_leave_ref_weeks=8, coef_no_leave_per_week=1.0,
        low_pulse_ref=3.5, coef_low_pulse=1.0,
        pulse_drop_ref=0.3, coef_pulse_drop=1.0,
        pay_ratio_ref=1.0, coef_pay_gap=1.0,
        stalled_ref_months=18, coef_stalled_per_month=1.0,
        load_ref=1.0, coef_load=1.0,
        peer_exit_window_weeks=8, coef_peer_exit=1.0,
        new_hire_years=1.0, coef_new_hire=1.0,
        coef_latent_frustration=1.0, noise_sd=0.3, max_weekly_hazard=0.5,
    )


def _inputs(**over) -> DriverInputs:
    """A calm employee-week (no driver active) with selected fields overridden."""
    base = dict(overtime_avg=0.0, weeks_without_leave=0, pulse_4wk=4.0, pulse_drop_4wk=0.0,
                pay_ratio=1.1, months_since_raise=6.0, load_ratio=0.9, peer_exits=0,
                tenure_years=3.0)
    return DriverInputs(**{**base, **over})


def test_calm_week_has_no_driver(hz) -> None:
    assert all(v == 0 for v in driver_contributions(_inputs(), hz).values())
    assert set(driver_contributions(_inputs(), hz)) == set(DRIVERS)


@pytest.mark.parametrize(("field", "value", "driver", "expected"), [
    ("overtime_avg", 10.0, "overtime", 6.0),          # 10 - 4
    ("weeks_without_leave", 11, "no_leave", 3.0),     # 11 - 8
    ("pulse_4wk", 2.5, "low_pulse", 1.0),             # 3.5 - 2.5
    ("pulse_drop_4wk", 1.3, "pulse_drop", 1.0),       # 1.3 - 0.3
    ("pay_ratio", 0.8, "pay_gap", 0.2),               # 1.0 - 0.8
    ("months_since_raise", 24.0, "stalled", 6.0),     # 24 - 18
    ("load_ratio", 1.25, "load", 0.25),               # 1.25 - 1.0
    ("peer_exits", 2, "peer_exits", 2.0),
    ("tenure_years", 0.5, "new_hire", 1.0),
])
def test_each_driver_by_hand(hz, field, value, driver, expected) -> None:
    contrib = driver_contributions(_inputs(**{field: value}), hz)
    assert contrib[driver] == pytest.approx(expected)
    assert sum(v for k, v in contrib.items() if k != driver) == 0


def test_driver_contributions_vectorised(hz) -> None:
    d = _inputs(overtime_avg=np.array([0.0, 10.0]), tenure_years=np.array([0.5, 3.0]))
    c = driver_contributions(d, hz)
    assert c["overtime"].tolist() == [0.0, 6.0] and c["new_hire"].tolist() == [1.0, 0.0]


def test_hazard_is_sigmoid_of_logit(hz) -> None:
    calm = driver_contributions(_inputs(), hz)
    assert compute_exit_hazard(0.0, calm, 0.0, 0.0, hz) == pytest.approx(0.5)  # capped at 0.5
    # logit = -5 + 0 + 1.0 * 0.5 (frustration) + 0.2 (noise) = -4.3
    assert compute_exit_hazard(-5.0, calm, 0.5, 0.2, hz) == pytest.approx(1 / (1 + np.exp(4.3)))


def test_drivers_raise_hazard(hz) -> None:
    calm = compute_exit_hazard(-6.0, driver_contributions(_inputs(), hz), 0.0, 0.0, hz)
    busy = compute_exit_hazard(
        -6.0, driver_contributions(_inputs(overtime_avg=6.0), hz), 0.0, 0.0, hz
    )
    # +2 on the logit: odds multiply by e^2
    assert busy / (1 - busy) == pytest.approx(calm / (1 - calm) * np.exp(2.0))


def test_hazard_capped(hz) -> None:
    hot = driver_contributions(_inputs(overtime_avg=20.0), hz)
    assert compute_exit_hazard(5.0, hot, 2.0, 1.0, hz) == hz.max_weekly_hazard


# --- raises -----------------------------------------------------------------------------


def test_no_raise_before_eligible(a) -> None:
    always = a.raises.model_copy(update={"weekly_prob_when_eligible": 1.0})
    rng = np.random.default_rng(0)
    assert draw_raise(rng, always.eligible_after_months - 1, always) == 0.0
    assert draw_raise(rng, always.eligible_after_months, always) > 0.0


def test_raise_rate_and_size(a) -> None:
    r = a.raises
    rng = np.random.default_rng(1)
    pcts = np.array([draw_raise(rng, 24.0, r) for _ in range(20_000)])
    assert (pcts > 0).mean() == pytest.approx(r.weekly_prob_when_eligible, abs=0.005)
    assert pcts[pcts > 0].mean() == pytest.approx(r.pct_mean, abs=0.003)


# --- vacancy ----------------------------------------------------------------------------


def test_vacancy_days_range_and_mean(a) -> None:
    rng = np.random.default_rng(3)
    gaps = np.array([draw_vacancy_days(rng, a) for _ in range(20_000)])
    assert gaps.min() >= a.vacancy_days_min and gaps.max() <= a.vacancy_days_max
    assert 8.5 < gaps.mean() < 10.5
