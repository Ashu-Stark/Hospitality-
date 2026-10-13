from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml.generator.calendar import build_calendar
from ml.generator.weather import simulate_weather

LONG_YEARS = 60


@pytest.fixture(scope="module")
def long_run(cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    """60 years of weather so empirical rates are close to the configured ones."""
    end = date(cfg.property.start.year + LONG_YEARS - 1, 12, 31)
    long_cfg = cfg.model_copy(update={"property": cfg.property.model_copy(update={"end": end})})
    cal = build_calendar(long_cfg)
    return cal, simulate_weather(cal, long_cfg, np.random.default_rng(0))


def test_columns_and_types(cfg, generated) -> None:
    w = generated[1]
    assert list(w.columns) == ["date", "temp_c", "rain_day", "heavy_rain", "road_closure_flag"]
    assert len(w) == (cfg.property.end - cfg.property.start).days + 1
    assert not w.isna().any().any()
    for col in ("rain_day", "heavy_rain", "road_closure_flag"):
        assert w[col].dtype == bool


def test_reproducible(cfg, generated) -> None:
    cal = generated[0]
    a = simulate_weather(cal, cfg, np.random.default_rng(7))
    b = simulate_weather(cal, cfg, np.random.default_rng(7))
    c = simulate_weather(cal, cfg, np.random.default_rng(8))
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


def test_rain_rates_match_config(cfg, long_run) -> None:
    cal, w = long_run
    rates = w["rain_day"].groupby(cal["month"]).mean()
    for m, p in cfg.weather.rain_prob_by_month.items():
        assert 0 <= rates[m] <= 1
        assert rates[m] == pytest.approx(p, abs=0.03)


def test_temperature_tracks_monthly_mean(cfg, long_run) -> None:
    cal, w = long_run
    means = w["temp_c"].groupby(cal["month"]).mean()
    for m, t in cfg.weather.monthly_temp_c.items():
        assert means[m] == pytest.approx(t, abs=0.3)


def test_heavy_rain_subset_and_monsoon_heavier(cfg, long_run) -> None:
    cal, w = long_run
    assert not (w["heavy_rain"] & ~w["rain_day"]).any()
    monsoon = cal["month"].isin(cfg.weather.monsoon_months)
    rain = w["rain_day"]
    share_monsoon = w.loc[monsoon & rain, "heavy_rain"].mean()
    share_other = w.loc[~monsoon & rain, "heavy_rain"].mean()
    assert share_monsoon == pytest.approx(cfg.weather.heavy_rain_prob_monsoon, abs=0.03)
    assert share_monsoon > share_other


def test_road_closures_mostly_monsoon(cfg, long_run) -> None:
    cal, w = long_run
    closed = w["road_closure_flag"]
    assert closed.any()
    monsoon = cal["month"].isin(cfg.weather.monsoon_months)
    assert closed[monsoon].sum() / closed.sum() > 0.5
    rc = cfg.road_closures
    lo, hi = rc.duration_days_range
    days_per_year = closed.sum() / LONG_YEARS
    assert rc.per_year_mean * lo <= days_per_year <= rc.per_year_mean * hi
