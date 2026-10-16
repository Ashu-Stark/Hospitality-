"""Live staff signals -> the attrition model's feature rows (no retraining).

The model was trained on SYNTHETIC weekly tables (employee_v2, weekly_behaviour, weekly_signals,
exits, ...). A real hotel produces different raw facts: a published roster, dispatch jobs, leave
marks, thank-you points, logged check-ins, an optional 1-tap weekly answer and an owner / HR record
(joining date, pay band, last raise). This module turns those weekly facts into the SAME tables and
runs the SAME feature code (features.build_attrition_features), so the feature names, meanings and
scales stay those of training and no retrain is needed. Pure: plain records in, a frame out; no
database, no network, never reads ml/data/internal/ or the synthetic CSVs.

Feature -> live source (ASSUMED mappings, values in live_signals.yaml):
  department, contract_type          staff record
  role, is_department_head           HR record `role` or the job title (role_keywords)
  tenure_days                        HR record joining_date
  monthly_pay, pay_ratio             HR record monthly_pay, else pay_band x the role's average pay
  months_since_raise                 HR record last_raise_date
  days_until_contract_end            HR record contract_end_date (seasonal staff)
  peer_exits                         HR records with left_on (same department, last N weeks)
  overtime_hours (+ 4w / window)     planned roster hours + minutes finished after shift end - 48 h
  load_ratio                         department's roster hours / (people x 48 h), a PROXY for the
                                     generator's demand / available hours
  weeks_since_weekend_off,
  consecutive_days_worked,
  weekly_off_skipped_4w              roster days worked + leave marks, carried across weeks
  leave_days, weeks_without_leave    leave / absence marks (no reasons, no health information)
  festival_leave_days_12w            leave marks near the given festival dates
  pulse_score (+ 4w mean, trend)     "How was your week?" good / ok / hard (consented)
  task_score_roll4_mean, _trend_4w   dispatch jobs: on time, declines / timeouts, response time

Context signals (shown with the score, NOT model inputs because the model never saw them):
night shifts, short rests (< min_rest_hours), declines / timeouts, response-time trend, share of
the team's jobs, thank-you points trend, logged check-ins.

Missing signals are imputed with the TRAINING average (reference_stats.json, SYNTHETIC data): for
the logistic winner that means "no contribution" from that feature. Every imputed signal is listed
per person in `missing`. A person is scored from live records only: synthetic values are never
mixed in for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Literal

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, Field, field_validator

from ml import guardrails as G
from ml.attrition.features import ARTIFACT_DIR, MODEL_FEATURES, build_attrition_features
from ml.generator.attrition import RESIGNATION, SEASONAL_END
from ml.generator.config import GeneratorConfig, load_config

CONFIG_PATH = Path(__file__).with_name("live_signals.yaml")
DAYS = 7
SAT, SUN = 5, 6
ROLL = 4
Pulse = Literal["good", "ok", "hard"]

# plain-language source names (shown on screens: "Based on: shifts, jobs, ...")
SHIFTS, JOBS, THANKS, CHECKINS = "shifts", "jobs", "thank-yous", "check-ins"
ANSWERS, LEAVE, HR = "weekly answers", "leave marks", "HR record"
SOURCE_ORDER = (SHIFTS, JOBS, THANKS, CHECKINS, ANSWERS, LEAVE, HR)

# signal group -> the model features it fills
GROUPS: dict[str, tuple[str, ...]] = {
    "shifts": ("overtime_hours", "overtime_roll4_mean", "overtime_window_mean", "load_ratio",
               "weeks_since_weekend_off", "consecutive_days_worked", "weekly_off_skipped_4w"),
    "jobs": ("task_score_roll4_mean", "task_score_trend_4w"),
    "weekly answers": ("pulse_score", "pulse_roll4_mean", "pulse_trend_4w"),
    "leave marks": ("leave_days", "weeks_without_leave", "festival_leave_days_12w"),
    "festival dates": ("festival_leave_days_12w",),
    "joining date": ("tenure_days",),
    "pay": ("monthly_pay", "pay_ratio"),
    "last raise date": ("months_since_raise",),
    "contract end date": ("days_until_contract_end",),
}


# ------------------------------------------------------------------ inputs (plain records)
def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


class StaffProfile(BaseModel):
    """One staff member: ids and work facts only (no names or personal attributes)."""

    employee_id: str = Field(max_length=40)
    department: str = Field(max_length=40)
    role_title: str = Field(default="", max_length=80)
    role: str | None = Field(default=None, max_length=40)  # model role code, else from the title
    contract_type: Literal["permanent", "seasonal"] = "permanent"
    is_department_head: bool | None = None
    joining_date: date | None = None
    contract_end_date: date | None = None
    pay_band: Literal["below", "at", "above"] | None = None
    monthly_pay: float | None = Field(default=None, ge=0, le=10_000_000)
    last_raise_date: date | None = None
    left_on: date | None = None
    pay_withheld: bool = False  # the caller may not see pay (e.g. a department head)


class WeekRecord(BaseModel):
    """One person's facts for one week (Monday start, hotel local time)."""

    employee_id: str = Field(max_length=40)
    week_start: date
    roster_published: bool = False  # this week's roster is known (else the shift facts are unknown)
    worked_days: list[int] = Field(default_factory=list)  # 0 = Monday .. 6 = Sunday, rostered
    shift_hours: float = Field(default=0.0, ge=0, le=168)
    night_shifts: int = Field(default=0, ge=0, le=7)
    short_rest: int = Field(default=0, ge=0, le=7)  # rests shorter than min_rest_hours
    late_finish_minutes: float | None = Field(default=None, ge=0, le=10_080)
    leave_days: list[int] = Field(default_factory=list)  # days marked leave / absent (no reason)
    jobs_offered: int = Field(default=0, ge=0)  # offers answered (accepted + declined + timed out)
    jobs_declined: int = Field(default=0, ge=0)
    jobs_timed_out: int = Field(default=0, ge=0)
    jobs_done: int = Field(default=0, ge=0)
    jobs_on_time: int = Field(default=0, ge=0)
    team_jobs_done: int = Field(default=0, ge=0)  # the department's finished jobs that week
    median_response_seconds: float | None = Field(default=None, ge=0)
    recognition_points: int | None = Field(default=None, ge=0)
    checkins: int = Field(default=0, ge=0)  # logged "We talked" check-ins
    pulse: Pulse | None = None

    @field_validator("week_start")
    @classmethod
    def _monday(cls, v: date) -> date:
        return monday(v)

    @field_validator("worked_days", "leave_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("days are 0 (Monday) .. 6 (Sunday)")
        return sorted(set(v))


class LiveSignals(BaseModel):
    """What the platform knows about the staff, week by week (ids only)."""

    profiles: list[StaffProfile] = Field(default_factory=list, max_length=2000)
    records: list[WeekRecord] = Field(default_factory=list, max_length=60_000)
    leave_marks_used: bool = False  # the hotel records leave / absence marks at all
    festival_dates: list[date] | None = None  # None: festival leave is unknown (imputed)
    note: str = Field(default="", max_length=300)


# ------------------------------------------------------------------ outputs
@dataclass
class PersonInfo:
    weeks_of_history: int
    data_sources: list[str]
    missing: list[dict]  # {"signal", "features", "imputed_with"}
    context: dict  # context-only signals (not model inputs)


@dataclass
class LiveFrame:
    week_start: date | None
    rows: pd.DataFrame  # one row per scored person that week: ids + MODEL_FEATURES + labels
    people: dict[str, PersonInfo] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)  # employee_id -> why not scored


@lru_cache(maxsize=4)
def load_live_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def training_means(artifact_dir: Path = ARTIFACT_DIR) -> dict[str, float]:
    ref = G.load_reference(artifact_dir) or {}
    return {k: float(v["mean"]) for k, v in ref.get("features", {}).items() if "mean" in v}


def role_code(department: str, title: str, lc: dict) -> str:
    rules = lc["role_keywords"][department]
    low = (title or "").lower()
    return next((code for kw, code in rules["rules"] if kw in low), rules["default"])


def task_score(r: WeekRecord, lc: dict) -> float:
    """Work-quality score 0-100 on the training scale; NaN when the week has too few jobs."""
    if r.jobs_done < lc["min_jobs_for_task_score"]:
        return np.nan
    w = lc["task_parts"]
    parts = {"on_time": min(1.0, r.jobs_on_time / r.jobs_done)}
    if r.jobs_offered:
        parts["reliability"] = max(0.0, 1 - (r.jobs_declined + r.jobs_timed_out) / r.jobs_offered)
    if r.median_response_seconds is not None:
        fast, slow = lc["response_fast_seconds"], lc["response_slow_seconds"]
        parts["responsiveness"] = float(np.clip((slow - r.median_response_seconds)
                                                / (slow - fast), 0, 1))
    q = sum(w[k] * v for k, v in parts.items()) / sum(w[k] for k in parts)
    lo, hi = lc["task_score_low"], lc["task_score_high"]
    return round(lo + q * (hi - lo), 2)


# ------------------------------------------------------------------ roster counters
def _roster_signals(recs: list[WeekRecord]) -> list[dict]:
    """Per week (sorted): weekly_off_skipped, weekend_off, weeks_since_weekend_off,
    consecutive_days_worked. Weeks without a roster carry the counters unchanged."""
    out, weeks_no_weekend, run = [], 0, 0
    for r in recs:
        if not r.roster_published:
            out.append({"weekly_off_skipped": False, "weekend_off": False,
                        "weeks_since_weekend_off": weeks_no_weekend,
                        "consecutive_days_worked": run})
            continue
        worked = [d in r.worked_days and d not in r.leave_days for d in range(DAYS)]
        for w in worked:
            run = run + 1 if w else 0
        weekend_off = not worked[SAT] and not worked[SUN]
        weeks_no_weekend = 0 if weekend_off else weeks_no_weekend + 1
        out.append({"weekly_off_skipped": all(worked), "weekend_off": weekend_off,
                    "weeks_since_weekend_off": weeks_no_weekend,
                    "consecutive_days_worked": run})
    return out


def _festival_leave(r: WeekRecord, festivals: np.ndarray | None, lookahead: int) -> float:
    if festivals is None:
        return np.nan
    lo = np.datetime64(r.week_start)
    hi = lo + np.timedelta64(DAYS - 1 + lookahead, "D")
    soon = np.searchsorted(festivals, hi, "right") > np.searchsorted(festivals, lo, "left")
    return float(len(r.leave_days)) if soon else 0.0


# ------------------------------------------------------------------ tables
def _profiles(live: LiveSignals, cfg: GeneratorConfig, lc: dict
              ) -> tuple[dict[str, StaffProfile], dict[str, str]]:
    keep, skipped = {}, {}
    for p in live.profiles:
        if p.department not in cfg.roles:
            skipped[p.employee_id] = f"department {p.department} is not scored by the model"
            continue
        role = p.role if p.role in cfg.roles[p.department] else role_code(
            p.department, p.role_title, lc)
        keep[p.employee_id] = p.model_copy(update={"role": role})
    return keep, skipped


def _employees(profiles: dict[str, StaffProfile], first_week: dict[str, date],
               cfg: GeneratorConfig, lc: dict) -> pd.DataFrame:
    rows = []
    for e, p in profiles.items():
        mean_pay = cfg.roles[p.department][p.role].pay_mean
        pay = (p.monthly_pay if p.monthly_pay else
               mean_pay * lc["pay_band_ratio"][p.pay_band] if p.pay_band else mean_pay)
        hire = p.joining_date or first_week.get(e, date.today())
        head = (p.is_department_head if p.is_department_head is not None
                else p.role in lc["head_roles"])
        rows.append({
            "employee_id": e, "department": p.department, "role": p.role,
            "is_department_head": bool(head), "manager_id": "", "hire_date": hire.isoformat(),
            "contract_type": p.contract_type,
            "contract_end_date": p.contract_end_date.isoformat() if p.contract_end_date else "",
            "monthly_pay": float(pay),
            "last_raise_date": (p.last_raise_date or hire).isoformat()})
    return pd.DataFrame(rows)


def _exits(profiles: dict[str, StaffProfile]) -> pd.DataFrame:
    rows = [{"employee_id": e, "exit_date": p.left_on.isoformat(),
             "exit_reason": SEASONAL_END if p.contract_type == "seasonal" else RESIGNATION,
             "tenure_days_at_exit": 0, "replacement_employee_id": ""}
            for e, p in profiles.items() if p.left_on]
    return pd.DataFrame(rows, columns=["employee_id", "exit_date", "exit_reason",
                                       "tenure_days_at_exit", "replacement_employee_id"])


def _weekly_tables(by_emp: dict[str, list[WeekRecord]], profiles: dict[str, StaffProfile],
                   live: LiveSignals, cfg: GeneratorConfig, lc: dict
                   ) -> tuple[pd.DataFrame, pd.DataFrame]:
    std = lc["standard_weekly_hours"]
    festivals = (np.sort(np.array(live.festival_dates, dtype="datetime64[D]"))
                 if live.festival_dates is not None else None)
    lookahead = cfg.signals.festival_lookahead_days
    pulse_values = lc["pulse_values"]
    beh, sig = [], []
    for e, recs in by_emp.items():
        p = profiles[e]
        for r, rs in zip(recs, _roster_signals(recs), strict=True):
            hours = (r.shift_hours + (r.late_finish_minutes or 0) / 60) if r.roster_published \
                else np.nan
            beh.append({"employee_id": e, "week_start": r.week_start.isoformat(),
                        "department": p.department, "role": p.role, "_hours": hours,
                        "overtime_hours": max(0.0, hours - std) if r.roster_published else np.nan,
                        "pulse_score": pulse_values[r.pulse] if r.pulse else np.nan,
                        "leave_days": len(r.leave_days),
                        "is_active": p.left_on is None or p.left_on > r.week_start})
            sig.append({"employee_id": e, "week_start": r.week_start.isoformat(),
                        "task_score": task_score(r, lc), **rs,
                        "leave_before_festival": _festival_leave(r, festivals, lookahead)})
    b = pd.DataFrame(beh)
    # department load PROXY: rostered hours / (rostered people x contract hours), per week
    known = b.dropna(subset=["_hours"])
    load = (known.groupby(["department", "week_start"])["_hours"].agg(["sum", "count"])
            .assign(load_ratio=lambda x: (x["sum"] / (x["count"] * std)).round(4))["load_ratio"])
    b = b.merge(load.reset_index(), on=["department", "week_start"], how="left")
    return b.drop(columns=["_hours"]), pd.DataFrame(sig)


# ------------------------------------------------------------------ per-person description
def _context(recs: list[WeekRecord]) -> dict:
    last, prev = recs[-ROLL:], recs[-2 * ROLL:-ROLL]

    def med(rs: list[WeekRecord]) -> float | None:
        v = [r.median_response_seconds for r in rs if r.median_response_seconds is not None]
        return round(median(v), 1) if v else None

    def pts(rs: list[WeekRecord]) -> int | None:
        v = [r.recognition_points for r in rs if r.recognition_points is not None]
        return sum(v) if v else None

    now = recs[-1]
    return {
        "night_shifts_4w": sum(r.night_shifts for r in last),
        "short_rests_4w": sum(r.short_rest for r in last),
        "late_finish_minutes_4w": round(sum(r.late_finish_minutes or 0 for r in last), 1),
        "declined_or_missed_offers_4w": sum(r.jobs_declined + r.jobs_timed_out for r in last),
        "median_response_seconds_4w": med(last),
        "median_response_seconds_prev_4w": med(prev),
        "share_of_team_jobs": (round(now.jobs_done / now.team_jobs_done, 3)
                               if now.team_jobs_done else None),
        "thank_you_points_4w": pts(last),
        "thank_you_points_prev_4w": pts(prev),
        "checkins_logged": sum(r.checkins for r in recs),
        "note": "Context only: shown with the score, not used in the risk number.",
    }


def _sources(recs: list[WeekRecord], p: StaffProfile, leave_used: bool) -> list[str]:
    have = {
        SHIFTS: any(r.roster_published for r in recs),
        JOBS: any(r.jobs_offered or r.jobs_done for r in recs),
        THANKS: any(r.recognition_points for r in recs),
        CHECKINS: any(r.checkins for r in recs),
        ANSWERS: any(r.pulse for r in recs),
        LEAVE: leave_used,
        HR: bool(p.joining_date or p.pay_band or p.monthly_pay or p.last_raise_date
                 or p.contract_end_date),
    }
    return [s for s in SOURCE_ORDER if have[s]]


def _missing_groups(recs: list[WeekRecord], p: StaffProfile, live: LiveSignals) -> list[str]:
    now, last = recs[-1], recs[-ROLL:]
    miss = []
    if not now.roster_published:
        miss.append("shifts")
    if not any(r.jobs_done for r in last):
        miss.append("jobs")
    if not any(r.pulse for r in last):
        miss.append("weekly answers")
    if not live.leave_marks_used:
        miss.append("leave marks")
    elif live.festival_dates is None:
        miss.append("festival dates")
    if not p.joining_date:
        miss.append("joining date")
    if p.pay_withheld or not (p.monthly_pay or p.pay_band):
        miss.append("pay")
    if not p.last_raise_date:
        miss.append("last raise date")
    if p.contract_type == "seasonal" and not p.contract_end_date:
        miss.append("contract end date")
    return miss


def _impute(row: pd.Series, groups: list[str], means: dict[str, float]
            ) -> tuple[pd.Series, list[dict]]:
    row = row.copy()
    out, done = [], set()
    for g in groups:
        feats = [f for f in GROUPS[g] if f not in done]
        for f in feats:
            row[f] = means[f]
        done.update(feats)
        if feats:
            out.append({"signal": g + (" (owner / HR only)" if g == "pay" else ""),
                        "features": feats,
                        "imputed_with": "training average (SYNTHETIC data): " + ", ".join(
                            f"{f}={means[f]:.3g}" for f in feats)})
    rest = [f for f in MODEL_FEATURES if f in means and pd.isna(row[f])]
    for f in rest:  # any other gap (e.g. too little history for a rolling value)
        row[f] = means[f]
    if rest:
        out.append({"signal": "other", "features": rest,
                    "imputed_with": "training average (SYNTHETIC data)"})
    return row, out


# ------------------------------------------------------------------ entry point
def live_week_frame(live: LiveSignals, week_start: date | str | None = None,
                    artifact_dir: Path = ARTIFACT_DIR,
                    cfg: GeneratorConfig | None = None) -> LiveFrame:
    """Feature rows for one week (default: the latest week with records) from live records."""
    cfg = cfg or load_config()
    lc = load_live_config()
    profiles, skipped = _profiles(live, cfg, lc)
    by_emp: dict[str, list[WeekRecord]] = {}
    for r in sorted(live.records, key=lambda r: (r.employee_id, r.week_start)):
        if r.employee_id in profiles:
            by_emp.setdefault(r.employee_id, []).append(r)
    for e in profiles:
        if e not in by_emp:
            skipped[e] = "no live records yet"
    if not by_emp:
        return LiveFrame(None, pd.DataFrame(columns=["employee_id", "week_start"]), {}, skipped)
    week = (monday(pd.Timestamp(week_start).date()) if week_start is not None
            else max(r.week_start for rs in by_emp.values() for r in rs))
    hist = {e: [r for r in rs if r.week_start <= week] for e, rs in by_emp.items()}
    active = {e: rs for e, rs in hist.items()
              if rs and rs[-1].week_start == week
              and (profiles[e].left_on is None or profiles[e].left_on > week)}
    for e in set(by_emp) - set(active):
        skipped.setdefault(e, f"no live record in week {week}")
    if not active:
        return LiveFrame(week, pd.DataFrame(columns=["employee_id", "week_start"]), {}, skipped)
    first = {e: rs[0].week_start for e, rs in active.items()}
    used = {e: profiles[e] for e in active}
    behaviour, signals = _weekly_tables(active, used, live, cfg, lc)
    feats = build_attrition_features(
        _employees(profiles, first, cfg, lc), behaviour, signals, _exits(profiles),
        pd.DataFrame(columns=["employee_id", "renewal_date", "new_contract_end_date"]),
        pd.DataFrame(columns=["employee_id", "effective_date", "monthly_pay"]), cfg)
    rows = feats[feats["week_start"] == pd.Timestamp(week)].copy()
    means = training_means(artifact_dir)
    people, fixed = {}, []
    for i, row in rows.iterrows():
        e = row["employee_id"]
        new, missing = _impute(row, _missing_groups(active[e], used[e], live), means)
        fixed.append(new.rename(i))
        people[e] = PersonInfo(weeks_of_history=len(active[e]),
                               data_sources=_sources(active[e], used[e], live.leave_marks_used),
                               missing=missing, context=_context(active[e]))
    out = pd.DataFrame(fixed) if fixed else rows
    for f in MODEL_FEATURES:  # restore numeric dtypes after the row-wise fill
        if f in means:
            out[f] = pd.to_numeric(out[f])
    return LiveFrame(week, out.reset_index(drop=True), people, skipped)
