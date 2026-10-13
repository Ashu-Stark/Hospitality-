from pathlib import Path

import pandas as pd
import pytest

from ml.generator import run_attrition, run_occupancy, run_staff

# Slow: calibration searches / full pipeline runs. Run with python run.py test --all.
pytestmark = pytest.mark.slow

OUTPUTS = [
    "weekly_behaviour.csv",
    "exits.csv",
    "contract_renewals.csv",
    "employee_v2.csv",
    "dept_week_load_dynamic.csv",
    "pay_changes.csv",
    "internal/employee_latent.csv",
    "attrition_calibration.json",
]


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data")
    run_occupancy.main(out_dir=d)
    run_staff.main(out_dir=d)
    return d


@pytest.fixture(scope="module")
def task3_bytes(data_dir: Path) -> dict[str, bytes]:
    names = ["employee.csv", "dept_week_load.csv", "internal/employee_latent.csv"]
    return {n: (data_dir / n).read_bytes() for n in names}


@pytest.fixture(scope="module")
def outputs(data_dir: Path, task3_bytes) -> list[Path]:
    return run_attrition.main(data_dir=data_dir)


def test_writes_all_outputs(data_dir: Path, outputs: list[Path]) -> None:
    assert [p.relative_to(data_dir).as_posix() for p in outputs] == OUTPUTS


def test_task3_files_untouched(data_dir: Path, task3_bytes, outputs) -> None:
    assert (data_dir / "employee.csv").read_bytes() == task3_bytes["employee.csv"]
    assert (data_dir / "dept_week_load.csv").read_bytes() == task3_bytes["dept_week_load.csv"]


def test_employee_v2_and_latent_extend_task3_rows(data_dir: Path, task3_bytes, outputs) -> None:
    v2 = (data_dir / "employee_v2.csv").read_bytes()
    assert v2.startswith(task3_bytes["employee.csv"])
    latent = (data_dir / "internal/employee_latent.csv").read_bytes()
    assert latent.startswith(task3_bytes["internal/employee_latent.csv"])
    assert len(pd.read_csv(data_dir / "employee_v2.csv")) == len(
        pd.read_csv(data_dir / "internal/employee_latent.csv")
    )


def test_rerun_is_identical_and_idempotent(data_dir: Path, outputs) -> None:
    first = {p.name: run_attrition.file_hash(p) for p in outputs}
    again = run_attrition.main(data_dir=data_dir)
    assert {p.name: run_attrition.file_hash(p) for p in again} == first


def test_behaviour_columns(data_dir: Path, outputs) -> None:
    beh = pd.read_csv(data_dir / "weekly_behaviour.csv", nrows=1)
    assert list(beh.columns) == [
        "employee_id", "week_start", "department", "role", "load_ratio",
        "overtime_hours", "pulse_score", "leave_days", "is_active",
    ]


def test_missing_inputs_raise(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_attrition.main(data_dir=tmp_path)


def test_calibration_record(data_dir: Path, outputs) -> None:
    import json

    from ml.generator.config import load_config

    cfg = load_config()
    rec = json.loads((data_dir / "attrition_calibration.json").read_text(encoding="utf-8"))
    assert rec["target_annual_attrition"] == cfg.target_annual_attrition
    assert abs(rec["achieved_annual_attrition"] - cfg.target_annual_attrition) <= 0.05
    lo, hi = cfg.attrition.calibration.intercept_low, cfg.attrition.calibration.intercept_high
    assert lo - cfg.attrition.calibration.refine_half_width <= rec["intercept"] <= hi

