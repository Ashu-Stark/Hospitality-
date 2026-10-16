"""Workload interface (Task 7 model, loads artifacts/workload/v1; never trains), guarded.

    from ml.models import workload_api
    workload_api.predict_next_week(data_dir=..., week_start=None)  # -> WorkloadForecast

Next week's load_ratio (required / available hours) per department, made at the end of
`week_start` (default: the last week in the data). Guardrails (ml/guardrails.py): inputs
validated, rows outside the training distribution fall back to the naive baseline (next week =
this week), outputs clipped to 0..3, stale model rejected. SYNTHETIC data.

Note: the model was trained on the default 45-room hotel. occupied_room_nights and headcount of
a smaller hotel (e.g. the 24-room Himsagar variant) can lie outside its training range; the
guardrail then uses the naive baseline for those departments, which is the intended behaviour.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel

from ml import guardrails as G
from ml.features.build_workload_features import (
    WORKLOAD_FEATURES,
    add_department_history,
    festival_weeks,
    load_inputs,
)

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "workload" / "v1"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MODEL = "workload/v1"
LIMITS = {"load_ratio": (0, 3), "load_roll4_mean": (0, 3), "headcount": (0, 500),
          "occupied_room_nights": (0, 100_000), "week_of_year": (1, 53)}
OUT_BOUNDS = (0.0, 3.0)  # ASSUMED sensible load_ratio range


class DepartmentLoad(BaseModel):
    department: str
    this_week_load: float
    next_week_load: float
    source: str  # model / baseline


class WorkloadForecast(BaseModel):
    week_start: date
    for_week: date
    departments: list[DepartmentLoad]
    confidence: str
    checks: list[G.Check]
    fallback_used: bool
    synthetic: bool = True


@lru_cache(maxsize=2)
def _model(artifact_dir: Path):
    return joblib.load(artifact_dir / "model.joblib")


def week_features(data_dir: Path, week_start: date | str | None = None) -> pd.DataFrame:
    """Feature rows of one department-week (no next-week label needed)."""
    load, calendar = load_inputs(data_dir)
    df = add_department_history(load.assign(week_start=pd.to_datetime(load["week_start"])))
    week = pd.Timestamp(week_start) if week_start is not None else df["week_start"].max()
    fest = festival_weeks(calendar)
    df = df[df["week_start"] == week].copy()
    if df.empty:
        raise ValueError(f"no workload rows for week {week.date()}")
    df["week_of_year"] = df["week_start"].dt.isocalendar().week.astype(int)
    df["is_festival_week"] = df["week_start"].map(fest).fillna(0).astype(int)
    df["next_week_is_festival"] = (df["week_start"] + pd.Timedelta(days=7)).map(fest).fillna(
        0).astype(int)
    return df.reset_index(drop=True)


def predict_next_week(data_dir: Path = DATA_DIR, week_start: date | str | None = None,
                      artifact_dir: Path = ARTIFACT_DIR, today: date | None = None,
                      ) -> WorkloadForecast:
    rows = week_features(data_dir, week_start)
    ref = G.load_reference(artifact_dir)
    checks: list[G.Check] = []
    stale = G.staleness(ref, today or date.today(), checks, MODEL)
    x = rows[WORKLOAD_FEATURES]
    missing = G.validate_schema(x, WORKLOAD_FEATURES, checks, MODEL)
    bad = G.validate_ranges(x, LIMITS, checks, MODEL)
    ood, level = G.drift_check(x, ref, checks, MODEL, psi_features=[],
                               psi_skip_reason="one week has one row per department")
    fallback = (missing | bad | ood).to_numpy() | stale
    pred = rows["load_ratio"].to_numpy(dtype=float).copy()  # naive baseline
    if (~fallback).any():
        pred[~fallback] = _model(artifact_dir).predict(x[~fallback])
    pred = G.clip(pred, *OUT_BOUNDS, checks, "load ratio", MODEL)
    if fallback.any():
        G.record(checks, "fallback", "warn", f"{int(fallback.sum())} of {len(rows)} department(s) "
                 "use the naive baseline (next week = this week)", MODEL)
    week = rows["week_start"].iloc[0].date()
    return WorkloadForecast(
        week_start=week, for_week=week + timedelta(days=7),
        departments=[DepartmentLoad(department=r.department,
                                    this_week_load=round(float(r.load_ratio), 4),
                                    next_week_load=round(float(p), 4),
                                    source="baseline" if f else "model")
                     for r, p, f in zip(rows.itertuples(), pred, fallback, strict=True)],
        confidence=G.confidence(None, level, float(np.mean(fallback)), stale),
        checks=checks, fallback_used=bool(fallback.any()))
