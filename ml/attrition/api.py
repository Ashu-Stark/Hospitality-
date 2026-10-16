"""Attrition interfaces (Task T9): attrition.score and attrition.rescore, on SYNTHETIC data.

Load the trained bundle from artifacts/attrition/v1/ and the output tables (with the demo heroes
appended for scoring only); never train. Features are built once per process and cached.

rescore() is a SIMULATION, not causal proof: it changes feature values on one employee-week and
re-runs the same trained models. The models learned associations in synthetic data with planted
drivers; a lower re-score says "an employee who looked like this scored lower", not "doing this
will make them stay".
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from ml.attrition.drivers import CATEGORY_TITLES, SUPPORT_LEVEL, load_playbook
from ml.attrition.explain import (
    feature_frame,
    load_bundle,
    load_hero_ids,
    score_week,
    tables_with_heroes,
)
from ml.attrition.features import ARTIFACT_DIR, DATA_DIR, MODEL_FEATURES
from ml.attrition.live_signals import LiveFrame, LiveSignals, live_week_frame
from ml.generator.config import load_config

SIMULATION_NOTE = ("SIMULATION, not causal proof: the same trained models re-scored with changed "
                   "feature values on SYNTHETIC data.")


class Driver(BaseModel):
    category: str
    title: str
    reason: str
    contribution_logodds: float  # from the scoring model, calibrated log-odds vs training mean
    support_level: str  # supported / weakly_supported (generator planted it only in part)


class Action(BaseModel):
    driver: str
    action: str
    owner: str
    check_after_weeks: int
    expected_effect: str  # an ASSUMPTION, never a measured effect


class AttritionScore(BaseModel):
    employee_id: str
    week_start: date
    segment: str  # resignation (permanent) or contract_end (seasonal)
    model: str
    risk: float  # calibrated probability of leaving in the next 90 days
    rank: int  # 1 = highest risk among active non-hero staff of the same group that week
    group_size: int  # number of active non-hero staff in that group that week
    band: str  # high / watch / low
    band_basis: str  # model_rank (permanent: ceil-count rank, ties never split) or
    #                  contract_date_rule (seasonal: days to contract end, config thresholds)
    rank_is_tied: bool  # shares its risk with other staff (common for seasonal contract ends)
    is_demo_hero: bool  # scripted demo employee, placed against the staff, never takes a slot
    drivers: list[Driver]
    actions: list[Action]
    synthetic: bool = True


class HeroInfo(BaseModel):
    """A scripted, fictional DEMO employee (never in training or test data)."""

    employee_id: str
    display_name: str  # first name for demo screens only
    department: str
    role: str
    contract_type: str
    story: str
    synthetic: bool = True


class RescoreResult(BaseModel):
    employee_id: str
    week_start: date
    overrides: dict[str, float | str]
    features_before: dict[str, float | str]
    features_after: dict[str, float | str]
    before: AttritionScore
    after: AttritionScore
    risk_change: float
    note: str = SIMULATION_NOTE


@lru_cache(maxsize=2)
def _state(artifact_dir: Path, data_dir: Path) -> tuple[dict, dict, pd.DataFrame, frozenset]:
    return (load_bundle(artifact_dir), load_playbook(),
            feature_frame(tables_with_heroes(data_dir)), load_hero_ids(data_dir))


def _rows(features: pd.DataFrame, week_start: date | str,
          employee_ids: list[str] | None) -> pd.DataFrame:
    week = pd.Timestamp(week_start)
    rows = features[features["week_start"] == week]
    if rows.empty:
        raise ValueError(f"no active employees in week {week.date()} (weeks start on Monday, "
                         f"{features['week_start'].min().date()}..{features['week_start'].max().date()})")
    if employee_ids is not None:
        missing = sorted(set(employee_ids) - set(rows["employee_id"]))
        if missing:
            raise ValueError(f"not active in week {week.date()}: {missing}")
        rows = rows[rows["employee_id"].isin(employee_ids)]
    return rows


def _to_results(week_rows: pd.DataFrame, bundle: dict, playbook: dict, hero_ids: frozenset,
                extra_outsiders: frozenset = frozenset()) -> dict[str, AttritionScore]:
    """Score a whole week (bands need it); results keyed by employee_id."""
    cfg = load_config().attrition_model
    return {s.employee_id: AttritionScore(
        employee_id=s.employee_id, week_start=date.fromisoformat(s.week_start), segment=s.segment,
        model=s.model, risk=s.risk, rank=s.rank, group_size=s.group_size, band=s.band,
        band_basis=s.band_basis, rank_is_tied=s.rank_is_tied, is_demo_hero=s.is_demo_hero,
        drivers=[Driver(category=c, title=CATEGORY_TITLES[c], reason=r, contribution_logodds=v,
                        support_level=SUPPORT_LEVEL[c])
                 for c, r, v in zip(s.drivers, s.reasons, s.driver_logodds, strict=True)],
        actions=[Action(**a) for a in s.actions],
    ) for s in score_week(week_rows, bundle, cfg, playbook, hero_ids, extra_outsiders)}


def score(week_start: date | str, employee_ids: list[str] | None = None,
          artifact_dir: Path = ARTIFACT_DIR, data_dir: Path = DATA_DIR) -> list[AttritionScore]:
    """Risk, rank, band, top drivers and actions for every (or the given) employee that week."""
    bundle, playbook, features, hero_ids = _state(artifact_dir, data_dir)
    wanted = _rows(features, week_start, employee_ids)
    results = _to_results(_rows(features, week_start, None), bundle, playbook, hero_ids)
    return [results[e] for e in wanted["employee_id"]]


@lru_cache(maxsize=2)
def _bundle(artifact_dir: Path) -> tuple[dict, dict]:
    return load_bundle(artifact_dir), load_playbook()


def score_live(live: LiveSignals, week_start: date | str | None = None,
               employee_ids: list[str] | None = None, artifact_dir: Path = ARTIFACT_DIR,
               ) -> tuple[list[AttritionScore], LiveFrame]:
    """Score from LIVE hotel records (ml/attrition/live_signals.py), same trained models.

    The population for ranks / bands is the live staff of that week; no demo heroes and no
    synthetic rows are mixed in. Returns the scores of the wanted people who have a live record
    that week (others are listed in frame.skipped) and the frame (per-person data sources,
    imputed signals, history length, context).
    """
    frame = live_week_frame(live, week_start, artifact_dir)
    if frame.rows.empty:
        return [], frame
    bundle, playbook = _bundle(artifact_dir)
    results = _to_results(frame.rows, bundle, playbook, frozenset())
    wanted = list(results) if employee_ids is None else [e for e in employee_ids if e in results]
    return [results[e] for e in wanted], frame


def latest_week(artifact_dir: Path = ARTIFACT_DIR, data_dir: Path = DATA_DIR) -> date:
    return _state(artifact_dir, data_dir)[2]["week_start"].max().date()


def _value(v: object) -> float | str:
    return v if isinstance(v, str) else round(float(v), 4)


def rescore(employee_id: str, feature_overrides: dict[str, float | str],
            week_start: date | str | None = None, artifact_dir: Path = ARTIFACT_DIR,
            data_dir: Path = DATA_DIR) -> RescoreResult:
    """Re-score one employee-week with changed feature values. A SIMULATION, not causal proof.

    Before and after, the employee is PLACED against the other active staff of that week (who
    keep their ranks), so a lower risk can move them to a lower band without moving anyone else.
    """
    unknown = sorted(set(feature_overrides) - set(MODEL_FEATURES))
    if unknown:
        raise ValueError(f"unknown features {unknown}; valid names: {MODEL_FEATURES}")
    bundle, playbook, features, hero_ids = _state(artifact_dir, data_dir)
    week = week_start if week_start is not None else latest_week(artifact_dir, data_dir)
    row = _rows(features, week, [employee_id])
    week_rows = _rows(features, week, None)
    changed = row.copy()
    for name, value in feature_overrides.items():
        changed[name] = value
    me = frozenset({employee_id})
    before = _to_results(week_rows, bundle, playbook, hero_ids, me)[employee_id]
    swapped = pd.concat([week_rows.drop(index=row.index), changed])
    after = _to_results(swapped, bundle, playbook, hero_ids, me)[employee_id]
    names = list(feature_overrides)
    return RescoreResult(
        employee_id=employee_id, week_start=before.week_start,
        overrides={k: _value(v) for k, v in feature_overrides.items()},
        features_before={n: _value(row.iloc[0][n]) for n in names},
        features_after={n: _value(changed.iloc[0][n]) for n in names},
        before=before, after=after, risk_change=round(after.risk - before.risk, 4))


def protected_weekends_off(employee_id: str, weekends: int, week_start: date | str | None = None,
                           artifact_dir: Path = ARTIFACT_DIR,
                           data_dir: Path = DATA_DIR) -> dict[str, float]:
    """Feature overrides for 'the last `weekends` weeks each had a protected weekend off'.

    weeks_since_weekend_off -> 0; weekly offs skipped in those weeks are removed from
    weekly_off_skipped_4w; consecutive_days_worked -> the employee's own median in weeks that had
    a weekend off (overtime is left unchanged, a conservative choice).
    """
    features = _state(artifact_dir, data_dir)[2]
    week = pd.Timestamp(week_start if week_start is not None else latest_week(artifact_dir,
                                                                              data_dir))
    tables = tables_with_heroes(data_dir)
    sig = tables["signals"].assign(week_start=pd.to_datetime(tables["signals"]["week_start"]))
    own = sig[(sig["employee_id"] == employee_id) & (sig["week_start"] <= week)].sort_values(
        "week_start")
    recent = own.tail(weekends)
    current = features[(features["employee_id"] == employee_id) & (features["week_start"] == week)]
    if current.empty:
        raise ValueError(f"{employee_id} is not active in week {week.date()}")
    with_off = own.loc[own["weekend_off"].astype(bool), "consecutive_days_worked"]
    rested = float(with_off.median()) if not with_off.empty else float(
        sig.loc[sig["weekend_off"].astype(bool), "consecutive_days_worked"].median())
    skipped_4w = float(current["weekly_off_skipped_4w"].iloc[0])
    return {
        "weeks_since_weekend_off": 0.0,
        "weekly_off_skipped_4w": max(0.0, skipped_4w - float(recent["weekly_off_skipped"].sum())),
        "consecutive_days_worked": rested,
    }


def heroes(data_dir: Path = DATA_DIR) -> list[HeroInfo]:
    """The demo heroes with display name, department and scripted story."""
    from ml.generator.heroes import load_heroes

    names = json.loads((data_dir / "demo" / "hero_display_names.json").read_text("utf-8"))
    script = load_heroes().heroes
    return [HeroInfo(employee_id=h, display_name=names[h], department=script[h].department,
                     role=script[h].role, contract_type=script[h].contract_type,
                     story=script[h].story) for h in names]
