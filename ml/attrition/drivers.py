"""Attrition drivers (T8, made consistent in T12): per-feature contributions grouped into 7
driver categories, with plain-language reasons, on SYNTHETIC data.

Contributions come from the SAME model that produces the risk (the segment's calibrated winner;
see FoldModel.contributions), in calibrated log-odds relative to the training mean: for the
logistic winner coefficient x (standardised value - training mean). LightGBM TreeSHAP
(shap_values, pred_contrib=True) is kept only as a COMPARISON view in drivers.json.

A driver category's contribution = the sum of its features' contributions. Only categories
pushing risk UP by at least attrition_model.driver_min_logodds (config, ASSUMED) are reported,
largest first, at most TOP_DRIVERS.
Manager relationship is UNSUPPORTED: the data has a manager_id but no signal about the
relationship (no 1:1s, no manager pulse item, no transfer requests), so no feature maps to it.
Clustered-leave burnout is WEAKLY SUPPORTED: the generator's hazard has a weeks-without-leave
term but no pre-festival leave term, so only part of the category was ever planted.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from ml.attrition.models import LightGBMScorer

PLAYBOOK_PATH = Path(__file__).resolve().parent / "playbook.json"
TOP_DRIVERS = 3
UNSUPPORTED = "manager_relationship"
WEAK = "clustered_leave_burnout"
# How well the SYNTHETIC generator supports each driver (T12b). The hazard has a weeks-without-
# leave term but NO pre-festival (clustered) leave term, so clustered-leave burnout is only
# WEAKLY supported; there is no manager signal at all.
SUPPORTED, WEAKLY_SUPPORTED, NOT_SUPPORTED = "supported", "weakly_supported", "unsupported"
SUPPORT_LEVEL = {"overtime_overload": SUPPORTED, "stalled_progression": SUPPORTED,
                 "low_engagement": SUPPORTED, WEAK: WEAKLY_SUPPORTED,
                 "season_end_exit": SUPPORTED, "pay_gap": SUPPORTED,
                 UNSUPPORTED: NOT_SUPPORTED}

# Driver category -> model features (raw names; one-hot columns map by their prefix).
DRIVER_GROUPS: dict[str, list[str]] = {
    "overtime_overload": ["overtime_hours", "overtime_roll4_mean", "overtime_window_mean",
                          "load_ratio", "weekly_off_skipped_4w", "weeks_since_weekend_off",
                          "consecutive_days_worked"],
    "stalled_progression": ["months_since_raise"],
    "low_engagement": ["pulse_score", "pulse_roll4_mean", "pulse_trend_4w",
                       "task_score_roll4_mean", "task_score_trend_4w"],
    "clustered_leave_burnout": ["weeks_without_leave", "leave_days", "festival_leave_days_12w"],
    "season_end_exit": ["days_until_contract_end", "contract_type"],
    "pay_gap": ["pay_ratio", "monthly_pay"],
    UNSUPPORTED: [],
}
# Context features: they move risk but are not something a manager can act on as a driver.
CONTEXT_FEATURES = ["department", "role", "is_department_head", "tenure_days", "peer_exits"]
CATEGORY_TITLES = {
    "overtime_overload": "Overtime overload",
    "stalled_progression": "Stalled progression",
    "low_engagement": "Low engagement",
    "clustered_leave_burnout": "Clustered-leave burnout",
    "season_end_exit": "Season-end exit",
    "pay_gap": "Pay gap",
    UNSUPPORTED: "Manager relationship",
}


def _feature_of(column: str) -> str:
    """Map a design column (raw or one-hot 'feature_value') to its raw feature name."""
    for feats in [*DRIVER_GROUPS.values(), CONTEXT_FEATURES]:
        for f in feats:
            if column == f or column.startswith(f + "_"):
                return f
    raise KeyError(f"design column {column!r} has no driver group")


def category_of(feature: str) -> str | None:
    """Driver category of a raw feature (None for context features)."""
    return next((c for c, feats in DRIVER_GROUPS.items() if feature in feats), None)


def shap_values(scorer: LightGBMScorer, df: pd.DataFrame) -> pd.DataFrame:
    """Per-row SHAP value (log-odds) of every design column; the bias column is dropped."""
    contrib = scorer.model.booster_.predict(scorer.design(df), pred_contrib=True)
    return pd.DataFrame(contrib[:, :-1], columns=scorer.columns, index=df.index)


def category_contributions(shap: pd.DataFrame) -> pd.DataFrame:
    """Sum feature contributions per driver category (context features are left out)."""
    cats = {c: [col for col in shap.columns if category_of(_feature_of(col)) == c]
            for c in DRIVER_GROUPS}
    return pd.DataFrame({c: shap[cols].sum(axis=1) if cols else 0.0 for c, cols in cats.items()},
                        index=shap.index)


def top_categories(contrib: pd.Series, min_logodds: float, n: int = TOP_DRIVERS) -> list[str]:
    """Categories adding at least min_logodds to the log-odds, largest first."""
    positive = contrib[(contrib >= min_logodds) & (contrib > 0) & (contrib.index != UNSUPPORTED)]
    return list(positive.sort_values(ascending=False).index[:n])


def _fmt(v: float, digits: int = 1) -> str:
    return f"{v:.{digits}f}"


REASONS: dict[str, Callable[[pd.Series], str]] = {
    "overtime_overload": lambda r: (
        f"averaging {_fmt(r['overtime_window_mean'])} h overtime a week recently, "
        f"{int(r['weeks_since_weekend_off'])} week(s) since a weekend off"),
    "stalled_progression": lambda r: (
        f"{_fmt(r['months_since_raise'], 0)} months since the last raise"),
    "low_engagement": lambda r: (
        f"pulse {_fmt(r['pulse_roll4_mean'])}/5 over 4 weeks (change {r['pulse_trend_4w']:+.1f}), "
        f"task score trend {r['task_score_trend_4w']:+.1f}"),
    "clustered_leave_burnout": lambda r: (
        f"{int(r['weeks_without_leave'])} week(s) without leave; "
        f"{int(r['festival_leave_days_12w'])} leave day(s) bunched before a festival"),
    "season_end_exit": lambda r: (
        f"seasonal contract ends in {int(r['days_until_contract_end'])} days"
        if r["contract_type"] == "seasonal" else "contract timing"),
    "pay_gap": lambda r: f"paid {_fmt(100 * r['pay_ratio'], 0)}% of the role average",
}


def plain_reason(category: str, row: pd.Series) -> str:
    return f"{CATEGORY_TITLES[category]}: {REASONS[category](row)}"


def load_playbook(path: Path = PLAYBOOK_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def actions_for(categories: list[str], playbook: dict) -> list[dict]:
    """Playbook interventions for the given categories, in driver order."""
    return [dict(a, driver=c) for c in categories for a in playbook["drivers"][c]["interventions"]]


def global_importance(contrib: pd.DataFrame) -> pd.Series:
    """Mean |contribution| per driver category over the rows (feature-level contributions in)."""
    cats = category_contributions(contrib)
    return cats.abs().mean().sort_values(ascending=False).pipe(
        lambda s: s.astype(float).round(4)).rename("mean_abs_logodds").replace({np.nan: 0.0})
