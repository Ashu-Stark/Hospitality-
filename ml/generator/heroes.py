"""Scripted demo HEROES (Task T5): five fictional employees for demos only.

Built from heroes.yaml over the last `weeks` simulated weeks. Each hero gets an employee row
(same columns as employee_v2) and weekly rows (weekly_behaviour columns + T5 signal columns),
written to data/demo/. Display names go ONLY to data/demo/hero_display_names.json. Heroes are
never added to the training data files, so they can never enter training or test sets.
The department load_ratio each week is the real simulated load of that department.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from ml.generator.attrition import BEHAVIOUR_COLUMNS
from ml.generator.behaviour import DAYS_PER_MONTH
from ml.generator.config import GeneratorConfig, is_head_role
from ml.generator.signals import (
    DAYS_PER_WEEK,
    SIGNAL_COLUMNS,
    _running_counters,
    festival_dates,
    festival_soon,
)
from ml.generator.staff import EMPLOYEE_COLUMNS

HEROES_PATH = Path(__file__).with_name("heroes.yaml")
HERO_WEEKLY_COLUMNS = BEHAVIOUR_COLUMNS + SIGNAL_COLUMNS[2:]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HeroScript(_Strict):
    display_name: str
    story: str
    department: str
    role: str
    contract_type: str
    contract_end_in_days: int | None = None
    tenure_months: float = Field(gt=0)
    months_since_raise: float = Field(ge=0)
    pay_ratio: float = Field(gt=0)
    overtime_hours: tuple[float, float]
    pulse_score: tuple[float, float]
    task_score: tuple[float, float]
    no_weekend_off_last_weeks: int = Field(ge=0)
    leave_weeks: dict[int, int] = {}


class HeroFile(_Strict):
    weeks: int = Field(gt=0)
    heroes: dict[str, HeroScript]


def load_heroes(path: Path = HEROES_PATH) -> HeroFile:
    return HeroFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _line(pair: tuple[float, float], n: int) -> np.ndarray:
    return np.linspace(pair[0], pair[1], n).round(2)


def _employee_row(hid: str, h: HeroScript, last: pd.Timestamp, cfg: GeneratorConfig,
                  heads: dict[str, str]) -> dict[str, object]:
    pay_mean = cfg.roles[h.department][h.role].pay_mean
    end = (last + timedelta(days=h.contract_end_in_days)).date() if h.contract_end_in_days else None
    head = is_head_role(h.role)
    return {
        "employee_id": hid,
        "department": h.department,
        "role": h.role,
        "is_department_head": head,
        "manager_id": "" if head else heads.get(h.department, ""),
        "hire_date": (last - timedelta(days=round(h.tenure_months * DAYS_PER_MONTH))).date(),
        "contract_type": h.contract_type,
        "contract_end_date": end,
        "monthly_pay": int(round(pay_mean * h.pay_ratio)),
        "last_raise_date": (last - timedelta(
            days=round(h.months_since_raise * DAYS_PER_MONTH))).date(),
    }


def _weekly_rows(hid: str, h: HeroScript, weeks: list[pd.Timestamp], load: pd.DataFrame,
                 festivals: np.ndarray, lookahead: int) -> pd.DataFrame:
    n = len(weeks)
    leave = np.array([h.leave_weeks.get(i + 1, 0) for i in range(n)])
    # final no-weekend-off weeks also skip the weekly day off; otherwise a weekly off every
    # week, falling on a weekend every other week
    skipped = (np.arange(n) >= n - h.no_weekend_off_last_weeks) & (h.no_weekend_off_last_weeks > 0)
    weekend = (np.arange(n) % 2 == 0) & ~skipped
    weeks_since, consecutive = _running_counters(
        np.array([hid] * n), weekend, ~skipped | (leave > 0), np.full(n, DAYS_PER_WEEK // 2))
    ws = pd.Series(weeks)
    dept_load = load[load["department"] == h.department].set_index("week_start")["load_ratio"]
    soon = festival_soon(ws, festivals, lookahead)
    return pd.DataFrame({
        "employee_id": hid,
        "week_start": ws,
        "department": h.department,
        "role": h.role,
        "load_ratio": dept_load.reindex(ws).to_numpy(),
        "overtime_hours": _line(h.overtime_hours, n),
        "pulse_score": _line(h.pulse_score, n),
        "leave_days": leave,
        "is_active": True,
        "task_score": _line(h.task_score, n),
        "weekly_off_skipped": skipped,
        "weekend_off": weekend,
        "weeks_since_weekend_off": weeks_since,
        "consecutive_days_worked": consecutive,
        "leave_before_festival": np.where(soon, leave, 0),
    })[HERO_WEEKLY_COLUMNS]


def build_heroes(
    cfg: GeneratorConfig,
    dept_load_dynamic: pd.DataFrame,
    calendar: pd.DataFrame,
    employees: pd.DataFrame,
    script: HeroFile | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """(hero employees, hero weekly rows, {hero id: display name})."""
    script = script if script is not None else load_heroes()
    load = dept_load_dynamic.assign(week_start=pd.to_datetime(dept_load_dynamic["week_start"]))
    weeks = sorted(load["week_start"].unique())[-script.weeks:]
    last = pd.Timestamp(weeks[-1])
    head_rows = employees[employees["is_department_head"].astype(bool)]
    heads = dict(zip(head_rows["department"], head_rows["employee_id"], strict=False))
    festivals = festival_dates(calendar)
    emp_rows, weekly = [], []
    for hid, h in script.heroes.items():
        emp_rows.append(_employee_row(hid, h, last, cfg, heads))
        weekly.append(_weekly_rows(hid, h, [pd.Timestamp(w) for w in weeks], load, festivals,
                                   cfg.signals.festival_lookahead_days))
    names = {hid: h.display_name for hid, h in script.heroes.items()}
    return (pd.DataFrame(emp_rows, columns=EMPLOYEE_COLUMNS),
            pd.concat(weekly, ignore_index=True), names)
