import pandas as pd
import pytest

from ml.features.build_workload_features import (
    WORKLOAD_FEATURES,
    WORKLOAD_LABEL,
    build_workload_features,
    festival_weeks,
)

MONDAY = pd.Timestamp("2024-01-01")
N_WEEKS = 8


def _week(n: int) -> pd.Timestamp:
    """1-based week number -> week_start."""
    return MONDAY + pd.Timedelta(weeks=n - 1)


def _load() -> pd.DataFrame:
    """kitchen load = week / 10, room nights = 100 + week; security load = 0.5 + week / 100.
    Rows deliberately interleaved and out of order to test per-department grouping."""
    rows = []
    for w in range(N_WEEKS, 0, -1):
        rows.append(("security", _week(w), 200, 5, 0.5 + w / 100))
        rows.append(("kitchen", _week(w), 100 + w, 10, w / 10))
    return pd.DataFrame(rows, columns=[
        "department", "week_start", "occupied_room_nights", "headcount", "load_ratio",
    ]).assign(required_hours=1.0, available_hours=1.0)


def _calendar() -> pd.DataFrame:
    days = pd.date_range(_week(1), _week(N_WEEKS) + pd.Timedelta(days=6), freq="D")
    festival = days == pd.Timestamp("2024-02-07")  # Wednesday of week 6
    return pd.DataFrame({"date": days, "is_festival": festival})


@pytest.fixture
def mini() -> pd.DataFrame:
    return build_workload_features(_load(), _calendar())


def _dept(feats: pd.DataFrame, dept: str) -> pd.DataFrame:
    return feats[feats["department"] == dept].set_index("week_start")


def test_rows_need_4_weeks_history_and_a_next_week(mini: pd.DataFrame) -> None:
    # Weeks 1-4 lack 4 earlier weeks; week 8 has no next week -> weeks 5, 6, 7 per department.
    for dept in ("kitchen", "security"):
        assert list(_dept(mini, dept).index) == [_week(5), _week(6), _week(7)]
    assert len(mini) == 6


def test_label_is_next_week_same_department(mini: pd.DataFrame) -> None:
    k, s = _dept(mini, "kitchen"), _dept(mini, "security")
    assert k[WORKLOAD_LABEL].tolist() == pytest.approx([0.6, 0.7, 0.8])
    assert s[WORKLOAD_LABEL].tolist() == pytest.approx([0.56, 0.57, 0.58])
    # Never another department's value: kitchen labels are exactly its own load + 0.1.
    assert (k[WORKLOAD_LABEL] - k["load_ratio"]).tolist() == pytest.approx([0.1] * 3)


def test_rolling_and_trend_by_hand(mini: pd.DataFrame) -> None:
    k = _dept(mini, "kitchen")
    assert k.loc[_week(5), "load_roll4_mean"] == pytest.approx(0.35)  # mean(.2, .3, .4, .5)
    assert k.loc[_week(5), "room_nights_roll4_mean"] == pytest.approx(103.5)  # mean(102..105)
    assert k.loc[_week(5), "load_trend_4w"] == pytest.approx(0.4)  # 0.5 - 0.1
    assert k.loc[_week(5), "week_of_year"] == 5


def test_festival_flags(mini: pd.DataFrame) -> None:
    k = _dept(mini, "kitchen")
    assert k["is_festival_week"].tolist() == [0, 1, 0]  # festival in week 6
    assert k["next_week_is_festival"].tolist() == [1, 0, 0]  # known one week ahead
    fest = festival_weeks(_calendar())
    assert fest[_week(6)] == 1 and fest.sum() == 1


def test_columns(mini: pd.DataFrame) -> None:
    assert list(mini.columns) == ["department", "week_start", *WORKLOAD_FEATURES[1:],
                                  WORKLOAD_LABEL]


def test_real_data(attrition_result, generated) -> None:
    r = attrition_result
    feats = build_workload_features(r.dept_week_load_dynamic, generated[0])
    assert feats["department"].nunique() == 6
    weeks = r.dept_week_load_dynamic["week_start"].nunique()
    assert len(feats) == 6 * (weeks - 4 - 1)
    dyn = r.dept_week_load_dynamic.assign(
        week_start=pd.to_datetime(r.dept_week_load_dynamic["week_start"])
    ).set_index(["department", "week_start"])["load_ratio"]
    nxt = list(zip(feats["department"], feats["week_start"] + pd.Timedelta(days=7), strict=True))
    assert (dyn.loc[nxt].to_numpy() == feats[WORKLOAD_LABEL].to_numpy()).all()
    assert not feats.isna().any().any()
