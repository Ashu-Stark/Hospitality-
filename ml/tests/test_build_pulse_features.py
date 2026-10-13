from datetime import date, timedelta

import pandas as pd
import pytest

from ml.features.build_features import CONTRACT_END_CAP_DAYS
from ml.features.build_pulse_features import (
    LATENT_NAMES,
    PULSE_FEATURES,
    PULSE_LABEL,
    build_pulse_features,
)
from ml.generator.staff import LATENT_COLUMNS

MONDAY = date(2024, 1, 1)


def _week(n: int) -> date:
    """1-based week number -> week_start."""
    return MONDAY + timedelta(weeks=n - 1)


def _employees() -> pd.DataFrame:
    return pd.DataFrame({
        "employee_id": ["A", "B", "C"],
        "department": ["kitchen", "security", "kitchen"],
        "role": ["cook", "guard", "helper"],
        "is_department_head": [False, False, False],
        "manager_id": ["H", "H", "H"],
        "hire_date": ["2023-01-01", "2023-06-01", "2023-03-01"],
        "contract_type": ["permanent", "seasonal", "permanent"],
        "contract_end_date": ["", "2024-02-07", ""],
        "monthly_pay": [24000, 13000, 13000],
        "last_raise_date": ["2023-01-01", "2023-06-01", "2023-03-01"],
    })


def _row(emp: str, week: int, pulse: float, active: bool = True) -> tuple:
    return (emp, _week(week), "kitchen", "cook", 1.0, 0.0, pulse, 0, active)


def _behaviour() -> pd.DataFrame:
    """A: weeks 1-6, pulse = week number. B: exits in week 5 (is_active False), pulse = 10 x
    week. C: weeks 1, 2, 4 (a gap at week 3)."""
    rows = [_row("A", w, float(w)) for w in range(1, 7)]
    rows += [_row("B", w, 10.0 * w, active=w < 5) for w in range(1, 6)]
    rows += [_row("C", w, 3.0) for w in (1, 2, 4)]
    return pd.DataFrame(rows, columns=[
        "employee_id", "week_start", "department", "role", "load_ratio", "overtime_hours",
        "pulse_score", "leave_days", "is_active",
    ])


@pytest.fixture
def mini() -> pd.DataFrame:
    return build_pulse_features(_employees(), _behaviour())


def _labels(feats: pd.DataFrame, emp: str) -> dict[date, float]:
    part = feats[feats["employee_id"] == emp]
    return dict(zip(part["week_start"].dt.date, part[PULSE_LABEL], strict=True))


def test_label_is_next_week_pulse(mini: pd.DataFrame) -> None:
    # A: week 1 has no history, week 6 has no next week -> rows for weeks 2-5.
    assert _labels(mini, "A") == {_week(2): 3.0, _week(3): 4.0, _week(4): 5.0, _week(5): 6.0}
    a = mini[mini["employee_id"] == "A"]
    assert (a[PULSE_LABEL] == a["pulse_score"] + 1).all()


def test_week_before_exit_and_exit_week_dropped(mini: pd.DataFrame) -> None:
    # B: week 4's next week is the exit week (inactive) -> dropped; week 5 is the exit week.
    assert _labels(mini, "B") == {_week(2): 30.0, _week(3): 40.0}


def test_non_consecutive_next_week_dropped(mini: pd.DataFrame) -> None:
    # C: week 2's next row is week 4 (gap) -> no valid label; week 4 is last -> dropped.
    assert _labels(mini, "C") == {}


def test_features_by_hand(mini: pd.DataFrame) -> None:
    a = mini[mini["employee_id"] == "A"].set_index(mini.loc[mini["employee_id"] == "A",
                                                            "week_start"].dt.date)
    assert a.loc[_week(4), "pulse_roll4_mean"] == pytest.approx(2.5)  # mean(1, 2, 3, 4)
    assert a.loc[_week(5), "pulse_trend_4w"] == pytest.approx(4.0)  # 5 - 1
    assert a.loc[_week(4), "pulse_trend_4w"] == 0.0  # fewer than 5 weeks of history
    assert a.loc[_week(2), "tenure_days"] == (_week(2) - date(2023, 1, 1)).days
    assert (a["days_until_contract_end"] == CONTRACT_END_CAP_DAYS).all()  # permanent
    b = mini[mini["employee_id"] == "B"].set_index(mini.loc[mini["employee_id"] == "B",
                                                            "week_start"].dt.date)
    assert b.loc[_week(2), "days_until_contract_end"] == 30  # 2024-01-08 -> 2024-02-07


def test_columns(mini: pd.DataFrame) -> None:
    assert list(mini.columns) == ["employee_id", "week_start", *PULSE_FEATURES, PULSE_LABEL]


def test_no_latent_columns_anywhere(attrition_result) -> None:
    r = attrition_result
    feats = build_pulse_features(r.employees, r.weekly_behaviour, r.contract_renewals)
    assert set(LATENT_NAMES) == set(LATENT_COLUMNS)
    for col in feats.columns:
        assert not any(name in col for name in LATENT_NAMES), col
    assert not set(LATENT_COLUMNS) & set(PULSE_FEATURES)


def test_real_data_label_matches_behaviour(attrition_result) -> None:
    r = attrition_result
    feats = build_pulse_features(r.employees, r.weekly_behaviour, r.contract_renewals)
    beh = r.weekly_behaviour.assign(week_start=pd.to_datetime(r.weekly_behaviour["week_start"]))
    pulse = beh.set_index(["employee_id", "week_start"])["pulse_score"]
    sample = feats.sample(200, random_state=0)
    nxt = list(zip(sample["employee_id"], sample["week_start"] + pd.Timedelta(days=7),
                   strict=True))
    assert (pulse.loc[nxt].to_numpy() == sample[PULSE_LABEL].to_numpy()).all()
    assert not feats[PULSE_FEATURES + [PULSE_LABEL]].isna().any().any()
