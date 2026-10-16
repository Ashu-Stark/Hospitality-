"""Guarded attrition scoring: attrition.score plus the shared prediction checks.

    from ml.attrition import guarded
    guarded.score("2029-12-24", data_dir=...)   # -> list[GuardedAttritionScore]
    guarded.score_live(LiveSignals(...))        # -> (list[GuardedAttritionScore], skipped)

Every score keeps the model's risk, rank and band, and gains `confidence` and `checks`. A person
whose inputs are missing, outside their allowed range or outside the training distribution
gets the segment's training base rate as risk (source "baseline"), confidence low. Risks are
clipped to 0..1. Batch drift: PSI per feature when the batch has >= 200 rows, else the per-row
z-score / range check only. SYNTHETIC data; staff are ids only.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import Field

from ml import guardrails as G
from ml.attrition import api
from ml.attrition.features import ARTIFACT_DIR, DATA_DIR, MODEL_FEATURES
from ml.attrition.live_signals import LiveSignals, load_live_config

MODEL = "attrition/v1"
LIMITS = {"pulse_score": (1, 5), "pulse_roll4_mean": (1, 5), "load_ratio": (0, 3),
          "overtime_hours": (0, 60), "overtime_roll4_mean": (0, 60),
          "overtime_window_mean": (0, 60), "leave_days": (0, 7), "tenure_days": (0, 20000),
          "monthly_pay": (0, 10_000_000), "pay_ratio": (0, 5), "months_since_raise": (0, 240),
          "consecutive_days_worked": (0, 400), "weeks_since_weekend_off": (0, 520)}
# PSI only on person-level features. Department-week values (load_ratio, peer_exits: one value
# per department that week) and seasonal ones (overtime, leave, contract dates) differ from the
# all-year training mix in any single week by design, so a weekly PSI on them is not drift.
PSI_FEATURES = ["pay_ratio", "months_since_raise", "monthly_pay", "pulse_score",
                "pulse_roll4_mean", "task_score_roll4_mean", "weeks_since_weekend_off"]


DEMO_SOURCES = ["synthetic demo data"]


class GuardedAttritionScore(api.AttritionScore):
    source: str = "model"  # model / baseline (guardrail fallback)
    confidence: str
    checks: list[G.Check]
    # where the INPUTS came from: live (the hotel's own HOI records, ml/attrition/live_signals.py)
    # or demo_synthetic (the seeded synthetic tables in ml/data). Never mixed for one person.
    data_source: str = "demo_synthetic"
    weeks_of_history: int | None = None  # live weeks behind this score (None for demo data)
    data_sources: list[str] = Field(default_factory=lambda: list(DEMO_SOURCES))  # e.g. shifts, jobs
    missing: list[dict] = Field(default_factory=list)  # imputed live signals (signal, features,
    #                                                    imputed_with)
    context: dict = Field(default_factory=dict)  # live context-only signals (not model inputs)


def _base_rates(artifact_dir: Path) -> dict[str, float]:
    m = json.loads((artifact_dir / "metrics.json").read_text("utf-8"))
    return {seg: float(v["test"][v["winner"]]["base_rate"]) for seg, v in m.items()}


def _guard(scores: list[api.AttritionScore], rows: pd.DataFrame, artifact_dir: Path,
           today: date | None, overrides: dict[str, dict[str, float]] | None = None,
           ) -> list[GuardedAttritionScore]:
    """The shared checks. rows: the week's feature rows indexed by employee_id."""
    rows = rows.copy()
    for e, vals in (overrides or {}).items():
        for k, v in vals.items():
            rows.loc[e, k] = v
    x = rows[MODEL_FEATURES]
    ref = G.load_reference(artifact_dir)
    checks: list[G.Check] = []
    stale = G.staleness(ref, today or date.today(), checks, MODEL)
    missing = G.validate_schema(x, MODEL_FEATURES, checks, MODEL)
    bad = G.validate_ranges(x, LIMITS, checks, MODEL)
    ood, level = G.drift_check(x, ref, checks, MODEL,
                               psi_features=PSI_FEATURES)
    fallback = missing | bad | ood | stale
    # confidence: a calibrated probability has no range, so the ceiling is medium (ASSUMED);
    # drift or a fallback lowers it
    base = _base_rates(artifact_dir)
    risks = G.clip(np.array([s.risk for s in scores]), 0, 1, checks, "risk", MODEL)
    n_fb = int(fallback.loc[[s.employee_id for s in scores]].sum()) if scores else 0
    if n_fb:
        G.record(checks, "fallback", "warn", f"{n_fb} of {len(scores)} person(s) got the "
                 "training base rate instead of a model score", MODEL)
    out = []
    for s, r in zip(scores, risks, strict=True):
        fb = bool(fallback.get(s.employee_id, False))
        row_checks = list(checks)
        if fb:
            why = [n for n, m in (("missing input", missing), ("input out of range", bad),
                                  ("outside training data", ood)) if m.get(s.employee_id, False)]
            row_checks.append(G.Check(name="row_fallback", status="warn",
                                      detail=f"{', '.join(why) or 'stale model'}: risk = "
                                             f"training base rate {base[s.segment]:.3f}"))
        conf = G.confidence(None, level, 1.0 if fb else 0.0, stale)
        out.append(GuardedAttritionScore(**{**s.model_dump(), "risk": base[s.segment] if fb
                                            else round(float(r), 4)},
                                         source="baseline" if fb else "model",
                                         confidence=conf, checks=row_checks))
    return out


def score(week_start: date | str | None = None, employee_ids: list[str] | None = None,
          artifact_dir: Path = ARTIFACT_DIR, data_dir: Path = DATA_DIR,
          today: date | None = None,
          overrides: dict[str, dict[str, float]] | None = None) -> list[GuardedAttritionScore]:
    """attrition.score with checks, on the SYNTHETIC demo tables (data_source demo_synthetic).
    overrides {employee_id: {feature: value}} replace input values for the CHECKS only (tests);
    the model score itself is unchanged."""
    week = week_start or api.latest_week(artifact_dir, data_dir)
    scores = api.score(week, employee_ids, artifact_dir=artifact_dir, data_dir=data_dir)
    _, _, features, _ = api._state(artifact_dir, data_dir)
    rows = api._rows(features, week, None).set_index("employee_id")
    return _guard(scores, rows, artifact_dir, today, overrides)


def score_live(live: LiveSignals, week_start: date | str | None = None,
               employee_ids: list[str] | None = None, artifact_dir: Path = ARTIFACT_DIR,
               today: date | None = None,
               ) -> tuple[list[GuardedAttritionScore], dict[str, str]]:
    """attrition.score_live with the same checks plus the live data-quality rules:
    fewer than live_signals.yaml min_weeks_for_confidence weeks of history -> confidence low
    (check short_history); every imputed signal is listed in `missing`.
    Returns (scores, skipped {employee_id: why no live score})."""
    scores, frame = api.score_live(live, week_start, employee_ids, artifact_dir)
    if not scores:
        return [], frame.skipped
    guarded = _guard(scores, frame.rows.set_index("employee_id"), artifact_dir, today)
    min_weeks = int(load_live_config()["min_weeks_for_confidence"])
    out = []
    for g in guarded:
        info = frame.people[g.employee_id]
        checks = list(g.checks)
        conf = g.confidence
        if info.weeks_of_history < min_weeks:
            conf = "low"
            checks.append(G.Check(name="short_history", status="warn",
                                  detail=f"{info.weeks_of_history} week(s) of live records; "
                                         f"fewer than {min_weeks} gives low confidence"))
        if info.missing:
            checks.append(G.Check(name="imputed_signals", status="warn",
                                  detail="not available, training average used: " + ", ".join(
                                      m["signal"] for m in info.missing)))
        out.append(g.model_copy(update={
            "confidence": conf, "checks": checks, "data_source": "live",
            "weeks_of_history": info.weeks_of_history, "data_sources": info.data_sources,
            "missing": info.missing, "context": info.context}))
    return out, frame.skipped


def high_band_count(scores: list[api.AttritionScore]) -> int:
    return sum(1 for s in scores if s.band == "high" and not s.is_demo_hero)


def week_frame(scores: list[api.AttritionScore]) -> pd.DataFrame:
    return pd.DataFrame([{"employee_id": s.employee_id, "band": s.band, "risk": s.risk}
                         for s in scores])


class GuardedRescore(api.RescoreResult):
    confidence: str
    checks: list[G.Check]


def rescore(employee_id: str, feature_overrides: dict[str, float | str],
            week_start: date | str | None = None, artifact_dir: Path = ARTIFACT_DIR,
            data_dir: Path = DATA_DIR, today: date | None = None) -> GuardedRescore:
    """attrition.rescore with checks on the CHANGED inputs. A what-if outside the allowed range
    or the training data is still answered (it is a simulation) but marked low confidence."""
    r = api.rescore(employee_id, feature_overrides, week_start, artifact_dir=artifact_dir,
                    data_dir=data_dir)
    ref = G.load_reference(artifact_dir)
    checks: list[G.Check] = []
    stale = G.staleness(ref, today or date.today(), checks, MODEL)
    x = pd.DataFrame([{k: r.features_after.get(k) for k in MODEL_FEATURES}])
    bad = G.validate_ranges(x, LIMITS, checks, MODEL)
    ood, _ = G.drift_check(x, ref, checks, MODEL, psi_features=[],
                           psi_skip_reason="one person")
    G.clip(np.array([r.before.risk, r.after.risk]), 0, 1, checks, "risk", MODEL)
    risky = bool(bad.any() or ood.any() or stale)
    if risky:
        G.record(checks, "what_if", "warn", "the changed inputs are outside the allowed range "
                 "or the training data: treat this simulated change as unreliable", MODEL)
    return GuardedRescore(**r.model_dump(), confidence="low" if risky else "medium",
                          checks=checks)
