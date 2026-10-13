from pathlib import Path

import pandas as pd
import pytest

from ml.generator import run_occupancy, run_staff
from ml.generator.staff import LATENT_COLUMNS


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data")
    run_occupancy.main(out_dir=d)
    return d


def test_writes_four_files(out_dir: Path) -> None:
    paths = run_staff.main(out_dir=out_dir)
    rel = sorted(p.relative_to(out_dir).as_posix() for p in paths)
    assert rel == [
        "dept_week_load.csv",
        "employee.csv",
        "employee_skill.csv",
        "internal/employee_latent.csv",
    ]


def test_employee_csv_has_no_latent_columns(out_dir: Path) -> None:
    run_staff.main(out_dir=out_dir)
    header = pd.read_csv(out_dir / "employee.csv", nrows=0).columns
    assert not set(LATENT_COLUMNS) & set(header)
    latent = pd.read_csv(out_dir / "internal" / "employee_latent.csv")
    assert set(LATENT_COLUMNS) <= set(latent.columns)


def test_rerun_is_byte_identical(out_dir: Path) -> None:
    first = run_staff.files_hash(run_staff.main(out_dir=out_dir))
    second = run_staff.files_hash(run_staff.main(out_dir=out_dir))
    assert first == second


def test_missing_occupancy_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_staff.main(out_dir=tmp_path)
