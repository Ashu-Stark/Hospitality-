"""Checks for the replacement-hire skills (bug fix after T12b), SYNTHETIC data.

Run from ml/:  python run.py validate
(or from the repo root: python -m ml.generator.validate_skills)
Exits 1 if any check fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from ml.generator.config import MAX_SKILLS_PER_EMPLOYEE, GeneratorConfig, load_config
from ml.generator.run_skills import DATA_DIR, build
from ml.generator.skills import active_coverage
from ml.generator.validate_occupancy import Check, frame_hash, print_table


def skill_checks(employees: pd.DataFrame, skills: pd.DataFrame, original: pd.DataFrame,
                 exits: pd.DataFrame, cfg: GeneratorConfig, last_week: pd.Timestamp,
                 rerun_hash: str) -> list[Check]:
    counts = skills.groupby("employee_id").size()
    n = employees["employee_id"].map(counts).fillna(0).astype(int)
    heads = employees["is_department_head"].astype(str).str.lower() == "true"
    dept_of = employees.set_index("employee_id")["department"]
    off_dept = sum(r.skill not in cfg.skills[dept_of[r.employee_id]] for r in skills.itertuples())
    cov = active_coverage(employees, skills, exits, cfg, last_week)
    short = cov[cov["skills_below_minimum"] != ""]
    fo = int(cov.loc[cov["department"] == "front_office", "fo_system_holders"].iloc[0])
    prefix = skills.iloc[:len(original)].reset_index(drop=True)
    return [
        Check(f"every employee (incl. replacement hires) holds 1-{MAX_SKILLS_PER_EMPLOYEE} skills",
              bool(n.between(1, MAX_SKILLS_PER_EMPLOYEE).all()),
              f"{int((n > 0).sum())} of {len(n)} employees"),
        Check("heads hold >= 2 skills", bool((n[heads] >= 2).all()), f"{int(heads.sum())} heads"),
        Check("skills only from the employee's department", off_dept == 0, f"{off_dept} off"),
        Check("original staff rows unchanged", prefix.equals(original.reset_index(drop=True)),
              f"{len(original)} rows"),
        Check(f"coverage holds among active staff in the last week ({last_week.date()})",
              short.empty, "ok" if short.empty else short.to_dict("records")),
        Check("front_office has a fo_system holder in the last week", fo >= 1, f"{fo} holders"),
        Check("same seed -> identical hash (skills)", frame_hash(skills) == rerun_hash, "ok"),
    ]


def main(data_dir: Path = DATA_DIR) -> int:
    cfg = load_config()
    employees = pd.read_csv(data_dir / "employee_v2.csv", keep_default_na=False)
    original_ids = set(pd.read_csv(data_dir / "employee.csv")["employee_id"])
    skills = pd.read_csv(data_dir / "employee_skill.csv")
    original = skills[skills["employee_id"].isin(original_ids)]
    exits = pd.read_csv(data_dir / "exits.csv")
    last_week = pd.Timestamp(pd.read_csv(data_dir / "weekly_behaviour.csv")["week_start"].max())
    checks = skill_checks(employees, skills, original, exits, cfg, last_week,
                          frame_hash(build(data_dir)))
    print("Validation of SYNTHETIC skills for all employees (incl. replacement hires)\n")
    print_table(checks)
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
