from datetime import date, timedelta

import pandas as pd
import pytest

from ml.features.build_features import (
    CENSORED,
    CONTRACT_END_CAP_DAYS,
    FEATURES,
    HORIZON_DAYS,
    LABEL,
    LATENT_NAMES,
    build_features,
    days_until_contract_end,
    peer_exit_counts,
)
from ml.generator.staff import LATENT_COLUMNS

MONDAY = date(2024, 1, 1)
N_WEEKS = 30  # data ends 2024-07-29 (day after the last week)


def _employees() -> pd.DataFrame:
    return pd.DataFrame({
        "employee_id": ["E1", "E2"],
        "department": ["kitchen", "security"],
        "role": ["cook", "guard"],
        "is_department_head": [False, False],
        "manager_id": ["E0", "E0"],
        "hire_date": ["2023-01-01", "2023-06-01"],
        "contract_type": ["permanent", "seasonal"],
        "contract_end_date": ["", "2024-12-31"],
        "monthly_pay": [24000, 13000],
        "last_raise_date": ["2023-01-01", "2023-06-01"],
    })


def _behaviour(e2_exit_week: int, e1_leave_weeks: tuple[int, ...] = ()) -> pd.DataFrame:
    """E1 active all weeks (pulse and overtime = week number, leave only in e1_leave_weeks);
    E2 exits in week e2_exit_week (1-based)."""
    rows = []
    for w in range(1, N_WEEKS + 1):
        ws = MONDAY + timedelta(weeks=w - 1)
        leave = 1 if w in e1_leave_weeks else 0
        rows.append(("E1", ws, "kitchen", "cook", 1.0, float(w), float(w), leave, True))
        if w <= e2_exit_week:
            rows.append(("E2", ws, "security", "guard", 0.9, 0.0, 3.0, 0, w < e2_exit_week))
    return pd.DataFrame(rows, columns=[
        "employee_id", "week_start", "department", "role", "load_ratio", "overtime_hours",
        "pulse_score", "leave_days", "is_active",
    ])


def _exits(day: str) -> pd.DataFrame:
    return pd.DataFrame({"employee_id": ["E2"], "exit_date": [day],
                         "exit_reason": ["resignation"]})


@pytest.fixture
def mini() -> pd.DataFrame:
    # E2 exits Wednesday 2024-05-15 (week 20, week_start 2024-05-13).
    return build_features(_employees(), _behaviour(20), _exits("2024-05-15"))


def test_horizon_is_90_days() -> None:
    assert HORIZON_DAYS == 90 and CONTRACT_END_CAP_DAYS == 90


def test_active_rows_and_censoring(mini: pd.DataFrame) -> None:
    e1 = mini[mini["employee_id"] == "E1"]
    e2 = mini[mini["employee_id"] == "E2"]
    # E1: all 30 weeks active. E2: weeks 1-19 (week 20 is the exit week, so no row).
    assert len(e1) == 30 and len(e2) == 19
    # Censored when week_start + 7 + 90 > 2024-07-29, i.e. week_start >= 2024-04-29 (week 18).
    assert (e1[CENSORED] == (e1["week_start"] >= pd.Timestamp("2024-04-29"))).all()
    assert e1[CENSORED].sum() == 13 and e2[CENSORED].sum() == 2
    assert mini.loc[mini[CENSORED], LABEL].isna().all()
    assert mini.loc[~mini[CENSORED], LABEL].notna().all()


def test_labels_by_hand(mini: pd.DataFrame) -> None:
    # Window [ws + 7, ws + 97) contains 2024-05-15  <=>  2024-02-08 < ws <= 2024-05-08.
    e2 = mini[(mini["employee_id"] == "E2") & ~mini[CENSORED]].set_index("week_start")[LABEL]
    assert (e2.loc[:"2024-02-05"] == 0).all() and len(e2.loc[:"2024-02-05"]) == 6
    assert (e2.loc["2024-02-12":] == 1).all() and len(e2.loc["2024-02-12":]) == 11
    e1 = mini[(mini["employee_id"] == "E1") & ~mini[CENSORED]]
    assert (e1[LABEL] == 0).all()


@pytest.mark.parametrize(("offset_days", "expected"),
                         [(6, None), (7, 1), (HORIZON_DAYS + 6, 1), (HORIZON_DAYS + 7, 0)])
def test_label_window_edges(offset_days: int, expected: int | None) -> None:
    exit_date = MONDAY + timedelta(days=offset_days)
    exit_week = offset_days // 7 + 1
    feats = build_features(_employees(), _behaviour(exit_week), _exits(exit_date.isoformat()))
    row = feats[(feats["employee_id"] == "E2") & (feats["week_start"] == pd.Timestamp(MONDAY))]
    if expected is None:
        assert row.empty  # exit in the same week as the row: the row is not active
    else:
        assert row[LABEL].item() == expected


def test_rolling_features_by_hand(mini: pd.DataFrame) -> None:
    e1 = mini[mini["employee_id"] == "E1"].reset_index(drop=True)
    # pulse = overtime = week number: roll4 at week 4 = mean(1..4) = 2.5; week 1 = 1.
    assert e1.loc[0, "pulse_roll4_mean"] == 1.0
    assert e1.loc[3, "pulse_roll4_mean"] == pytest.approx(2.5)
    assert e1.loc[3, "overtime_roll4_mean"] == pytest.approx(2.5)
    # trend = pulse - pulse 4 weeks earlier: 0 until week 5, then 4.
    assert (e1.loc[:3, "pulse_trend_4w"] == 0).all()
    assert e1.loc[4, "pulse_trend_4w"] == pytest.approx(4.0)


def test_weeks_without_leave_by_hand() -> None:
    feats = build_features(_employees(), _behaviour(20, e1_leave_weeks=(3,)),
                           _exits("2024-05-15"))
    e1 = feats[feats["employee_id"] == "E1"]["weeks_without_leave"].tolist()
    assert e1[:6] == [1, 2, 0, 1, 2, 3]  # resets to 0 in the leave week


def test_rolling_uses_only_past() -> None:
    no_exits = pd.DataFrame(columns=["employee_id", "exit_date", "exit_reason"])
    beh = _behaviour(20)
    future_changed = beh.copy()
    future_changed.loc[future_changed["week_start"] > date(2024, 2, 1), "pulse_score"] = 1.0
    a = build_features(_employees(), beh, no_exits)
    b = build_features(_employees(), future_changed, no_exits)
    early = a["week_start"] <= pd.Timestamp("2024-02-01")
    pd.testing.assert_frame_equal(a[early], b[early])


def test_static_and_pay_features_by_hand(mini: pd.DataFrame) -> None:
    first = mini[(mini["employee_id"] == "E1")].iloc[0]
    assert first["tenure_days"] == 365  # 2023-01-01 -> 2024-01-01
    assert first["months_since_raise"] == pytest.approx(365 / 30.44, abs=0.01)
    assert first["monthly_pay"] == 24000 and first["pay_ratio"] == pytest.approx(1.0)
    assert first["is_department_head"] == 0 and first["contract_type"] == "permanent"


def test_pay_changes_are_point_in_time() -> None:
    raises = pd.DataFrame({"employee_id": ["E1"], "effective_date": ["2024-02-05"],
                           "monthly_pay": [26400]})
    feats = build_features(_employees(), _behaviour(20), _exits("2024-05-15"), None, raises)
    e1 = feats[feats["employee_id"] == "E1"].set_index("week_start")
    assert e1.loc["2024-01-29", "monthly_pay"] == 24000  # before the raise
    assert e1.loc["2024-02-05", "monthly_pay"] == 26400  # raise effective this week
    assert e1.loc["2024-02-05", "pay_ratio"] == pytest.approx(1.1)
    assert e1.loc["2024-02-05", "months_since_raise"] == 0
    assert e1.loc["2024-02-12", "months_since_raise"] == pytest.approx(7 / 30.44, abs=0.01)


def test_peer_exit_counts_by_hand() -> None:
    emp = pd.DataFrame({"employee_id": ["A", "B", "C"],
                        "department": ["kitchen", "kitchen", "security"]})
    exits = pd.DataFrame({"employee_id": ["A", "C"],
                          "exit_date": ["2024-02-01", "2024-02-01"]})
    rows = pd.DataFrame({"employee_id": ["B", "B", "B"], "department": ["kitchen"] * 3,
                         "week_start": pd.to_datetime(["2024-01-29", "2024-02-05",
                                                       "2024-04-01"])})
    # A (kitchen) left 2024-02-01: inside [ws - 8 weeks, ws) only for 2024-02-05.
    # C left on the same day but is in security, so never counted for kitchen.
    assert peer_exit_counts(rows, emp, exits, 8).tolist() == [0, 1, 0]


def test_no_latent_columns_anywhere(attrition_result) -> None:
    r = attrition_result
    feats = build_features(r.employees, r.weekly_behaviour, r.exits, r.contract_renewals,
                           r.pay_changes)
    assert set(LATENT_NAMES) == set(LATENT_COLUMNS)
    for col in feats.columns:
        assert not any(name in col for name in LATENT_NAMES), col
    assert not set(LATENT_COLUMNS) & set(FEATURES)


def test_real_data_shape(attrition_result) -> None:
    r = attrition_result
    feats = build_features(r.employees, r.weekly_behaviour, r.exits, r.contract_renewals,
                           r.pay_changes)
    assert not feats[FEATURES].isna().any().any()
    usable = feats[~feats[CENSORED]]
    assert set(usable[LABEL].unique()) == {0, 1}
    assert 0.01 < usable[LABEL].mean() < 0.30
    assert feats.loc[feats[CENSORED], LABEL].isna().all()


# --- days_until_contract_end -----------------------------------------------------------


def _contract_rows() -> tuple[pd.DataFrame, pd.DataFrame]:
    emp = pd.DataFrame({"employee_id": ["S1", "P1"], "contract_end_date": ["2024-02-07", ""]})
    rows = pd.DataFrame({
        "employee_id": ["S1", "S1", "S1", "S1", "S1", "P1"],
        "week_start": pd.to_datetime(
            ["2024-01-29", "2024-02-05", "2024-02-12", "2024-06-10", "2024-07-08", "2024-02-12"]
        ),
    })
    return emp, rows


def test_days_until_contract_end_seasonal_by_hand() -> None:
    """S1's contract ends Wed 2024-02-07 and is renewed that day to 2024-06-30, then again on
    2024-06-30 to 2024-10-31."""
    emp, rows = _contract_rows()
    renewals = pd.DataFrame({
        "employee_id": ["S1", "S1"],
        "renewal_date": ["2024-02-07", "2024-06-30"],
        "new_contract_end_date": ["2024-06-30", "2024-10-31"],
    })
    days = days_until_contract_end(rows, emp, renewals).tolist()
    assert CONTRACT_END_CAP_DAYS == 90
    assert days == [
        9,   # 2024-01-29 -> 2024-02-07, original contract
        2,   # 2024-02-05: renewal on 02-07 is AFTER week_start, so not yet known
        90,  # 2024-02-12 -> 2024-06-30 is 139 days, first renewal known; capped at 90
        20,  # 2024-06-10 -> 2024-06-30, under the cap
        90,  # 2024-07-08 -> 2024-10-31 is 115 days (second renewal known); capped
        90,  # permanent staff: always the cap
    ]


def test_days_until_contract_end_ignores_future_renewals() -> None:
    emp, rows = _contract_rows()
    none = pd.DataFrame(columns=["employee_id", "renewal_date", "new_contract_end_date"])
    future = pd.DataFrame({"employee_id": ["S1"], "renewal_date": ["2024-03-01"],
                           "new_contract_end_date": ["2024-06-30"]})
    a = days_until_contract_end(rows.iloc[:2], emp, none).tolist()
    b = days_until_contract_end(rows.iloc[:2], emp, future).tolist()
    assert a == b == [9, 2]


def test_contract_feature_in_matrix(attrition_result) -> None:
    r = attrition_result
    feats = build_features(r.employees, r.weekly_behaviour, r.exits, r.contract_renewals)
    seasonal = feats["contract_type"] == "seasonal"
    assert (feats.loc[~seasonal, "days_until_contract_end"] == CONTRACT_END_CAP_DAYS).all()
    assert feats.loc[seasonal, "days_until_contract_end"].between(0, CONTRACT_END_CAP_DAYS).all()
    assert (feats.loc[seasonal, "days_until_contract_end"] < CONTRACT_END_CAP_DAYS).any()
