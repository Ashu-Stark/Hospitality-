"""SYNTHETIC staff table plus generator-only latent traits.

Employees are ids only: no names, gender, age, religion, caste, health or family status.
Latent traits drive later simulation (Task 4) and are written to a separate internal file;
they must never be used as model features.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ml.generator.config import GeneratorConfig, RoleSpec, StaffConfig, is_head_role

EMPLOYEE_COLUMNS = [
    "employee_id",
    "department",
    "role",
    "is_department_head",
    "manager_id",
    "hire_date",
    "contract_type",
    "contract_end_date",
    "monthly_pay",
    "last_raise_date",
]
LATENT_COLUMNS = [
    "overtime_propensity",
    "baseline_pulse",
    "baseline_task_score",
    "latent_frustration",
]

DAYS_PER_YEAR = 365.25
PAY_FLOOR_SHARE = 0.7  # monthly pay never drawn below 70% of the role mean

# ASSUMED latent trait distributions (generator-only, not measured).
OVERTIME_LOGNORMAL_SIGMA = 0.3  # mu = -sigma^2 / 2 gives a mean of 1
PULSE_MEAN, PULSE_SD, PULSE_RANGE = 3.8, 0.5, (1.0, 5.0)
TASK_SCORE_MEAN, TASK_SCORE_SD, TASK_SCORE_RANGE = 78.0, 8.0, (40.0, 98.0)
FRUSTRATION_SD = 0.5


def employee_id(n: int) -> str:
    """1 -> 'E001'."""
    return f"E{n:03d}"


def head_role(roles: dict[str, RoleSpec]) -> str:
    return next(r for r in roles if is_head_role(r))


def draw_tenure_years(rng: np.random.Generator, staff: StaffConfig) -> float:
    """Exponential(scale=tenure_mean_years) truncated to [min, max] by inverse CDF."""
    scale = staff.tenure_mean_years
    lo = 1 - np.exp(-staff.tenure_min_years / scale)
    hi = 1 - np.exp(-staff.tenure_max_years / scale)
    return float(-scale * np.log(1 - rng.uniform(lo, hi)))


def next_month_day(after: date, month_day: str) -> date:
    """First date strictly after `after` that falls on 'MM-DD'."""
    candidate = date.fromisoformat(f"{after.year}-{month_day}")
    return candidate if candidate > after else date.fromisoformat(f"{after.year + 1}-{month_day}")


def draw_pay(rng: np.random.Generator, spec: RoleSpec) -> int:
    return int(round(max(rng.normal(spec.pay_mean, spec.pay_sd), PAY_FLOOR_SHARE * spec.pay_mean)))


def draw_last_raise(rng: np.random.Generator, hire_date: date, as_of: date) -> date:
    """hire_date if tenure < 1 year, else a uniform day strictly between hire and as_of."""
    tenure_days = (as_of - hire_date).days
    offset = int(rng.integers(1, max(tenure_days, 2)))  # always draw, keeps streams aligned
    return hire_date if tenure_days < DAYS_PER_YEAR else hire_date + timedelta(days=offset)


def draw_latent(rng: np.random.Generator) -> dict[str, float]:
    sigma = OVERTIME_LOGNORMAL_SIGMA
    return {
        "overtime_propensity": float(rng.lognormal(-(sigma**2) / 2, sigma)),
        "baseline_pulse": float(np.clip(rng.normal(PULSE_MEAN, PULSE_SD), *PULSE_RANGE)),
        "baseline_task_score": float(
            np.clip(rng.normal(TASK_SCORE_MEAN, TASK_SCORE_SD), *TASK_SCORE_RANGE)
        ),
        "latent_frustration": float(rng.normal(0, FRUSTRATION_SD)),
    }


def generate_employee(
    rng: np.random.Generator,
    cfg: GeneratorConfig,
    *,
    emp_id: str,
    department: str,
    role: str,
    hire_date: date,
    as_of: date,
    manager_id: str = "",
    contract_type: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """One employee row and its latent-trait row, both keyed by employee_id.

    `as_of` is the date the record describes (property start for initial staff, the hire
    date for replacement hires). A seasonal contract ends on the next configured MM-DD
    after `as_of`. `contract_type` forces "seasonal" / "permanent" (replacement hires keep
    the leaver's type); None draws it from seasonal_share_by_role. The draw is consumed
    either way so random streams stay aligned.
    """
    if contract_type not in (None, "seasonal", "permanent"):
        raise ValueError(f"contract_type must be seasonal, permanent or None, got {contract_type}")
    spec = cfg.roles[department][role]
    drawn_seasonal = rng.random() < cfg.staff.seasonal_share_by_role.get(role, 0.0)
    seasonal = drawn_seasonal if contract_type is None else contract_type == "seasonal"
    options = cfg.staff.seasonal_contract_end_options
    end_option = options[int(rng.integers(len(options)))]
    is_head = is_head_role(role)
    row: dict[str, object] = {
        "employee_id": emp_id,
        "department": department,
        "role": role,
        "is_department_head": is_head,
        "manager_id": "" if is_head else manager_id,
        "hire_date": hire_date,
        "contract_type": "seasonal" if seasonal else "permanent",
        "contract_end_date": next_month_day(as_of, end_option) if seasonal else None,
        "monthly_pay": draw_pay(rng, spec),
        "last_raise_date": draw_last_raise(rng, hire_date, as_of),
    }
    return row, {"employee_id": emp_id, **draw_latent(rng)}


def generate_initial_staff(
    cfg: GeneratorConfig, rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(employee, employee_latent) for everyone active on the property start date.

    Ids run department by department in config order, head first.
    """
    start = cfg.property.start
    rows, latent = [], []
    n = 0
    for dept, roles in cfg.roles.items():
        head = head_role(roles)
        head_id = employee_id(n + 1)
        ordered = [head] + [r for r in roles if r != head]
        for role in ordered:
            for _ in range(roles[role].count):
                n += 1
                tenure_days = round(draw_tenure_years(rng, cfg.staff) * DAYS_PER_YEAR)
                row, lat = generate_employee(
                    rng,
                    cfg,
                    emp_id=employee_id(n),
                    department=dept,
                    role=role,
                    hire_date=start - timedelta(days=tenure_days),
                    as_of=start,
                    manager_id=head_id,
                )
                rows.append(row)
                latent.append(lat)
    return pd.DataFrame(rows, columns=EMPLOYEE_COLUMNS), pd.DataFrame(latent)
