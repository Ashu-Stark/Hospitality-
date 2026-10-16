import numpy as np
import pandas as pd
import pytest

from ml.attrition.features import (
    MODEL_FEATURES,
    SIGNAL_FEATURES,
    build_attrition_features,
    segment_rows,
    signal_features,
)
from ml.attrition.models import (
    PlattCalibrator,
    best_f1_threshold,
    calibration_table,
    classification_metrics,
    rule_score,
)
from ml.attrition.train import backtest_folds, make_fold, run_segment
from ml.features.build_features import CENSORED, HORIZON_DAYS
from ml.generator.heroes import build_heroes
from ml.generator.rng import stream_rngs
from ml.generator.signals import compute_weekly_signals


@pytest.fixture(scope="module")
def features(cfg, generated, attrition_result) -> pd.DataFrame:
    r = attrition_result
    signals = compute_weekly_signals(r.weekly_behaviour, r.latent, generated[0], cfg,
                                     stream_rngs(cfg.seed, "signals")[0])
    return build_attrition_features(r.employees, r.weekly_behaviour, signals, r.exits,
                                    r.contract_renewals, r.pay_changes, cfg)


def test_signal_features_are_trailing() -> None:
    s = pd.DataFrame({
        "employee_id": ["A"] * 6, "week_start": pd.date_range("2029-01-01", periods=6, freq="7D"),
        "task_score": [80.0, 80, 80, 80, 70, 70], "weekly_off_skipped": [True] * 6,
        "weekend_off": [False] * 6, "weeks_since_weekend_off": [1, 2, 3, 4, 5, 6],
        "consecutive_days_worked": [7] * 6, "leave_before_festival": [0, 2, 0, 0, 0, 0]})
    f = signal_features(s, festival_window_weeks=3)
    assert f["weekly_off_skipped_4w"].tolist() == [1, 2, 3, 4, 4, 4]
    assert f["task_score_trend_4w"].tolist() == [0, 0, 0, 0, -10, -10]
    assert f["festival_leave_days_12w"].tolist() == [0, 2, 2, 2, 0, 0]


def test_features_and_segment_labels(features, attrition_result) -> None:
    assert set(MODEL_FEATURES) <= set(features.columns)
    assert not features[SIGNAL_FEATURES].isna().any().any()
    usable = features[~features[CENSORED]]
    # resignations and contract ends are separate labels; together they are the T4 label
    both = usable["label_resignation"] + usable["label_contract_end"]
    assert both.max() <= 1
    perm = segment_rows(features, "resignation")
    seas = segment_rows(features, "contract_end")
    assert (perm["contract_type"] == "permanent").all() and perm["label"].sum() > 0
    assert (seas["contract_type"] == "seasonal").all() and seas["label"].sum() > 0


def test_folds_keep_a_label_gap(features) -> None:
    rows = segment_rows(features, "resignation")
    for fold in backtest_folds(rows, [2027, 2028]):
        window_end = fold.train["week_start"] + pd.Timedelta(days=7 + HORIZON_DAYS)
        assert window_end.max() <= pd.Timestamp(fold.test_year - 1, 1, 1)
        assert (fold.val["week_start"].dt.year == fold.test_year - 1).all()
        assert (fold.test["week_start"].dt.year == fold.test_year).all()
    deployed = make_fold(rows, 2028, None)
    assert deployed.test.empty and (deployed.val["week_start"].dt.year == 2028).all()


def test_rule_score_counts_conditions(cfg) -> None:
    m = cfg.attrition_model
    df = pd.DataFrame({"overtime_window_mean": [0.0, m.rule_sustained_overtime_hours + 1],
                       "weeks_since_weekend_off": [0, m.rule_weeks_without_weekend_off],
                       "pulse_trend_4w": [0.5, -m.rule_pulse_drop - 0.1]})
    assert rule_score(df, m).tolist() == [0.0, 3.0]


@pytest.mark.gpu  # trains a model: GPU only
def test_platt_threshold_and_metrics() -> None:
    rng = np.random.default_rng(0)
    raw = rng.uniform(0.01, 0.99, 2000)
    y = (rng.uniform(size=2000) < raw).astype(int)
    p = PlattCalibrator(on_logit=True).fit(raw, y).transform(raw)
    assert abs(p.mean() - y.mean()) < 0.02 and np.all(np.diff(p[np.argsort(raw)]) >= 0)
    t = best_f1_threshold(y, p)
    m = classification_metrics(y, p, p >= t)
    assert 0.5 < m["roc_auc"] <= 1 and 0 < m["recall"] <= 1
    table = calibration_table(y, p, bins=5)
    assert len(table) == 5 and table["rows"].sum() == 2000
    assert table["observed_rate"].is_monotonic_increasing


@pytest.mark.gpu  # trains a model: GPU only
def test_run_segment_end_to_end(cfg, features) -> None:
    small = cfg.model_copy(update={"attrition_model": cfg.attrition_model.model_copy(
        update={"test_years": [2028]})})
    r = run_segment(features, "resignation", small)
    assert r.winner in r.deployed.names
    assert set(r.metrics["test"]) == {"rules", "logistic", "xgboost"}
    assert r.test_preds["year"].eq(2028).all()
    assert not r.test_preds["employee_id"].str.startswith("H").any()


def test_heroes_are_not_training_rows(cfg, generated, attrition_result, features) -> None:
    r = attrition_result
    heroes, _, _ = build_heroes(cfg, r.dept_week_load_dynamic, generated[0], r.employees)
    assert not set(heroes["employee_id"]) & set(features["employee_id"])
