from datetime import date

import pandas as pd
import pytest

from ml.generator.calendar import build_calendar, in_month_day_range, load_festivals


@pytest.fixture(scope="module")
def cal(cfg) -> pd.DataFrame:
    return build_calendar(cfg).set_index("date")


def test_row_count_and_range(cfg, cal: pd.DataFrame) -> None:
    assert len(cal) == (cfg.property.end - cfg.property.start).days + 1
    assert cal.index.min() == pd.Timestamp(cfg.property.start)
    assert cal.index.max() == pd.Timestamp(cfg.property.end)
    assert cal.index.is_unique


def test_columns(cal: pd.DataFrame) -> None:
    assert list(cal.columns) == [
        "day_of_week",
        "month",
        "is_weekend",
        "is_public_holiday",
        "festival_name",
        "is_festival",
        "is_festival_window",
        "is_char_dham",
        "is_school_holiday",
    ]


@pytest.mark.parametrize(
    ("day", "name"),
    [
        ("2023-03-08", "Holi"),
        ("2024-10-12", "Dussehra"),
        ("2025-10-20", "Diwali"),
        ("2024-12-24", "Christmas-New Year"),
        ("2025-01-01", "Christmas-New Year"),
    ],
)
def test_festival_days_flagged(cal: pd.DataFrame, day: str, name: str) -> None:
    row = cal.loc[day]
    assert row["is_festival"] and row["festival_name"] == name and row["is_festival_window"]


def test_festival_window_is_3_before_1_after(cal: pd.DataFrame) -> None:
    holi = pd.Timestamp("2024-03-25")
    window = cal.loc[holi - pd.Timedelta(days=5) : holi + pd.Timedelta(days=3)]
    expected = [False, False, True, True, True, True, True, False, False]
    assert window["is_festival_window"].tolist() == expected
    assert not cal.loc["2024-03-24", "is_festival"]


def test_christmas_window_extends_around_range(cal: pd.DataFrame) -> None:
    assert cal.loc["2024-12-21", "is_festival_window"]
    assert not cal.loc["2024-12-20", "is_festival_window"]
    assert cal.loc["2025-01-02", "is_festival_window"]
    assert not cal.loc["2025-01-03", "is_festival_window"]


def test_char_dham_range(cal: pd.DataFrame) -> None:
    cd = cal[cal["is_char_dham"]]
    assert set(cd["month"]) == {5, 6}
    assert len(cd) == 61 * cal.index.year.nunique()
    assert not cal.loc["2024-04-30", "is_char_dham"]
    assert not cal.loc["2024-07-01", "is_char_dham"]


def test_public_holidays(cal: pd.DataFrame) -> None:
    hol = cal[cal["is_public_holiday"]].index.strftime("%m-%d")
    assert sorted(set(hol)) == ["01-26", "08-15", "10-02"]
    assert len(hol) == 3 * cal.index.year.nunique()


def test_school_holidays(cal: pd.DataFrame) -> None:
    assert cal.loc["2024-05-20", "is_school_holiday"]
    assert cal.loc["2024-06-30", "is_school_holiday"]
    assert not cal.loc["2024-05-19", "is_school_holiday"]
    assert cal.loc["2025-01-05", "is_school_holiday"]
    assert not cal.loc["2025-01-06", "is_school_holiday"]


def test_weekend_is_fri_sat(cal: pd.DataFrame) -> None:
    assert set(cal.loc[cal["is_weekend"], "day_of_week"]) == {4, 5}


def test_in_month_day_range_wraps() -> None:
    md = pd.Series(["12-23", "12-24", "12-31", "01-01", "01-02"])
    assert in_month_day_range(md, "12-24", "01-01").tolist() == [False, True, True, True, False]


def test_festivals_yaml_parses() -> None:
    fc = load_festivals()
    assert date(2025, 10, 2) in fc.festivals["Dussehra"]
