"""Daily SYNTHETIC weather: temperature, rain, heavy rain and road closures."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.generator.config import GeneratorConfig, RoadClosureConfig


def by_month(values: dict[int, float], months: np.ndarray) -> np.ndarray:
    """Look up a per-month value for each day."""
    return np.array([values[int(m)] for m in months], dtype=float)


def simulate_road_closures(
    years: np.ndarray,
    is_monsoon: np.ndarray,
    heavy_rain: np.ndarray,
    rc: RoadClosureConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """Poisson number of closure events per year; monsoon events start on a heavy-rain day."""
    flag = np.zeros(len(years), dtype=bool)
    lo, hi = rc.duration_days_range
    for year in np.unique(years):
        idx = np.flatnonzero(years == year)
        n_events = rng.poisson(rc.per_year_mean * len(idx) / 365)
        for _ in range(n_events):
            in_monsoon = rng.random() < rc.monsoon_share
            pool = idx[is_monsoon[idx] == in_monsoon]
            if in_monsoon and heavy_rain[pool].any():
                pool = pool[heavy_rain[pool]]
            if pool.size == 0:
                continue
            start = int(rng.choice(pool))
            flag[start : start + int(rng.integers(lo, hi + 1))] = True
    return flag


def simulate_weather(
    calendar: pd.DataFrame, cfg: GeneratorConfig, rng: np.random.Generator
) -> pd.DataFrame:
    """Columns: date, temp_c, rain_day, heavy_rain, road_closure_flag."""
    w = cfg.weather
    months = calendar["month"].to_numpy()
    n = len(calendar)
    is_monsoon = np.isin(months, w.monsoon_months)

    temp = by_month(w.monthly_temp_c, months) + rng.normal(0, w.temp_sd, n)
    rain = rng.random(n) < by_month(w.rain_prob_by_month, months)
    heavy_p = np.where(is_monsoon, w.heavy_rain_prob_monsoon, w.heavy_rain_prob_other)
    heavy = rain & (rng.random(n) < heavy_p)
    closure = simulate_road_closures(
        calendar["date"].dt.year.to_numpy(), is_monsoon, heavy, cfg.road_closures, rng
    )
    return pd.DataFrame(
        {
            "date": calendar["date"],
            "temp_c": temp.round(1),
            "rain_day": rain,
            "heavy_rain": heavy,
            "road_closure_flag": closure,
        }
    )
