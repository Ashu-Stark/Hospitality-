from dataclasses import replace
from pathlib import Path

import pandas as pd

from ml.generator.validate_staff import (
    forbidden_columns,
    frames_hash,
    load_summary,
    save_load_plot,
    staff_checks,
    workload_checks,
)


def _failed(checks) -> list[str]:
    return [c.name for c in checks if not c.passed]


def test_staff_checks_pass_on_default_data(cfg, staff_frames) -> None:
    assert _failed(staff_checks(staff_frames, cfg)) == []


def test_latent_column_in_employee_fails(cfg, staff_frames) -> None:
    emp = staff_frames.employee.assign(baseline_pulse=3.0)
    failed = _failed(staff_checks(replace(staff_frames, employee=emp), cfg))
    assert "employee.csv has no latent columns" in failed


def test_personal_column_in_employee_fails(cfg, staff_frames) -> None:
    emp = staff_frames.employee.assign(gender="x")
    failed = _failed(staff_checks(replace(staff_frames, employee=emp), cfg))
    assert "employee.csv has no personal/protected columns" in failed


def test_wrong_manager_fails(cfg, staff_frames) -> None:
    emp = staff_frames.employee.copy()
    emp.loc[emp["employee_id"] == "E002", "manager_id"] = "E017"  # another dept's head
    failed = _failed(staff_checks(replace(staff_frames, employee=emp), cfg))
    assert "non-heads managed by own dept head" in failed


def test_forbidden_columns_tokens() -> None:
    cols = ["employee_id", "department", "first_name", "Age", "family_status", "manager_id"]
    assert forbidden_columns(cols) == ["first_name", "Age", "family_status"]


def _load(peak: float, feb: float, other: float) -> pd.DataFrame:
    weeks = pd.date_range("2024-01-01", "2024-12-23", freq="W-MON")
    month = weeks.month
    ratio = [peak if m in (5, 6) else feb if m == 2 else other for m in month]
    return pd.DataFrame({"week_start": weeks, "department": "x", "load_ratio": ratio})


def test_workload_checks_pass_and_fail() -> None:
    assert _failed(workload_checks(_load(1.2, 0.6, 0.9))) == []
    assert len(_failed(workload_checks(_load(0.4, 0.9, 0.3)))) == 3


def test_load_summary() -> None:
    s = load_summary(_load(1.2, 0.6, 0.9))
    assert (s["median"], s["peak_mean"], s["feb_mean"], s["max"]) == (0.9, 1.2, 0.6, 1.2)


def test_frames_hash_stable_and_sensitive(staff_frames) -> None:
    assert frames_hash(staff_frames) == frames_hash(replace(staff_frames))
    emp = staff_frames.employee.assign(monthly_pay=staff_frames.employee["monthly_pay"] + 1)
    assert frames_hash(staff_frames) != frames_hash(replace(staff_frames, employee=emp))


def test_save_load_plot(staff_frames, tmp_path: Path) -> None:
    path = save_load_plot(staff_frames.dept_week_load, tmp_path)
    assert path.exists() and path.stat().st_size > 0
