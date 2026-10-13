import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from ml.features.build_features import CENSORED, HORIZON_DAYS, LABEL
from ml.generator.behaviour import DRIVERS, DriverInputs, driver_contributions
from ml.generator.validate_signal import (
    MIN_TRAIN_YEARS,
    MODELS,
    RULE,
    SCORERS,
    driver_frame,
    expanding_probe_splits,
    no_driver_check,
    no_driver_info,
    probe_checks,
    probe_table,
    result_features,
    signal_checks,
    signal_numbers,
    summarise_probes,
)


@pytest.fixture(scope="module")
def feats(cfg, attrition_result) -> pd.DataFrame:
    return result_features(attrition_result, cfg)


@pytest.fixture(scope="module")
def numbers(cfg, attrition_result):
    return signal_numbers(attrition_result, cfg)


def test_expanding_window_with_90_day_gap(feats) -> None:
    splits = expanding_probe_splits(feats)
    usable = feats[~feats[CENSORED]]
    first = int(usable["week_start"].dt.year.min())
    assert [y for y, _, _ in splits][0] == first + MIN_TRAIN_YEARS
    sizes = []
    for year, train, test in splits:
        # all history before the gap, starting at the first data year (expanding)
        assert int(train["week_start"].dt.year.min()) == first
        window_end = train["week_start"] + pd.Timedelta(days=7 + HORIZON_DAYS)
        assert (window_end <= pd.Timestamp(year, 1, 1)).all()
        assert set(test["week_start"].dt.year) == {year}
        assert (train["contract_type"] == "permanent").all()
        assert not train[CENSORED].any() and not test[CENSORED].any()
        sizes.append(len(train))
    assert sizes == sorted(sizes)  # the training set only grows


def test_predictions_have_every_scorer(numbers) -> None:
    preds = numbers.predictions
    assert set(SCORERS) <= set(preds.columns)
    assert preds[list(SCORERS)].notna().all().all()


def _toy(seed: int) -> pd.DataFrame:
    """Two years whose models score on very different scales; ranks make them comparable."""
    rng = np.random.default_rng(seed)
    rows = []
    for year, scale in ((2025, 1.0), (2026, 100.0)):
        label = (rng.random(300) < 0.2).astype(float)
        good = label + rng.normal(0, 0.8, 300)
        rows.append(pd.DataFrame({
            "test_year": year, "employee_id": [f"E{i}" for i in range(300)], "label": label,
            RULE: good * 0.3 + rng.normal(size=300), "lightgbm": good * scale,
            "logistic": good * scale * 0.5,
        }))
    return pd.concat(rows, ignore_index=True)


def test_ranked_pooling_removes_scale_differences() -> None:
    preds = _toy(0)
    s = summarise_probes(preds, ["test_year"])
    per_year = [roc_auc_score(g["label"], g["lightgbm"]) for _, g in preds.groupby("test_year")]
    assert s.scorers["lightgbm"].auc_mean_years == pytest.approx(np.mean(per_year))
    raw_pooled = roc_auc_score(preds["label"], preds["lightgbm"])
    assert s.scorers["lightgbm"].auc_rank_pooled > raw_pooled  # raw pooling is penalised
    assert s.best_model in MODELS
    assert s.gap == pytest.approx(s.best.auc_rank_pooled - s.rule.auc_rank_pooled)


def test_probe_table_traceable(numbers) -> None:
    t = probe_table(numbers.predictions, numbers.probes)
    assert list(t["test_year"])[-2:] == ["(a) mean of years", "(b) ranked pooled"]
    best = numbers.probes.best_model
    assert t.iloc[-1][f"{best}_auc"] == pytest.approx(
        round(numbers.probes.best.auc_rank_pooled, 3))


def test_probe_checks_bands_and_gap() -> None:
    s = summarise_probes(_toy(1), ["test_year"])
    names = [c.name for c in probe_checks(s, "toy")]
    assert len(names) == 3 and any("beats the rule" in n for n in names)


def test_no_driver_gate_and_info(numbers) -> None:
    assert no_driver_check(0.10, "pool").passed
    assert not no_driver_check(0.04, "pool").passed and not no_driver_check(0.25, "pool").passed
    assert "INFO" in no_driver_info(numbers) and "not pass/fail" in no_driver_info(numbers).lower()


def test_driver_frame_matches_scalar_formula(cfg, feats) -> None:
    frame = driver_frame(feats, cfg)
    assert list(frame.columns) == list(DRIVERS)
    row = feats.iloc[123]
    scalar = driver_contributions(DriverInputs(
        overtime_avg=row["overtime_window_mean"], weeks_without_leave=row["weeks_without_leave"],
        pulse_4wk=row["pulse_roll4_mean"], pulse_drop_4wk=-row["pulse_trend_4w"],
        pay_ratio=row["pay_ratio"], months_since_raise=row["months_since_raise"],
        load_ratio=row["load_ratio"], peer_exits=row["peer_exits"],
        tenure_years=row["tenure_days"] / 365.25), cfg.attrition.hazard)
    for drv in DRIVERS:
        assert frame.iloc[123][drv] == pytest.approx(float(scalar[drv]))


def test_signal_checks_exclude_single_seed_no_driver(cfg, attrition_result, numbers) -> None:
    checks = signal_checks(attrition_result, cfg, numbers)
    assert len(checks) == 6
    assert not any("no visible driver" in c.name for c in checks)
    assert LABEL  # label constant importable
