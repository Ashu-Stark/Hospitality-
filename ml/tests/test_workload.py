import numpy as np
import pandas as pd
import pytest

from ml.generator.workload import LOAD_COLUMNS, build_dept_week_load, weekly_room_nights


def _complete_weeks(cfg) -> pd.DatetimeIndex:
    """Mondays whose whole week lies inside the property date range."""
    mondays = pd.date_range(cfg.property.start, cfg.property.end, freq="W-MON")
    return mondays[mondays + pd.Timedelta(days=6) <= pd.Timestamp(cfg.property.end)]


def test_weeks_are_complete_mondays(cfg, generated) -> None:
    weeks = weekly_room_nights(generated[2])
    expected = _complete_weeks(cfg)
    assert len(weeks) == len(expected)
    assert (weeks["week_start"].dt.dayofweek == 0).all()
    assert weeks["week_start"].min() == pd.Timestamp("2023-01-02")
    assert weeks["week_start"].max() == expected.max()


def test_room_nights_sum_rooms_sold(generated) -> None:
    daily = generated[2]
    weeks = weekly_room_nights(daily).set_index("week_start")
    first = daily[(daily["date"] >= "2023-01-02") & (daily["date"] <= "2023-01-08")]
    assert weeks.loc["2023-01-02", "occupied_room_nights"] == first["rooms_sold"].sum()


def test_load_formula(cfg, staff_frames) -> None:
    load = staff_frames.dept_week_load
    assert list(load.columns) == LOAD_COLUMNS
    assert len(load) == len(_complete_weeks(cfg)) * len(cfg.departments)
    for dept, g in load.groupby("department"):
        std = cfg.workload[dept]
        expected = std.base_hours + std.per_occupied_room_night_hours * g["occupied_room_nights"]
        assert np.allclose(g["required_hours"], expected)
        assert (g["headcount"] == cfg.departments[dept]).all()
        assert (g["available_hours"] == cfg.departments[dept] * 48).all()
        assert np.allclose(g["load_ratio"], expected / g["available_hours"], atol=1e-4)


def test_partial_week_dropped(cfg, staff_frames) -> None:
    dates = pd.date_range("2024-01-01", "2024-01-10", freq="D")  # Mon..Wed next week
    daily = pd.DataFrame({"date": dates, "rooms_sold": 10})
    load = build_dept_week_load(daily, staff_frames.employee, cfg)
    assert load["week_start"].nunique() == 1
    assert (load["occupied_room_nights"] == 70).all()


def test_zero_headcount_gives_inf(cfg, staff_frames) -> None:
    daily = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=7), "rooms_sold": 5})
    emp = staff_frames.employee[staff_frames.employee["department"] != "security"]
    load = build_dept_week_load(daily, emp, cfg)
    assert load.loc[load["department"] == "security", "load_ratio"].iloc[0] == pytest.approx(
        float("inf")
    )
