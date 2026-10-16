import numpy as np
import pandas as pd
import pytest

from ml.forecast.core import (
    BASELINE,
    SEASONAL_LAG_DAYS,
    TARGET,
    alert_flags,
    build_frame,
    daily_table,
    feature_names,
    mape,
    split_frame,
)
from ml.forecast.train import train_horizon


@pytest.fixture(scope="module")
def daily(generated) -> pd.DataFrame:
    calendar, weather, occ_daily = generated
    occupancy = occ_daily[["date", "occupancy_pct", "rooms_sold", "adr", "room_revenue",
                           "booking_pace_7d"]]
    return daily_table(occupancy, calendar, weather)


def test_booking_pace_only_for_short_horizons(cfg) -> None:
    f = cfg.forecast
    assert "booking_pace_7d" in feature_names(1, f) and "booking_pace_7d" in feature_names(7, f)
    assert "booking_pace_7d" not in feature_names(30, f)


def test_baseline_is_same_weekday_52_weeks_earlier(cfg, daily) -> None:
    frame = build_frame(daily, 7, cfg.forecast, cfg.property.rooms)
    d = pd.Timestamp("2025-06-10")
    assert frame.loc[d, BASELINE] == daily.loc[d - pd.Timedelta(days=SEASONAL_LAG_DAYS),
                                               "occupancy_pct"]
    assert (d - pd.Timedelta(days=SEASONAL_LAG_DAYS)).dayofweek == d.dayofweek


def test_no_target_leakage_in_history_features(cfg, daily) -> None:
    """History features of target d with horizon h only use days up to d - h."""
    h = 30
    frame = build_frame(daily, h, cfg.forecast, cfg.property.rooms)
    d = pd.Timestamp("2025-03-15")
    origin = d - pd.Timedelta(days=h)
    assert frame.loc[d, "occ_origin"] == daily.loc[origin, "occupancy_pct"]
    window = daily.loc[origin - pd.Timedelta(days=6):origin, "occupancy_pct"]
    assert frame.loc[d, "occ_mean_7"] == pytest.approx(window.mean())
    changed = daily.copy()
    later = changed.index > origin
    changed.loc[later, "occupancy_pct"] = 0.0
    changed.loc[later, ["rain_day", "heavy_rain", "road_closure_flag"]] = False
    again = build_frame(changed, h, cfg.forecast, cfg.property.rooms)
    hist = [c for c in feature_names(h, cfg.forecast) if c.startswith(("occ_", "rain", "heavy",
                                                                        "closure"))]
    hist.remove("occ_same_weekday_last_year")  # d - 364 is long before the origin
    assert (frame.loc[d, hist] == again.loc[d, hist]).all()
    assert frame.loc[d, TARGET] != again.loc[d, TARGET]


def test_split_by_time(cfg, daily) -> None:
    train, test = split_frame(build_frame(daily, 1, cfg.forecast, cfg.property.rooms),
                              cfg.forecast)
    assert train.index.max() <= pd.Timestamp(cfg.forecast.train_end)
    assert test.index.min() >= pd.Timestamp(cfg.forecast.test_start)
    assert test.index.max() <= pd.Timestamp(cfg.forecast.test_end)


def test_metrics_and_alerts(cfg) -> None:
    assert mape(np.array([0.5, 1.0]), np.array([0.25, 1.0])) == pytest.approx(0.25)
    high, low = alert_flags(np.array([0.95, 0.5, 0.2]), cfg.forecast)
    assert high.tolist() == [True, False, False] and low.tolist() == [False, False, True]


@pytest.mark.gpu  # trains a model: GPU only
def test_train_horizon_reports_model_and_baseline(cfg, daily) -> None:
    r = train_horizon(daily, 7, cfg)
    m = r["metrics"]
    assert {"model_mape", "baseline_mape", "band_coverage", "used"} <= set(m)
    assert m["used"] in {"model", "baseline"}
    c = r["curve"]
    assert (c["low"] <= c["forecast"] + 1e-9).all() and (c["forecast"] <= c["high"] + 1e-9).all()
