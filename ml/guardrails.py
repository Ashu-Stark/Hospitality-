"""Shared prediction checks (guardrails) for every HOI model.

Used by the guarded entry points (ml/forecast/guarded.py, ml/attrition/guarded.py,
ml/models/workload_api.py, ml/realdata/hotel_alerts/api.py) and through them by the backend.

What a guarded prediction does:
  1. input schema + range validation (required columns present, values inside fixed limits)
  2. output clipping to sensible bounds (occupancy 0..1 = 0..room count, probabilities 0..1)
  3. drift: per-row z-score / range check against the TRAINING reference saved next to the
     model (reference_stats.json), and PSI for batches big enough to bin (>= psi_min_rows = 200)
  4. fallback to the model's baseline when inputs are missing or out of distribution
  5. a confidence label (high / medium / low) from the range width and the drift found
  6. stale-model rejection (the artifact is older than max_age_days -> baseline only)
  7. every check that does not pass is logged (logger "hoi.guardrails")

All thresholds are in GUARD_CONFIG below and are ASSUMED design values, not measured facts.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

LOG = logging.getLogger("hoi.guardrails")
REFERENCE_FILE = "reference_stats.json"

Status = Literal["pass", "warn", "fail"]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class GuardConfig:
    """ASSUMED thresholds (design choices; review once real hotel data exists)."""

    max_age_days: int = 365          # an artifact older than this is rejected (baseline only)
    z_limit: float = 4.0             # |value - training mean| / training std above this = OOD
    range_margin: float = 0.25       # allowed overshoot of the training min..max, x the range
    psi_warn: float = 0.10           # PSI 0.10-0.25 = moderate shift (common rule of thumb)
    psi_fail: float = 0.25           # PSI > 0.25 = large shift
    psi_min_rows: int = 200          # fewer rows: PSI is biased up (about (bins - 1) / n with no
                                     # drift: 0.16 at n = 55), so only per-row checks run
    psi_bins: int = 10
    ood_share_warn: float = 0.20     # share of rows with an OOD feature that makes a batch warn
    width_high: float = 0.15         # relative range width <= this -> high confidence
    width_medium: float = 0.30       # <= this -> medium, else low


GUARD_CONFIG = GuardConfig()


class Check(BaseModel):
    name: str
    status: Status
    detail: str


class GuardReport(BaseModel):
    """The `confidence` and `checks` fields every guarded API response carries."""

    confidence: Confidence
    checks: list[Check] = Field(default_factory=list)
    fallback_used: bool = False


# ------------------------------------------------------------------ logging helper
def record(checks: list[Check], name: str, status: Status, detail: str, model: str = "") -> Check:
    """Append a check; every non-pass check is logged (guardrail trigger)."""
    c = Check(name=name, status=status, detail=detail)
    checks.append(c)
    if status != "pass":
        LOG.warning("guardrail %s %s%s: %s", status, name, f" [{model}]" if model else "", detail)
    return c


# ------------------------------------------------------------------ reference stats
def _numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def build_reference(frame: pd.DataFrame, features: Iterable[str], *, model: str,
                    trained_on: str, training_window: str, bins: int = 10,
                    extra: Mapping | None = None) -> dict:
    """Per-feature training reference: mean, std, min, max, quantile bin edges and shares
    (numeric) or category shares (categorical). Saved as reference_stats.json."""
    feats: dict[str, dict] = {}
    for f in features:
        s = frame[f]
        if _numeric(s) or pd.api.types.is_bool_dtype(s):
            v = s.astype(float).dropna().to_numpy()
            if v.size == 0:
                continue
            edges = np.unique(np.quantile(v, np.linspace(0, 1, bins + 1)))
            shares = _bin_shares(v, edges)
            feats[f] = {"kind": "numeric", "mean": float(v.mean()), "std": float(v.std()),
                        "min": float(v.min()), "max": float(v.max()),
                        "p01": float(np.quantile(v, 0.01)), "p99": float(np.quantile(v, 0.99)),
                        "edges": [float(e) for e in edges], "shares": shares,
                        "missing_share": float(s.isna().mean())}
        else:
            vc = s.astype(str).value_counts(normalize=True)
            feats[f] = {"kind": "categorical", "shares": {str(k): float(x) for k, x in vc.items()},
                        "missing_share": float(s.isna().mean())}
    return {"model": model, "trained_on": trained_on, "training_window": training_window,
            "rows": int(len(frame)), "features": feats, **(dict(extra) if extra else {})}


def _bin_shares(v: np.ndarray, edges: np.ndarray) -> list[float]:
    if len(edges) < 2:
        return [1.0]
    idx = np.clip(np.searchsorted(edges, v, side="right") - 1, 0, len(edges) - 2)
    counts = np.bincount(idx, minlength=len(edges) - 1)
    return [float(c) / max(1, len(v)) for c in counts]


def save_reference(ref: dict, artifact_dir: Path) -> Path:
    path = artifact_dir / REFERENCE_FILE
    path.write_text(json.dumps(ref, indent=2) + "\n", encoding="utf-8")
    return path


def load_reference(artifact_dir: Path) -> dict | None:
    path = artifact_dir / REFERENCE_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ------------------------------------------------------------------ checks
def validate_schema(frame: pd.DataFrame, required: Iterable[str], checks: list[Check],
                    model: str = "") -> pd.Series:
    """Required columns present; returns a per-row mask of rows with a missing value."""
    required = list(required)
    absent = [c for c in required if c not in frame.columns]
    if absent:
        record(checks, "input_schema", "fail", f"missing input columns {absent}", model)
        return pd.Series(True, index=frame.index)
    missing = frame[required].isna().any(axis=1)
    if missing.any():
        cols = sorted(c for c in required if frame[c].isna().any())
        record(checks, "input_missing", "warn",
               f"{int(missing.sum())} of {len(frame)} rows have missing inputs ({cols}); "
               "those rows use the baseline", model)
    else:
        record(checks, "input_schema", "pass", f"{len(required)} inputs present, none missing")
    return missing


def validate_ranges(frame: pd.DataFrame, limits: Mapping[str, tuple[float, float]],
                    checks: list[Check], model: str = "") -> pd.Series:
    """Hard physical limits (e.g. occupancy 0..1, pulse 1..5). Returns a per-row bad mask."""
    bad = pd.Series(False, index=frame.index)
    out = []
    for col, (lo, hi) in limits.items():
        if col not in frame.columns:
            continue
        v = pd.to_numeric(frame[col], errors="coerce")
        b = v.notna() & ((v < lo) | (v > hi))
        if b.any():
            out.append(f"{col} outside {lo}..{hi} in {int(b.sum())} row(s)")
        bad |= b
    if out:
        record(checks, "input_range", "warn", "; ".join(out) + "; those rows use the baseline",
               model)
    else:
        record(checks, "input_range", "pass", "every input inside its allowed range")
    return bad


def ood_rows(frame: pd.DataFrame, ref: dict, cfg: GuardConfig = GUARD_CONFIG,
             ) -> tuple[pd.Series, dict[str, int]]:
    """Per-row out-of-distribution mask: a numeric feature with |z| > z_limit AND outside the
    training min..max widened by range_margin, or a category never seen in training."""
    mask = pd.Series(False, index=frame.index)
    per_feature: dict[str, int] = {}
    for f, st in ref.get("features", {}).items():
        if f not in frame.columns:
            continue
        if st["kind"] == "numeric":
            v = pd.to_numeric(frame[f], errors="coerce")
            std = st["std"] if st["std"] > 1e-12 else None
            span = st["max"] - st["min"]
            lo, hi = st["min"] - cfg.range_margin * span, st["max"] + cfg.range_margin * span
            outside = (v < lo) | (v > hi)
            if std is not None:
                outside &= ((v - st["mean"]).abs() / std) > cfg.z_limit
            elif span == 0:  # constant in training: anything else is new
                outside = v.notna() & (v != st["min"])
            b = outside.fillna(False)
        else:
            b = frame[f].notna() & ~frame[f].astype(str).isin(st["shares"].keys())
        if b.any():
            per_feature[f] = int(b.sum())
        mask |= b
    return mask, per_feature


def psi(ref_feature: dict, values: pd.Series) -> float | None:
    """Population stability index of a batch against the training reference (epsilon 1e-4)."""
    eps = 1e-4
    if ref_feature["kind"] == "numeric":
        v = pd.to_numeric(values, errors="coerce").dropna().to_numpy()
        if v.size == 0:
            return None
        expected = np.asarray(ref_feature["shares"], dtype=float)
        actual = np.asarray(_bin_shares(v, np.asarray(ref_feature["edges"])), dtype=float)
    else:
        cats = list(ref_feature["shares"])
        vc = values.dropna().astype(str).value_counts(normalize=True)
        expected = np.array([ref_feature["shares"][c] for c in cats] + [0.0])
        actual = np.array([float(vc.get(c, 0.0)) for c in cats]
                          + [float(vc[~vc.index.isin(cats)].sum())])
    if expected.size != actual.size:
        return None
    e, a = np.clip(expected, eps, None), np.clip(actual, eps, None)
    return float(np.sum((a - e) * np.log(a / e)))


def drift_check(frame: pd.DataFrame, ref: dict | None, checks: list[Check], model: str = "",
                cfg: GuardConfig = GUARD_CONFIG, psi_features: Iterable[str] | None = None,
                psi_skip_reason: str = "") -> tuple[pd.Series, str]:
    """Row OOD mask plus a batch drift level: none / moderate / large / unknown.
    psi_features: features whose batch distribution is comparable to the whole training set
    (default all); an empty list skips PSI with psi_skip_reason."""
    if ref is None:
        record(checks, "drift", "warn", "no training reference saved with this model; drift "
               "not checked", model)
        return pd.Series(False, index=frame.index), "unknown"
    mask, per_feature = ood_rows(frame, ref, cfg)
    level = "none"
    share = float(mask.mean()) if len(mask) else 0.0
    if per_feature:
        worst = sorted(per_feature.items(), key=lambda x: -x[1])[:4]
        top = ", ".join(f"{k} ({n})" for k, n in worst)
        status: Status = "warn"
        level = "large" if share > cfg.ood_share_warn else "moderate"
        record(checks, "drift_rows", status,
               f"{int(mask.sum())} of {len(frame)} rows are outside the training data "
               f"(|z| > {cfg.z_limit:g} and beyond the training range): {top}; those rows use "
               "the baseline", model)
    else:
        record(checks, "drift_rows", "pass",
               f"all {len(frame)} rows inside the training distribution (z-score and range)")
    wanted = None if psi_features is None else set(psi_features)
    if wanted is not None and not wanted:
        record(checks, "drift_psi", "pass", f"PSI skipped: {psi_skip_reason or 'not applicable'}"
               "; per-row z-score check used")
    elif len(frame) >= cfg.psi_min_rows:
        scores = {f: psi(st, frame[f]) for f, st in ref.get("features", {}).items()
                  if f in frame.columns and (wanted is None or f in wanted)}
        scores = {f: s for f, s in scores.items() if s is not None}
        worst = max(scores.items(), key=lambda x: x[1]) if scores else None
        if worst and worst[1] > cfg.psi_fail:
            level = "large"
            record(checks, "drift_psi", "warn",
                   f"large shift vs training: PSI {worst[1]:.2f} on {worst[0]} "
                   f"(> {cfg.psi_fail})", model)
        elif worst and worst[1] > cfg.psi_warn:
            level = "moderate" if level == "none" else level
            record(checks, "drift_psi", "warn",
                   f"moderate shift vs training: PSI {worst[1]:.2f} on {worst[0]}", model)
        elif worst:
            record(checks, "drift_psi", "pass", f"PSI <= {cfg.psi_warn} on every feature "
                   f"(max {worst[1]:.2f}, {worst[0]})")
    else:
        record(checks, "drift_psi", "pass",
               f"PSI skipped: {len(frame)} rows < {cfg.psi_min_rows} (too few to bin); "
               "per-row z-score check used")
    return mask, level


def staleness(ref: dict | None, today: date, checks: list[Check], model: str = "",
              cfg: GuardConfig = GUARD_CONFIG) -> bool:
    """True when the model must be rejected (older than max_age_days, or no trained_on date)."""
    trained = (ref or {}).get("trained_on")
    if not trained:
        record(checks, "model_age", "fail", "no trained_on date saved with this model; "
               "rejected, baseline used", model)
        return True
    age = (today - date.fromisoformat(str(trained)[:10])).days
    if age > cfg.max_age_days:
        record(checks, "model_age", "fail", f"model is {age} days old (limit "
               f"{cfg.max_age_days}); rejected, baseline used. Retrain it.", model)
        return True
    record(checks, "model_age", "pass", f"model trained on {trained} ({age} days ago, "
           f"limit {cfg.max_age_days})")
    return False


def clip(values: np.ndarray, lo: float, hi: float, checks: list[Check], what: str,
         model: str = "") -> np.ndarray:
    v = np.asarray(values, dtype=float)
    bad = ~np.isfinite(v)
    n = int(((v < lo) | (v > hi)).sum() + bad.sum())
    out = np.clip(np.where(bad, lo, v), lo, hi)
    if n:
        record(checks, "output_clip", "warn", f"{n} {what} value(s) clipped to {lo:g}..{hi:g}",
               model)
    else:
        record(checks, "output_clip", "pass", f"every {what} inside {lo:g}..{hi:g}")
    return out


def confidence(rel_width: float | None, drift_level: str, fallback_share: float,
               stale: bool, cfg: GuardConfig = GUARD_CONFIG) -> Confidence:
    """high / medium / low from the range width, drift and fallbacks (ASSUMED rule):
    start from the width (<= width_high high, <= width_medium medium, else low; no width =
    medium), drop one level for moderate drift or any fallback, to low for large drift, a
    stale model or a fallback on more than half of the rows."""
    levels: list[Confidence] = ["low", "medium", "high"]
    if rel_width is None or math.isnan(rel_width):
        i = 1
    else:
        i = 2 if rel_width <= cfg.width_high else 1 if rel_width <= cfg.width_medium else 0
    if stale or drift_level == "large" or fallback_share > 0.5:
        return "low"
    if drift_level in ("moderate", "unknown") or fallback_share > 0:
        i -= 1
    return levels[max(0, i)]
