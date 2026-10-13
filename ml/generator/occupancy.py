"""Daily SYNTHETIC occupancy, ADR, revenue and booking pace.

Only the realised outcomes are returned; the latent expected occupancy and AR(1) noise
are not, so no column leaks the target. No lag features are built here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.generator.config import GeneratorConfig
from ml.generator.weather import by_month

OCCUPANCY_COLUMNS = ["occupancy_pct", "rooms_sold", "adr", "room_revenue", "booking_pace_7d"]


def ar1_noise(n: int, phi: float, sd: float, rng: np.random.Generator) -> np.ndarray:
    """AR(1) series e_t = phi * e_{t-1} + N(0, sd), started from its stationary distribution."""
    eps = rng.normal(0, sd, n)
    e = np.empty(n)
    e[0] = eps[0] / np.sqrt(1 - phi**2)
    for t in range(1, n):
        e[t] = phi * e[t - 1] + eps[t]
    return e


def expected_occupancy(days: pd.DataFrame, cfg: GeneratorConfig) -> np.ndarray:
    """Deterministic occupancy mean from calendar and weather flags (before noise/clipping)."""
    o = cfg.occupancy
    return (
        by_month(cfg.month_base_occupancy, days["month"].to_numpy())
        + cfg.weekend_uplift * days["is_weekend"].to_numpy()
        + o.festival_bump * days["is_festival_window"].to_numpy()
        + o.char_dham_bump * days["is_char_dham"].to_numpy()
        - cfg.weather.heavy_rain_occupancy_penalty * days["heavy_rain"].to_numpy()
        - cfg.road_closures.occupancy_penalty * days["road_closure_flag"].to_numpy()
    )


def simulate_occupancy(
    calendar: pd.DataFrame,
    weather: pd.DataFrame,
    cfg: GeneratorConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Merge calendar + weather on date and add the OCCUPANCY_COLUMNS."""
    days = calendar.merge(weather, on="date", how="inner", validate="one_to_one")
    n = len(days)
    rooms = cfg.property.rooms
    o = cfg.occupancy

    occ = expected_occupancy(days, cfg) + ar1_noise(n, o.ar1_phi, o.noise_sd, rng)
    occ = np.clip(occ, o.min, o.max)
    rooms_sold = np.rint(occ * rooms).astype(int)

    weekend = days["is_weekend"].to_numpy()
    adr = (
        by_month(cfg.adr.base_by_month, days["month"].to_numpy())
        * (1 + cfg.adr.weekend_premium * weekend)
        * (1 + rng.normal(0, cfg.adr.noise_sd, n))
    ).round(0)

    pickup = cfg.booking_pace.pickup_fraction_mean + rng.normal(0, cfg.booking_pace.noise_sd, n)
    pace = np.clip(np.rint(rooms_sold * pickup), 0, rooms).astype(int)

    days["occupancy_pct"] = rooms_sold / rooms
    days["rooms_sold"] = rooms_sold
    days["adr"] = adr
    days["room_revenue"] = rooms_sold * adr
    days["booking_pace_7d"] = pace
    return days
