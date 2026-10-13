from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.features.build_features import build_features
from ml.generator.heroes import HERO_WEEKLY_COLUMNS, build_heroes, load_heroes
from ml.generator.rng import stream_rngs
from ml.generator.run_signals import build_outputs
from ml.generator.signals import (
    SIGNAL_COLUMNS,
    compute_weekly_signals,
    festival_soon,
    leave_records,
    pulse_responses,
)
from ml.generator.validate_heroes import hero_checks, signal_checks
from ml.generator.validate_occupancy import frame_hash


@pytest.fixture(scope="module")
def signals(cfg, generated, attrition_result) -> pd.DataFrame:
    (rng,) = stream_rngs(cfg.seed, "signals")
    r = attrition_result
    return compute_weekly_signals(r.weekly_behaviour, r.latent, generated[0], cfg, rng)


def test_one_row_per_behaviour_row(signals, attrition_result) -> None:
    beh = attrition_result.weekly_behaviour
    assert list(signals.columns) == SIGNAL_COLUMNS and len(signals) == len(beh)
    assert not signals.duplicated(["employee_id", "week_start"]).any()


def test_signal_ranges_and_logic(cfg, signals) -> None:
    s = cfg.signals
    assert signals["task_score"].between(s.task_score_min, s.task_score_max).all()
    assert not (signals["weekly_off_skipped"] & signals["weekend_off"]).any()
    assert (signals["weeks_since_weekend_off"] >= 0).all()
    # a weekend off resets the counter
    assert (signals.loc[signals["weekend_off"], "weeks_since_weekend_off"] == 0).all()


def test_overtime_drives_skipped_offs_and_fatigue(signals, attrition_result) -> None:
    beh = attrition_result.weekly_behaviour.assign(
        week_start=pd.to_datetime(attrition_result.weekly_behaviour["week_start"]))
    m = signals.merge(beh, on=["employee_id", "week_start"])
    busy, calm = m["overtime_hours"] > 10, m["overtime_hours"] == 0
    assert m.loc[busy, "weekly_off_skipped"].mean() > m.loc[calm, "weekly_off_skipped"].mean()


def test_signals_reproducible_and_stream_separate(cfg, generated, attrition_result) -> None:
    r = attrition_result
    a = compute_weekly_signals(r.weekly_behaviour, r.latent, generated[0], cfg,
                               stream_rngs(cfg.seed, "signals")[0])
    b = compute_weekly_signals(r.weekly_behaviour, r.latent, generated[0], cfg,
                               stream_rngs(cfg.seed, "signals")[0])
    pd.testing.assert_frame_equal(a, b)


def test_festival_soon_window() -> None:
    fest = np.array(["2029-11-05"], dtype="datetime64[ns]")
    weeks = pd.Series(pd.to_datetime(["2029-10-15", "2029-10-22", "2029-11-05", "2029-11-12"]))
    # week 10-22 ends 10-28; +10 days reaches 11-07 >= 11-05 -> True; 10-15 reaches 10-31 -> no
    assert festival_soon(weeks, fest, 10).tolist() == [False, True, True, False]


def test_leave_and_pulse_tables_follow_behaviour(signals, attrition_result) -> None:
    beh = attrition_result.weekly_behaviour
    leave = leave_records(beh, signals)
    assert (leave["leave_days"] > 0).all() and leave["leave_days"].sum() == beh["leave_days"].sum()
    assert len(pulse_responses(beh)) == len(beh)


@pytest.fixture(scope="module")
def heroes(cfg, generated, attrition_result):
    r = attrition_result
    return build_heroes(cfg, r.dept_week_load_dynamic, generated[0], r.employees)


def test_heroes_follow_script(cfg, heroes, signals, attrition_result) -> None:
    from ml.generator.run_signals import SignalOutputs

    emp, weekly, names = heroes
    out = SignalOutputs(signals, pd.DataFrame(), pd.DataFrame(), emp, weekly, names)
    checks = hero_checks(out, load_heroes(), cfg, set(attrition_result.employees["employee_id"]))
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]
    assert names == {"H901": "Sunita", "H902": "Rajesh", "H903": "Meena", "H904": "Arun",
                     "H905": "Deepak"}
    assert list(weekly.columns) == HERO_WEEKLY_COLUMNS


def test_display_names_only_in_demo_names(heroes) -> None:
    emp, weekly, names = heroes
    for frame in (emp, weekly):
        text = frame.to_csv(index=False)
        assert not any(name in text for name in names.values())


def test_heroes_never_in_training_features(attrition_result, heroes) -> None:
    r = attrition_result
    feats = build_features(r.employees, r.weekly_behaviour, r.exits, r.contract_renewals,
                           r.pay_changes)
    assert not set(heroes[0]["employee_id"]) & set(feats["employee_id"])


@pytest.mark.slow
def test_signal_checks_on_written_data(cfg) -> None:
    data = Path(__file__).resolve().parents[1] / "data"
    if not (data / "internal" / "employee_latent.csv").exists():  # gitignored: fresh clone
        pytest.skip("requires data/internal/employee_latent.csv; run generate first")
    out = build_outputs(cfg, data)
    behaviour = pd.read_csv(data / "weekly_behaviour.csv")
    rerun = frame_hash(pd.concat([out.signals, out.leave, out.pulse], keys=["s", "l", "p"]))
    assert all(c.passed for c in signal_checks(out, behaviour, cfg, rerun))
