"""Week-by-week SYNTHETIC attrition: behaviour, exits, renewals and replacement hires.

Each simulated week (the complete Monday weeks of Task 3's dept_week_load):
  1. Roster = everyone employed on at least one day of the week (hire_date <= week end and
     not exited before week start).
  2. Dynamic load per department: required_hours (from Task 3, unchanged) divided by
     available_hours = sum over roster of days_employed_this_week / 7 * standard_weekly_hours.
     So exits and hires change load_ratio from the following week on. Task 3's static
     dept_week_load.csv is NOT modified; the dynamic version is a separate output.
  3. For each roster employee, in id order: overtime, pulse, leave, then exit resolution.
     A seasonal contract ending this week is resolved first (renew or seasonal_end exit);
     the hazard is only drawn if the contract did not end, so the two never double-apply.
  4. Every exit schedules a replacement hire (same department, role AND contract type) after
     a vacancy gap, created with Task 3's generate_employee and a fresh latent row. The
     replacement may start after the last simulated week; it is still recorded as scheduled.

Exit reasons: "resignation" (hazard-driven, voluntary) and "seasonal_end".

Resignation hazard (Task T4): a logistic function of OBSERVABLE drivers (sustained overtime,
weeks without leave, low or falling pulse, pay gap, months since raise, load, peer exits,
first year), the hidden latent_frustration and a weekly noise shock, plus an intercept that
run_attrition calibrates to target_annual_attrition (see behaviour.py and config.yaml).
Each week every employee may also get a pay raise (pay_changes output), so pay ratio and
months-since-raise evolve over time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ml.generator.behaviour import (
    DAYS_PER_MONTH,
    DriverInputs,
    compute_exit_hazard,
    compute_weekly_leave,
    compute_weekly_overtime,
    compute_weekly_pulse,
    draw_raise,
    draw_vacancy_days,
    driver_contributions,
)
from ml.generator.config import GeneratorConfig, is_head_role
from ml.generator.staff import (
    DAYS_PER_YEAR,
    EMPLOYEE_COLUMNS,
    LATENT_COLUMNS,
    employee_id,
    generate_employee,
    next_month_day,
)

BEHAVIOUR_COLUMNS = [
    "employee_id",
    "week_start",
    "department",
    "role",
    "load_ratio",
    "overtime_hours",
    "pulse_score",
    "leave_days",
    "is_active",
]
EXIT_COLUMNS = [
    "employee_id",
    "exit_date",
    "exit_reason",
    "tenure_days_at_exit",
    "replacement_employee_id",
]
RENEWAL_COLUMNS = ["employee_id", "renewal_date", "new_contract_end_date"]
PAY_CHANGE_COLUMNS = ["employee_id", "effective_date", "monthly_pay"]
ROLL_WEEKS = 4
DYNAMIC_LOAD_COLUMNS = [
    "week_start",
    "department",
    "occupied_room_nights",
    "required_hours",
    "headcount",
    "available_hours",
    "load_ratio",
]
RESIGNATION, SEASONAL_END = "resignation", "seasonal_end"


@dataclass
class _Employee:
    """Mutable simulation state for one employee."""

    row: dict[str, object]
    latent: dict[str, float]  # LATENT_COLUMNS -> value
    contract_end: date | None
    exit_date: date | None = None
    prev_pulse: float | None = None
    pay: float = 0.0
    last_raise: date | None = None
    weeks_without_leave: int = 0
    overtime_hist: list[float] = field(default_factory=list)
    pulse_hist: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.pay = float(self.row["monthly_pay"])
        self.last_raise = self.row["last_raise_date"]

    @property
    def id(self) -> str:
        return str(self.row["employee_id"])

    @property
    def hire(self) -> date:
        return self.row["hire_date"]

    @property
    def department(self) -> str:
        return str(self.row["department"])


@dataclass(frozen=True)
class AttritionResult:
    weekly_behaviour: pd.DataFrame
    exits: pd.DataFrame
    contract_renewals: pd.DataFrame
    employees: pd.DataFrame  # employee_v2: initial staff + replacement hires
    latent: pd.DataFrame  # initial + replacement latent rows
    dept_week_load_dynamic: pd.DataFrame
    pay_changes: pd.DataFrame
    intercept: float


@dataclass
class _Log:
    behaviour: list[dict[str, object]] = field(default_factory=list)
    exits: list[dict[str, object]] = field(default_factory=list)
    renewals: list[dict[str, object]] = field(default_factory=list)
    load: list[dict[str, object]] = field(default_factory=list)
    pay_changes: list[dict[str, object]] = field(default_factory=list)


def _as_date(value: object) -> date | None:
    if value is None or (isinstance(value, float) and np.isnan(value)) or value == "":
        return None
    if isinstance(value, date):
        return value.date() if isinstance(value, pd.Timestamp) else value
    return date.fromisoformat(str(value))


def normalise_employees(employee: pd.DataFrame) -> pd.DataFrame:
    """Coerce CSV-loaded employee columns to the types generate_employee produces."""
    df = employee.copy()
    for col in ("hire_date", "last_raise_date", "contract_end_date"):
        df[col] = df[col].map(_as_date).astype(object)
    df["manager_id"] = df["manager_id"].fillna("").astype(str)
    df["is_department_head"] = df["is_department_head"].astype(bool)
    df["monthly_pay"] = df["monthly_pay"].astype(int)
    return df[EMPLOYEE_COLUMNS]


def days_in_week(hire: date, week_start: date) -> int:
    """Days of the week [week_start, week_start + 6] on or after hire (0..7)."""
    first = max(hire, week_start)
    return max((week_start + timedelta(days=6) - first).days + 1, 0)


def tenure_years(hire: date, on: date) -> float:
    return max((on - hire).days, 0) / DAYS_PER_YEAR


def peer_exit_count(dept_exits: list[date], week_start: date, window_weeks: int) -> int:
    """Department exits with exit_date in [week_start - window, week_start)."""
    lo = week_start - timedelta(weeks=window_weeks)
    return sum(lo <= d < week_start for d in dept_exits)


def _push(hist: list[float], value: float, keep: int) -> None:
    hist.append(value)
    del hist[:-keep]


def _week_loads(
    roster: list[_Employee], week_start: date, static: pd.DataFrame, hours: float
) -> dict[str, dict[str, object]]:
    """Dynamic load per department for one week from the current roster."""
    loads = {}
    for row in static.itertuples():
        members = [e for e in roster if e.department == row.department]
        available = sum(days_in_week(e.hire, week_start) for e in members) / 7 * hours
        loads[row.department] = {
            "week_start": week_start,
            "department": row.department,
            "occupied_room_nights": int(row.occupied_room_nights),
            "required_hours": float(row.required_hours),
            "headcount": len(members),
            "available_hours": round(available, 2),
            "load_ratio": round(row.required_hours / available, 4) if available else np.inf,
        }
    return loads


def _resolve_exit(
    rng: np.random.Generator,
    cfg: GeneratorConfig,
    emp: _Employee,
    week_start: date,
    drivers: DriverInputs,
    intercept: float,
    log: _Log,
) -> tuple[date, str] | None:
    """Seasonal contract end first (renew or exit), else a resignation hazard draw."""
    a = cfg.attrition
    week_end = week_start + timedelta(days=6)
    end = emp.contract_end
    if a.seasonal_contract_end_is_exit and end is not None and week_start <= end <= week_end:
        if rng.random() >= a.seasonal_renewal_prob:
            return end, SEASONAL_END
        options = cfg.staff.seasonal_contract_end_options
        emp.contract_end = next_month_day(end, options[int(rng.integers(len(options)))])
        log.renewals.append(
            {"employee_id": emp.id, "renewal_date": end, "new_contract_end_date": emp.contract_end}
        )
    h = a.hazard
    noise = float(rng.normal(0.0, h.noise_sd))
    hazard = compute_exit_hazard(
        intercept, driver_contributions(drivers, h), emp.latent["latent_frustration"], noise, h
    )
    if rng.random() < hazard:
        day = week_start + timedelta(days=int(rng.integers(7)))
        return max(day, emp.hire), RESIGNATION
    return None


def _hire_replacement(
    rng: np.random.Generator,
    cfg: GeneratorConfig,
    leaver: _Employee,
    exit_date: date,
    new_id: str,
    head_of: dict[str, str],
) -> _Employee:
    role = str(leaver.row["role"])
    hire = exit_date + timedelta(days=draw_vacancy_days(rng, cfg.attrition))
    if is_head_role(role):
        head_of[leaver.department] = new_id
    row, latent_row = generate_employee(
        rng,
        cfg,
        emp_id=new_id,
        department=leaver.department,
        role=role,
        hire_date=hire,
        as_of=hire,
        manager_id=head_of[leaver.department],
        # Task 4c: keep the leaver's contract type, so seasonal headcount does not drain away
        # (before, a seasonal leaver was replaced by a seasonal hire only 25-30% of the time).
        contract_type=str(leaver.row["contract_type"]),
    )
    latent = {c: float(latent_row[c]) for c in LATENT_COLUMNS}
    return _Employee(row=row, latent=latent, contract_end=row["contract_end_date"])


def _apply_raise(
    rng: np.random.Generator, cfg: GeneratorConfig, emp: _Employee, week_start: date, log: _Log
) -> None:
    months = (week_start - emp.last_raise).days / DAYS_PER_MONTH
    pct = draw_raise(rng, months, cfg.attrition.raises)
    if pct > 0:
        emp.pay = round(emp.pay * (1 + pct))
        emp.last_raise = week_start
        log.pay_changes.append(
            {"employee_id": emp.id, "effective_date": week_start, "monthly_pay": int(emp.pay)}
        )


def _driver_inputs(
    cfg: GeneratorConfig, emp: _Employee, week_start: date, load_ratio: float, peer_exits: int
) -> DriverInputs:
    pulse = emp.pulse_hist
    role_mean = cfg.roles[emp.department][str(emp.row["role"])].pay_mean
    return DriverInputs(
        overtime_avg=float(np.mean(emp.overtime_hist[-cfg.attrition.hazard.overtime_window_weeks:])),
        weeks_without_leave=emp.weeks_without_leave,
        pulse_4wk=float(np.mean(pulse[-ROLL_WEEKS:])),
        pulse_drop_4wk=pulse[0] - pulse[-1] if len(pulse) > ROLL_WEEKS else 0.0,
        pay_ratio=emp.pay / role_mean,
        months_since_raise=(week_start - emp.last_raise).days / DAYS_PER_MONTH,
        load_ratio=load_ratio,
        peer_exits=peer_exits,
        tenure_years=tenure_years(emp.hire, week_start),
    )


def _simulate_employee_week(
    rng: np.random.Generator,
    cfg: GeneratorConfig,
    emp: _Employee,
    week_start: date,
    load_ratio: float,
    peer_exits: int,
    intercept: float,
    log: _Log,
) -> tuple[date, str] | None:
    """Append one behaviour row; return (exit_date, reason) if the employee exits."""
    a = cfg.attrition
    lat = emp.latent
    overtime = compute_weekly_overtime(
        rng, lat["overtime_propensity"], load_ratio, cfg.staff.standard_weekly_hours, a
    )
    pulse = compute_weekly_pulse(
        rng,
        lat["baseline_pulse"],
        lat["latent_frustration"],
        load_ratio,
        overtime,
        emp.prev_pulse,
        a,
    )
    emp.prev_pulse = pulse
    leave = compute_weekly_leave(rng, week_start, a)
    emp.weeks_without_leave = 0 if leave > 0 else emp.weeks_without_leave + 1
    _push(emp.overtime_hist, round(overtime, 2),
          max(ROLL_WEEKS, cfg.attrition.hazard.overtime_window_weeks))
    _push(emp.pulse_hist, round(pulse, 3), ROLL_WEEKS + 1)
    _apply_raise(rng, cfg, emp, week_start, log)
    drivers = _driver_inputs(cfg, emp, week_start, load_ratio, peer_exits)
    exit_ = _resolve_exit(rng, cfg, emp, week_start, drivers, intercept, log)
    log.behaviour.append(
        {
            "employee_id": emp.id,
            "week_start": week_start,
            "department": emp.department,
            "role": emp.row["role"],
            "load_ratio": load_ratio,
            "overtime_hours": round(overtime, 2),
            "pulse_score": round(pulse, 3),
            "leave_days": leave,
            "is_active": exit_ is None,
        }
    )
    return exit_


def simulate_weekly(
    cfg: GeneratorConfig,
    rng: np.random.Generator,
    employee_df: pd.DataFrame,
    latent_df: pd.DataFrame,
    dept_week_load_df: pd.DataFrame,
    intercept: float,
) -> AttritionResult:
    """Run the weekly process over every week in dept_week_load_df (see module docstring).

    `intercept` is the resignation-hazard intercept (run_attrition calibrates it).
    """
    initial = normalise_employees(employee_df)
    latent_by_id = latent_df.set_index("employee_id")[LATENT_COLUMNS].astype(float)
    emps = [
        _Employee(
            row=r,
            latent=latent_by_id.loc[r["employee_id"]].to_dict(),
            contract_end=r["contract_end_date"],
        )
        for r in initial.to_dict("records")
    ]
    head_of = {e.department: e.id for e in emps if e.row["is_department_head"]}
    next_num = max(int(e.id[1:]) for e in emps) + 1
    static = dept_week_load_df.assign(week_start=pd.to_datetime(dept_week_load_df["week_start"]))
    log = _Log()
    dept_exits: dict[str, list[date]] = {d: [] for d in cfg.departments}
    window = cfg.attrition.hazard.peer_exit_window_weeks

    for ts, week_static in static.groupby("week_start", sort=True):
        week_start = ts.date()
        week_end = week_start + timedelta(days=6)
        roster = [
            e for e in emps
            if e.hire <= week_end and (e.exit_date is None or e.exit_date >= week_start)
        ]
        loads = _week_loads(roster, week_start, week_static, cfg.staff.standard_weekly_hours)
        log.load += loads.values()
        # A replacement starting later this same week joins the queue so it gets a row for
        # its first (partial) week; its hours only count towards load from next week.
        queue = list(roster)
        peers = {d: peer_exit_count(x, week_start, window) for d, x in dept_exits.items()}
        for emp in queue:
            ratio = float(loads[emp.department]["load_ratio"])
            exit_ = _simulate_employee_week(
                rng, cfg, emp, week_start, ratio, peers[emp.department], intercept, log
            )
            if exit_ is None:
                continue
            emp.exit_date, reason = exit_
            dept_exits[emp.department].append(emp.exit_date)
            new = _hire_replacement(rng, cfg, emp, emp.exit_date, employee_id(next_num), head_of)
            next_num += 1
            emps.append(new)
            if new.hire <= week_end:
                queue.append(new)
            log.exits.append(
                {
                    "employee_id": emp.id,
                    "exit_date": emp.exit_date,
                    "exit_reason": reason,
                    "tenure_days_at_exit": (emp.exit_date - emp.hire).days,
                    "replacement_employee_id": new.id,
                }
            )

    return AttritionResult(
        weekly_behaviour=pd.DataFrame(log.behaviour, columns=BEHAVIOUR_COLUMNS),
        exits=pd.DataFrame(log.exits, columns=EXIT_COLUMNS),
        contract_renewals=pd.DataFrame(log.renewals, columns=RENEWAL_COLUMNS),
        employees=pd.DataFrame([e.row for e in emps], columns=EMPLOYEE_COLUMNS),
        latent=pd.DataFrame(
            [{"employee_id": e.id, **e.latent} for e in emps],
            columns=["employee_id", *LATENT_COLUMNS],
        ),
        dept_week_load_dynamic=pd.DataFrame(log.load, columns=DYNAMIC_LOAD_COLUMNS),
        pay_changes=pd.DataFrame(log.pay_changes, columns=PAY_CHANGE_COLUMNS),
        intercept=intercept,
    )


def annual_attrition_rate(result: AttritionResult) -> float:
    """Exits (any reason) per year / mean weekly headcount, over the simulated weeks."""
    load = result.dept_week_load_dynamic
    weeks = sorted(pd.to_datetime(load["week_start"]).dt.date.unique())
    horizon_end = weeks[-1] + timedelta(days=6)
    exits = result.exits[pd.to_datetime(result.exits["exit_date"]).dt.date <= horizon_end]
    headcount = load.groupby("week_start")["headcount"].sum().mean()
    return len(exits) / (len(weeks) / 52) / headcount
