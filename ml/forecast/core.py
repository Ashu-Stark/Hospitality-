"""Occupancy forecast core (Task T6): feature frames, the seasonal-naive baseline, alerts.

A DIRECT model per horizon h: one row per forecast origin day t, target = occupancy_pct on day
d = t + h. Features use only what is known at the end of day t:
  - target-day calendar (known in advance): day of week, month, day of year, weekend,
    festival / festival window, Char Dham, public and school holidays
  - occupancy history up to t: occupancy on t, means of the last 7 and 28 days, the same weekday
    52 weeks before d (d - 364, always <= t for h <= 364), and d - 7 when h <= 7
  - weather observed up to t (never the target day's weather, which would leak): rain and heavy
    rain days and road-closure days in the last 7 days, road closure on t
  - booking_pace_7d of the target day ONLY for h <= booking_pace_max_horizon_days (it is the
    rooms on the books 7 days before the stay date, so it is unknown further ahead)
Baseline: seasonal-naive, occupancy on the same weekday 52 weeks earlier (d - 364).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ml.generator.config import ForecastConfig

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "occupancy_forecast" / "v1"
SEASONAL_LAG_DAYS = 364
TARGET = "target_occupancy"
BASELINE = "seasonal_naive"
CALENDAR_FEATURES = ["dow", "month", "day_of_year", "is_weekend", "is_festival",
                     "is_festival_window", "is_char_dham", "is_public_holiday",
                     "is_school_holiday"]
HISTORY_FEATURES = ["occ_origin", "occ_mean_7", "occ_mean_28", "occ_same_weekday_last_year"]
SHORT_HORIZON_FEATURES = ["occ_target_minus_7", "booking_pace_7d"]
WEATHER_FEATURES = ["rain_days_7", "heavy_rain_days_7", "closure_days_7", "closure_origin"]
HISTORY_DAYS_SHORT, HISTORY_DAYS_LONG = 7, 28


def feature_names(horizon: int, cfg: ForecastConfig) -> list[str]:
    short = SHORT_HORIZON_FEATURES if horizon <= cfg.booking_pace_max_horizon_days else []
    return CALENDAR_FEATURES + HISTORY_FEATURES + WEATHER_FEATURES + short


def daily_table(occupancy: pd.DataFrame, calendar: pd.DataFrame,
                weather: pd.DataFrame) -> pd.DataFrame:
    """One row per date with everything the feature builder needs."""
    df = occupancy.merge(calendar, on="date").merge(weather, on="date")
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").set_index("date")


def build_frame(daily: pd.DataFrame, horizon: int, cfg: ForecastConfig, rooms: int) -> pd.DataFrame:
    """Rows indexed by target date d (origin t = d - h), features + target + baseline."""
    occ = daily["occupancy_pct"]
    origin = daily.index - pd.Timedelta(days=horizon)
    at = lambda s: s.reindex(origin).to_numpy()  # noqa: E731 - value of a series at the origin
    flags = daily[["is_festival", "is_festival_window", "is_char_dham", "is_public_holiday",
                   "is_school_holiday", "is_weekend"]].astype(int)
    frame = pd.DataFrame({
        "dow": daily.index.dayofweek,
        "month": daily.index.month,
        "day_of_year": daily.index.dayofyear,
        **{c: flags[c].to_numpy() for c in flags},
        "occ_origin": at(occ),
        "occ_mean_7": at(occ.rolling(HISTORY_DAYS_SHORT).mean()),
        "occ_mean_28": at(occ.rolling(HISTORY_DAYS_LONG).mean()),
        "occ_same_weekday_last_year": occ.shift(SEASONAL_LAG_DAYS, freq="D").reindex(
            daily.index).to_numpy(),
        "rain_days_7": at(daily["rain_day"].astype(int).rolling(HISTORY_DAYS_SHORT).sum()),
        "heavy_rain_days_7": at(daily["heavy_rain"].astype(int).rolling(
            HISTORY_DAYS_SHORT).sum()),
        "closure_days_7": at(daily["road_closure_flag"].astype(int).rolling(
            HISTORY_DAYS_SHORT).sum()),
        "closure_origin": at(daily["road_closure_flag"].astype(int)),
        TARGET: occ.to_numpy(),
    }, index=daily.index)
    if horizon <= cfg.booking_pace_max_horizon_days:
        frame["occ_target_minus_7"] = occ.shift(7, freq="D").reindex(daily.index).to_numpy()
        frame["booking_pace_7d"] = (daily["booking_pace_7d"] / rooms).to_numpy()
    frame[BASELINE] = frame["occ_same_weekday_last_year"]
    return frame


def split_frame(frame: pd.DataFrame, cfg: ForecastConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train: targets up to train_end. Test: targets in [test_start, test_end]."""
    train = frame[frame.index <= pd.Timestamp(cfg.train_end)].dropna(subset=["occ_origin"])
    test = frame[(frame.index >= pd.Timestamp(cfg.test_start))
                 & (frame.index <= pd.Timestamp(cfg.test_end))]
    return train, test


def mape(y: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y - pred) / y))


def mae(y: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y - pred)))


def alert_flags(mean: np.ndarray, cfg: ForecastConfig) -> tuple[np.ndarray, np.ndarray]:
    """(high_demand, low_demand) flags from the config thresholds."""
    return mean >= cfg.alert_high_occupancy, mean <= cfg.alert_low_occupancy
