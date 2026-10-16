"""Guarded occupancy forecast: forecast.predict plus the shared prediction checks.

    from ml.forecast import guarded
    guarded.predict("2029-12-24", "2029-12-30", data_dir=..., rooms=24)  # -> GuardedForecast

Same point forecast and band as forecast.predict for every day whose inputs pass the checks.
A day with missing, out-of-range or out-of-distribution inputs (or every day, when the model
is stale) uses the seasonal-naive baseline (same weekday 52 weeks earlier; then the last 28
days' mean if that is missing), with the model's band widened by baseline MAE / model MAE from
the test metrics. Outputs are clipped to 0..1 (= 0..room count). SYNTHETIC data.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ml import guardrails as G
from ml.forecast.api import (
    DATA_DIR,
    ForecastDay,
    ForecastResult,
    _horizon_for,
    _load,
    _predict_horizon,
)
from ml.forecast.core import (
    ARTIFACT_DIR,
    BASELINE,
    CALENDAR_FEATURES,
    HISTORY_FEATURES,
    WEATHER_FEATURES,
    alert_flags,
    build_frame,
)
from ml.generator.config import load_config

MODEL = "occupancy_forecast/v1"
LIMITS = {"occ_origin": (0, 1), "occ_mean_7": (0, 1), "occ_mean_28": (0, 1),
          "occ_same_weekday_last_year": (0, 1), "occ_target_minus_7": (0, 1),
          "booking_pace_7d": (0, 1), "rain_days_7": (0, 7), "heavy_rain_days_7": (0, 7),
          "closure_days_7": (0, 7), "closure_origin": (0, 1), "dow": (0, 6), "month": (1, 12)}
BAND_COVERAGE_OK = (0.70, 0.90)  # stored test coverage of the nominal 80% band (ASSUMED limits)


class GuardedForecast(ForecastResult):
    rooms: int
    confidence: str
    checks: list[G.Check]
    fallback_used: bool
    fallback_days: list[date] = []


def _metrics(artifact_dir: Path) -> dict:
    p = artifact_dir / "metrics.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}


def predict(start_date: date | str, end_date: date | str, as_of: date | str | None = None,
            artifact_dir: Path = ARTIFACT_DIR, data_dir: Path = DATA_DIR,
            rooms: int | None = None, today: date | None = None,
            overrides: dict[str, dict[str, float]] | None = None) -> GuardedForecast:
    """forecast.predict with checks. overrides {iso date: {feature: value}} replaces input
    values (tests and what-if only)."""
    cfg = load_config()
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    origin = pd.Timestamp(as_of) if as_of is not None else start - timedelta(days=1)
    if end < start:
        raise ValueError("end_date is before start_date")
    bundle, daily = _load(artifact_dir, data_dir)
    if start <= daily.index.min() or end > daily.index.max():
        raise ValueError(f"dates must lie inside the SYNTHETIC data "
                         f"({daily.index.min().date()}..{daily.index.max().date()})")
    rooms = rooms if rooms is not None else cfg.property.rooms
    ref = G.load_reference(artifact_dir)
    metrics = _metrics(artifact_dir)
    checks: list[G.Check] = []
    stale = G.staleness(ref, today or date.today(), checks, MODEL)

    frames, rows, plan = {}, [], []
    for d in pd.date_range(start, end, freq="D"):
        h = _horizon_for((d - origin).days, list(bundle))
        if h not in frames:
            frames[h] = build_frame(daily, h, cfg.forecast, rooms)
        row = frames[h].loc[[d]].copy()
        for k, v in (overrides or {}).get(d.date().isoformat(), {}).items():
            row[k] = v
        rows.append(row)
        plan.append((d, h))
    x = pd.concat(rows)
    required = CALENDAR_FEATURES + HISTORY_FEATURES + WEATHER_FEATURES
    missing = G.validate_schema(x, required, checks, MODEL)
    bad = G.validate_ranges(x, LIMITS, checks, MODEL)
    present = [f for f in (ref or {}).get("features", {}) if f in x.columns]
    ood, level = G.drift_check(
        x[present], ref, checks, MODEL, psi_features=[],
        psi_skip_reason="a forecast window covers one season, so its distribution is not "
                        "comparable to the whole training period")
    use_base = (missing | bad | ood).to_numpy() | stale

    days, widths, fb_days = [], [], []
    for i, (d, h) in enumerate(plan):
        info, row = bundle[h], x.iloc[[i]]
        if use_base[i]:
            base = row[BASELINE].iloc[0]
            if pd.isna(base) or not 0 <= base <= 1:
                base = row["occ_mean_28"].iloc[0]
            if pd.isna(base):
                raise ValueError(f"no usable input or baseline for {d.date()}")
            m = metrics.get(str(h), {})
            widen = (m.get("baseline_mae", 1.0) / m["model_mae"]) if m.get("model_mae") else 2.0
            lo_q, hi_q = info["residual_quantiles"]
            mean = np.array([float(base)])
            low, high = mean + lo_q * widen, mean + hi_q * widen
            source = "baseline"
            fb_days.append(d.date())
        else:
            mean, low, high = _predict_horizon(info, row)
            source = info["use"]
        mean = G.clip(mean, 0, 1, checks, "occupancy", MODEL)
        low, high = np.clip(low, 0, 1), np.clip(high, 0, 1)
        low, high = np.minimum(low, mean), np.maximum(high, mean)
        widths.append(float(high[0] - low[0]))
        hi_flag, lo_flag = alert_flags(mean, cfg.forecast)
        days.append(ForecastDay(date=d.date(), horizon_days=h, source=source,
                                mean=round(float(mean[0]), 4), low=round(float(low[0]), 4),
                                high=round(float(high[0]), 4), high_demand_alert=bool(hi_flag[0]),
                                low_demand_alert=bool(lo_flag[0])))
    # collapse the per-day clip checks into one
    clips = [c for c in checks if c.name == "output_clip"]
    checks = [c for c in checks if c.name != "output_clip"]
    n_clip = sum(c.status != "pass" for c in clips)
    checks.append(G.Check(name="output_clip", status="warn" if n_clip else "pass",
                          detail=f"{n_clip} day(s) clipped to 0..1 occupancy (0..{rooms} rooms)"
                          if n_clip else f"every day inside 0..1 occupancy (0..{rooms} rooms)"))
    for h in sorted({h for _, h in plan}):
        cov = metrics.get(str(h), {}).get("band_coverage")
        if cov is not None:
            ok = BAND_COVERAGE_OK[0] <= cov <= BAND_COVERAGE_OK[1]
            G.record(checks, f"band_coverage_{h}d", "pass" if ok else "warn",
                     f"split-conformal 80% band held the actual value on {cov:.1%} of test days "
                     f"(acceptable {BAND_COVERAGE_OK[0]:.0%}-{BAND_COVERAGE_OK[1]:.0%})", MODEL)
    if fb_days:
        G.record(checks, "fallback", "warn", f"{len(fb_days)} of {len(days)} day(s) use the "
                 "seasonal-naive baseline", MODEL)
    share = len(fb_days) / len(days)
    q_lo, q_hi = cfg.forecast.band_quantiles
    return GuardedForecast(
        as_of=origin.date(), band=f"{q_hi - q_lo:.0%} split-conformal interval", days=days,
        rooms=rooms, confidence=G.confidence(float(np.mean(widths)), level, share, stale),
        checks=checks, fallback_used=bool(fb_days), fallback_days=fb_days)
