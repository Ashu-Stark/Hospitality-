"""Daily room-night forecasting on the REAL Hotel Booking Demand data: splits, features,
baselines, tree models (LightGBM CPU, XGBoost GPU), split-conformal bands and metrics.

Direct model per horizon h (like ml/forecast): one row per (hotel, target night d), origin
t = d - h; features use only what is known at the end of day t. One model is fitted on both
hotels together, on the occupancy proxy y / capacity (capacity = the hotel's highest nightly
count in the TRAINING window, so the test period never sets the scale), with a hotel flag.

Time split (never random), by TARGET date:
  train       series start .. 2016-10-31
  gap         2016-11-01 .. 2016-11-30   (no targets used)
  validation  2016-12-01 .. 2017-01-31   (band calibration, TimesFM early stopping)
  gap         2017-02-01 .. 2017-02-28   (no targets used)
  test        2017-03-01 .. 2017-08-31   (the last 6 months, scored once)
Learned models are fitted on TRAIN only (not refitted on train + validation). Test-time
inputs may use observed nights up to the origin t (as a live system would), including gap
days; only targets are excluded from training.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ml.realdata.hotels import HOTELS, holiday_flags


@dataclass(frozen=True)
class Split:
    train_end: str = "2016-10-31"
    val_start: str = "2016-12-01"
    val_end: str = "2017-01-31"
    test_start: str = "2017-03-01"
    test_end: str = "2017-08-31"


SPLIT = Split()
HORIZONS = (1, 7, 30)
BAND = (0.10, 0.90)  # 80% nominal prediction interval
YEAR = 364  # same weekday one year earlier
TARGET, HOTEL_FLAG = "target", "is_resort"
CALENDAR = ["dow", "month", "day_of_year", "is_weekend_night", "is_holiday", "days_to_holiday",
            HOTEL_FLAG]
HISTORY = ["y_origin", "y_mean_7", "y_mean_28", "y_last_week", "y_last_year"]
PACE = ["otb", "otb_last_year", "pickup_last_year"]


def features(kind: str) -> list[str]:
    """'calendar' = the existing ml/forecast approach adapted; 'pace' adds on-the-books."""
    return CALENDAR + HISTORY + (PACE if kind == "pace" else [])


def last_week_lag(h: int) -> int:
    """Lag (days) of the most recent same weekday already observed at the origin."""
    return 7 * math.ceil(h / 7)


def capacities(daily: pd.DataFrame, split: Split = SPLIT) -> dict[str, float]:
    train = daily[daily.index <= pd.Timestamp(split.train_end)]
    return {h: float(train[h].max()) for h in HOTELS}


def build_frame(daily: pd.DataFrame, otb: pd.DataFrame | None, h: int,
                caps: dict[str, float]) -> pd.DataFrame:
    """Rows = (hotel, target date), features in capacity-proxy units, plus raw-unit columns
    y_true / snaive_week / snaive_year / pickup_naive and the capacity."""
    parts = []
    for hotel in HOTELS:
        y = daily[hotel]
        cap = caps[hotel]
        idx = y.index
        at_origin = lambda s: s.shift(h).to_numpy()  # noqa: E731 - value at t = d - h
        lw = y.shift(last_week_lag(h))
        ly = y.shift(YEAR)
        f = pd.DataFrame({
            "hotel": hotel, "capacity": cap,
            "dow": idx.dayofweek, "month": idx.month, "day_of_year": idx.dayofyear,
            "is_weekend_night": idx.dayofweek.isin([4, 5]).astype(int),  # Fri / Sat nights
            HOTEL_FLAG: int(hotel == "Resort Hotel"),
            "y_origin": at_origin(y) / cap,
            "y_mean_7": at_origin(y.rolling(7).mean()) / cap,
            "y_mean_28": at_origin(y.rolling(28).mean()) / cap,
            "y_last_week": lw.to_numpy() / cap,
            "y_last_year": ly.to_numpy() / cap,
            TARGET: y.to_numpy() / cap,
            "y_true": y.to_numpy(),
            "snaive_week": lw.to_numpy(),
            "snaive_year": ly.to_numpy(),
        }, index=idx)
        f = f.join(holiday_flags(idx, hotel))
        if otb is not None:
            o = otb[hotel]
            pickup_ly = (ly - o.shift(YEAR)).to_numpy()
            f["otb"] = o.to_numpy() / cap
            f["otb_last_year"] = o.shift(YEAR).to_numpy() / cap
            f["pickup_last_year"] = pickup_ly / cap
            # Classic hotel "additive pickup" forecast: on the books now + last year's pickup.
            f["pickup_naive"] = o.to_numpy() + pickup_ly
        parts.append(f.dropna(subset=["y_true"]))
    out = pd.concat(parts)
    out.index.name = "date"
    return out


def split_frame(frame: pd.DataFrame, split: Split = SPLIT) -> dict[str, pd.DataFrame]:
    d = frame.index
    return {
        "train": frame[(d <= pd.Timestamp(split.train_end)) & frame["y_origin"].notna()],
        "val": frame[(d >= pd.Timestamp(split.val_start)) & (d <= pd.Timestamp(split.val_end))],
        "test": frame[(d >= pd.Timestamp(split.test_start))
                      & (d <= pd.Timestamp(split.test_end))],
    }


# ---- metrics ---------------------------------------------------------------------------

def mape(y: np.ndarray, p: np.ndarray) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    ok = y > 0
    return float(np.mean(np.abs(y[ok] - p[ok]) / y[ok]))


def mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(y, float) - np.asarray(p, float))))


def coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    y = np.asarray(y, float)
    return float(np.mean((y >= lo) & (y <= hi)))


def conformal_offsets(residuals: np.ndarray, band: tuple[float, float] = BAND
                      ) -> tuple[float, float]:
    """Split-conformal residual quantiles with the (n + 1) finite-sample correction."""
    r = np.sort(np.asarray(residuals, float))
    n = len(r)
    lo = max(np.floor((n + 1) * band[0]) / n, 0.0)
    hi = min(np.ceil((n + 1) * band[1]) / n, 1.0)
    return (float(np.quantile(r, lo, method="inverted_cdf")),
            float(np.quantile(r, hi, method="inverted_cdf")))


def score_rows(test: pd.DataFrame, pred: np.ndarray, lo: np.ndarray | None,
               hi: np.ndarray | None) -> list[dict]:
    """Per-hotel metrics in room-nights for one model and horizon."""
    rows = []
    for hotel, g in test.assign(_p=pred, _lo=lo if lo is not None else np.nan,
                                _hi=hi if hi is not None else np.nan).groupby("hotel"):
        y = g["y_true"].to_numpy()
        row = {"hotel": hotel, "days": len(g), "mape": round(mape(y, g["_p"]), 4),
               "mae_room_nights": round(mae(y, g["_p"]), 2),
               "median_abs_error_room_nights": round(float(np.median(np.abs(y - g["_p"]))), 2),
               "mae_pct_of_capacity": round(mae(y, g["_p"]) / g["capacity"].iloc[0], 4)}
        if lo is not None:
            row["coverage_80"] = round(coverage(y, g["_lo"], g["_hi"]), 4)
            row["band_width_room_nights"] = round(float(np.mean(g["_hi"] - g["_lo"])), 2)
        rows.append(row)
    return rows


# ---- tree models -----------------------------------------------------------------------

LGBM_PARAMS = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20,
                   subsample=0.8, subsample_freq=1, colsample_bytree=0.8, n_jobs=1,
                   deterministic=True, force_row_wise=True, verbose=-1)
XGB_PARAMS = dict(n_estimators=400, learning_rate=0.03, max_depth=4, min_child_weight=5,
                  subsample=0.8, colsample_bytree=0.8, tree_method="hist")


def fit_lgbm(x: pd.DataFrame, y: pd.Series, seed: int):
    import lightgbm as lgb
    return lgb.LGBMRegressor(objective="regression", random_state=seed, **LGBM_PARAMS).fit(x, y)


def fit_xgb(x: pd.DataFrame, y: pd.Series, seed: int, device: str = "cuda"):
    import xgboost as xgb
    return xgb.XGBRegressor(random_state=seed, device=device, **XGB_PARAMS).fit(x, y)


def evaluate_point_model(parts: dict[str, pd.DataFrame], val_pred: np.ndarray,
                         test_pred: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Clip to >= 0, add the split-conformal band from validation residuals (room-nights,
    pooled over hotels in capacity units then rescaled per hotel)."""
    val, test = parts["val"], parts["test"]
    ok = ~np.isnan(val_pred)
    resid = (val["y_true"].to_numpy()[ok] - val_pred[ok]) / val["capacity"].to_numpy()[ok]
    r_lo, r_hi = conformal_offsets(resid)
    cap = test["capacity"].to_numpy()
    p = np.clip(test_pred, 0, None)
    return p, np.clip(p + r_lo * cap, 0, None), p + r_hi * cap
