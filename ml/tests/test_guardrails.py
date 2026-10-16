"""Shared guardrails (ml/guardrails.py) and the guarded entry points of every model
(forecast, attrition, workload; cancellation in test_hotel_alerts.py). SYNTHETIC data."""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml import guardrails as G


@pytest.fixture
def ref() -> dict:
    rng = np.random.default_rng(42)
    train = pd.DataFrame({"x": rng.normal(10, 2, 2000), "c": rng.choice(["a", "b"], 2000)})
    return G.build_reference(train, ["x", "c"], model="toy", trained_on="2026-10-01",
                             training_window="toy")


def test_reference_has_numeric_and_categorical_stats(ref: dict) -> None:
    x, c = ref["features"]["x"], ref["features"]["c"]
    assert x["kind"] == "numeric" and abs(x["mean"] - 10) < 0.2 and len(x["shares"]) == 10
    assert c["kind"] == "categorical" and set(c["shares"]) == {"a", "b"}


def test_schema_and_range_checks_flag_rows() -> None:
    checks: list[G.Check] = []
    df = pd.DataFrame({"occ": [0.5, np.nan, 1.4]})
    assert G.validate_schema(df, ["occ"], checks).tolist() == [False, True, False]
    assert G.validate_ranges(df, {"occ": (0, 1)}, checks).tolist() == [False, False, True]
    assert [c.status for c in checks] == ["warn", "warn"]
    checks2: list[G.Check] = []
    assert G.validate_schema(df, ["nope"], checks2).all() and checks2[0].status == "fail"


def test_ood_needs_both_z_and_range(ref: dict) -> None:
    df = pd.DataFrame({"x": [10.0, 13.0, 60.0], "c": ["a", "b", "zzz"]})
    mask, per = G.ood_rows(df, ref)
    assert mask.tolist() == [False, False, True]
    assert per == {"x": 1, "c": 1}


def test_psi_small_for_same_distribution_large_for_shift(ref: dict) -> None:
    rng = np.random.default_rng(7)
    same = G.psi(ref["features"]["x"], pd.Series(rng.normal(10, 2, 1000)))
    moved = G.psi(ref["features"]["x"], pd.Series(rng.normal(13, 2, 1000)))
    assert same < 0.05 and moved > 0.25


def test_drift_check_psi_only_for_big_batches(ref: dict) -> None:
    rng = np.random.default_rng(1)
    small = pd.DataFrame({"x": rng.normal(13, 2, 50), "c": ["a"] * 50})
    checks: list[G.Check] = []
    _, level = G.drift_check(small, ref, checks)
    assert "PSI skipped" in checks[-1].detail and level == "none"
    big = pd.DataFrame({"x": rng.normal(13, 2, 400), "c": ["a"] * 400})
    checks = []
    _, level = G.drift_check(big, ref, checks)
    assert level == "large" and any(c.name == "drift_psi" and c.status == "warn" for c in checks)


def test_staleness_rejects_old_or_undated_models(ref: dict) -> None:
    checks: list[G.Check] = []
    assert not G.staleness(ref, date(2026, 10, 15), checks)
    assert G.staleness(ref, date(2028, 1, 1), checks)
    assert G.staleness({}, date(2026, 10, 15), checks)
    assert [c.status for c in checks] == ["pass", "fail", "fail"]


def test_clip_bounds_and_nan() -> None:
    checks: list[G.Check] = []
    out = G.clip(np.array([-0.2, 0.5, 1.3, np.nan]), 0, 1, checks, "probability")
    assert out.tolist() == [0.0, 0.5, 1.0, 0.0] and checks[0].status == "warn"


def test_confidence_rule() -> None:
    assert G.confidence(0.10, "none", 0, False) == "high"
    assert G.confidence(0.20, "none", 0, False) == "medium"
    assert G.confidence(0.10, "moderate", 0, False) == "medium"
    assert G.confidence(0.10, "none", 0.1, False) == "medium"
    assert G.confidence(0.10, "large", 0, False) == "low"
    assert G.confidence(0.10, "none", 0, True) == "low"
    assert G.confidence(None, "none", 0, False) == "medium"


def test_every_trigger_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="hoi.guardrails"):
        G.record([], "x", "warn", "something odd", "toy")
        G.record([], "y", "pass", "fine")
    assert len(caplog.records) == 1 and "something odd" in caplog.text


# ------------------------------------------------------------------ guarded models
TODAY = date(2026, 10, 15)


def test_guarded_forecast_matches_predict_when_inputs_are_clean() -> None:
    from ml.forecast import api, guarded

    g = guarded.predict("2029-12-24", "2029-12-27", today=TODAY)
    p = api.predict("2029-12-24", "2029-12-27")
    assert [d.mean for d in g.days] == [d.mean for d in p.days]
    assert not g.fallback_used and g.confidence in ("high", "medium")
    assert all(0 <= d.low <= d.mean <= d.high <= 1 for d in g.days)


def test_guarded_forecast_falls_back_on_bad_or_odd_inputs() -> None:
    from ml.forecast import guarded

    g = guarded.predict("2029-12-24", "2029-12-26", today=TODAY,
                        overrides={"2029-12-25": {"occ_origin": 7.0},
                                   "2029-12-26": {"occ_mean_7": np.nan}})
    src = {d.date.isoformat(): d.source for d in g.days}
    assert src == {"2029-12-24": "model", "2029-12-25": "baseline", "2029-12-26": "baseline"}
    assert g.fallback_used and g.confidence == "low"
    assert {c.name for c in g.checks if c.status == "warn"} >= {"input_range", "fallback"}


def test_guarded_forecast_rejects_a_stale_model() -> None:
    from ml.forecast import guarded

    g = guarded.predict("2029-12-24", "2029-12-25", today=date(2030, 1, 1))
    assert all(d.source == "baseline" for d in g.days) and g.confidence == "low"
    assert any(c.name == "model_age" and c.status == "fail" for c in g.checks)


def test_guarded_attrition_baseline_for_out_of_range_person() -> None:
    from ml.attrition import guarded

    week = "2029-12-24"
    clean = guarded.score(week, ["H901"], today=TODAY)[0]
    assert clean.source == "model" and clean.checks
    odd = guarded.score(week, ["H901"], today=TODAY, overrides={"H901": {"pulse_score": 9.0}})[0]
    assert odd.source == "baseline" and odd.confidence == "low"
    assert odd.risk == pytest.approx(0.0544, abs=1e-4)  # resignation training base rate
    assert any(c.name == "row_fallback" for c in odd.checks)


def test_guarded_rescore_marks_unrealistic_what_if() -> None:
    from ml.attrition import guarded

    r = guarded.rescore("H901", {"overtime_window_mean": 500.0}, today=TODAY)
    assert r.confidence == "low" and any(c.name == "what_if" for c in r.checks)


def test_guarded_workload_bounds_and_baseline_on_stale() -> None:
    from ml.models import workload_api

    w = workload_api.predict_next_week(today=TODAY)
    assert w.departments and all(0 <= d.next_week_load <= 3 for d in w.departments)
    s = workload_api.predict_next_week(today=date(2031, 1, 1))
    assert all(d.source == "baseline" and d.next_week_load == d.this_week_load
               for d in s.departments)


def test_backtest_monitor_runs_and_compares_with_baseline() -> None:
    from ml.eval import backtest_monitor as bm

    data_dir, rooms = bm._data(None)
    f = bm.forecast_backtest(data_dir, rooms, days=10, window=5, horizons=(1,))
    assert f["1d"]["days"] == 10 and isinstance(f["1d"]["warning"], bool)
    w = bm.workload_backtest(data_dir, weeks=2)
    assert w["rows"] > 0 and {"mae_model", "mae_baseline"} <= set(w)
