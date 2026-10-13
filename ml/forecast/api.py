"""Occupancy forecast interface (Task T9): forecast.predict(start_date, end_date).

Loads the trained bundle from artifacts/occupancy_forecast/v1/ and the SYNTHETIC daily tables;
never trains. Forecasts are made AS OF a day (default: the day before start_date) and use only
data up to that day: target day d is served by the smallest trained horizon H >= d - as_of, with
features taken at origin d - H (never later than as_of). Days more than the largest trained
horizon ahead are refused. The synthetic dataset is the "world", so the target days must lie
inside it (its calendar is known in advance; its occupancy after as_of is never read).
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel

from ml.forecast.core import ARTIFACT_DIR, BASELINE, alert_flags, build_frame, daily_table
from ml.generator.config import load_config

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class ForecastDay(BaseModel):
    date: date
    horizon_days: int
    source: str  # "model" or "baseline" (seasonal-naive), as chosen at training time
    mean: float
    low: float
    high: float
    high_demand_alert: bool
    low_demand_alert: bool


class ForecastResult(BaseModel):
    as_of: date
    band: str
    days: list[ForecastDay]
    synthetic: bool = True


@lru_cache(maxsize=4)
def _load(artifact_dir: Path, data_dir: Path) -> tuple[dict, pd.DataFrame]:
    bundle = joblib.load(artifact_dir / "model.joblib")
    daily = daily_table(pd.read_csv(data_dir / "occupancy_daily.csv"),
                        pd.read_csv(data_dir / "event_calendar.csv"),
                        pd.read_csv(data_dir / "weather_daily.csv"))
    return bundle, daily


def _horizon_for(days_ahead: int, horizons: list[int]) -> int:
    fitting = [h for h in sorted(horizons) if h >= days_ahead]
    if days_ahead < 1 or not fitting:
        raise ValueError(f"cannot forecast {days_ahead} day(s) ahead; trained horizons are "
                         f"{sorted(horizons)} days")
    return fitting[0]


def _predict_horizon(info: dict, row: pd.DataFrame) -> tuple[np.ndarray, ...]:
    """Point forecast (model or seasonal-naive) plus the split-conformal residual band."""
    if info["use"] == "model":
        mean = np.clip(info["mean"].predict(row[info["features"]]), 0, 1)
    else:
        mean = row[BASELINE].to_numpy()
    lo, hi = info["residual_quantiles"]
    return mean, np.clip(mean + lo, 0, 1), np.clip(mean + hi, 0, 1)


def predict(start_date: date | str, end_date: date | str, as_of: date | str | None = None,
            artifact_dir: Path = ARTIFACT_DIR, data_dir: Path = DATA_DIR) -> ForecastResult:
    """Daily occupancy mean, 80% band and alert flags for start_date..end_date (inclusive)."""
    cfg = load_config()
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    origin = pd.Timestamp(as_of) if as_of is not None else start - timedelta(days=1)
    if end < start:
        raise ValueError("end_date is before start_date")
    bundle, daily = _load(artifact_dir, data_dir)
    if start <= daily.index.min() or end > daily.index.max():
        raise ValueError(f"dates must lie inside the SYNTHETIC data "
                         f"({daily.index.min().date()}..{daily.index.max().date()})")
    rooms = cfg.property.rooms
    days, frames = [], {}
    for d in pd.date_range(start, end, freq="D"):
        h = _horizon_for((d - origin).days, list(bundle))
        info = bundle[h]
        if h not in frames:  # features at origin d - h <= as_of; the target column is unused
            frames[h] = build_frame(daily, h, cfg.forecast, rooms)
        mean, low, high = _predict_horizon(info, frames[h].loc[[d]])
        hi_flag, lo_flag = alert_flags(mean, cfg.forecast)
        days.append(ForecastDay(date=d.date(), horizon_days=h, source=info["use"],
                                mean=round(float(mean[0]), 4), low=round(float(low[0]), 4),
                                high=round(float(high[0]), 4),
                                high_demand_alert=bool(hi_flag[0]),
                                low_demand_alert=bool(lo_flag[0])))
    q_lo, q_hi = cfg.forecast.band_quantiles
    band = f"{q_hi - q_lo:.0%} split-conformal interval"
    return ForecastResult(as_of=origin.date(), band=band, days=days)
