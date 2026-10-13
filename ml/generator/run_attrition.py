"""Run the SYNTHETIC weekly attrition process and write its outputs into data/.

Reads Task 3 outputs (employee.csv, internal/employee_latent.csv, dept_week_load.csv) and
never modifies employee.csv or dept_week_load.csv. Writes:
  weekly_behaviour.csv, exits.csv, contract_renewals.csv, employee_v2.csv,
  dept_week_load_dynamic.csv, pay_changes.csv, attrition_calibration.json, and
  internal/employee_latent.csv (Task 3 rows + new hires).
The resignation-hazard intercept is first calibrated to target_annual_attrition (calibrate.py).
Re-running is idempotent: the latent file keeps only Task 3 employees' rows before appending.

Run from the repo root:  python -m ml.generator.run_attrition
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from ml.generator.attrition import AttritionResult
from ml.generator.calibrate import (
    CALIBRATION_FILE,
    DEFAULT_CALIBRATION_PATH,
    Calibration,
    calibrate_intercept,
    load_prior,
    save_calibration,
)
from ml.generator.config import GeneratorConfig, load_config

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
LATENT_PATH = Path("internal") / "employee_latent.csv"


def read_inputs(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(employee, latent restricted to employee.csv ids, dept_week_load) from Task 3 files."""
    for name in ("employee.csv", str(LATENT_PATH), "dept_week_load.csv"):
        if not (data_dir / name).exists():
            raise FileNotFoundError(f"{data_dir / name} missing; run python run.py generate")
    employee = pd.read_csv(data_dir / "employee.csv", keep_default_na=False)
    latent = pd.read_csv(data_dir / LATENT_PATH, float_precision="round_trip")
    latent = latent[latent["employee_id"].isin(employee["employee_id"])]
    return employee, latent, pd.read_csv(data_dir / "dept_week_load.csv")


def run(cfg: GeneratorConfig, data_dir: Path) -> Calibration:
    """Calibrate the hazard intercept, returning the simulation at the chosen intercept.

    Starts from the saved calibration in data_dir (or the repo's data/ folder) if any.
    """
    prior = load_prior(data_dir / CALIBRATION_FILE, DEFAULT_CALIBRATION_PATH)
    return calibrate_intercept(cfg, *read_inputs(data_dir), prior=prior)


def output_frames(result: AttritionResult) -> dict[Path, pd.DataFrame]:
    return {
        Path("weekly_behaviour.csv"): result.weekly_behaviour,
        Path("exits.csv"): result.exits,
        Path("contract_renewals.csv"): result.contract_renewals,
        Path("employee_v2.csv"): result.employees,
        Path("dept_week_load_dynamic.csv"): result.dept_week_load_dynamic,
        Path("pay_changes.csv"): result.pay_changes,
        LATENT_PATH: result.latent,
    }


def write_outputs(result: AttritionResult, out_dir: Path) -> list[Path]:
    paths = []
    for rel, frame in output_frames(result).items():
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, date_format="%Y-%m-%d")
        paths.append(path)
    return paths


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(data_dir: Path = DATA_DIR, config_path: Path | None = None) -> list[Path]:
    cfg = load_config(config_path)
    cal = run(cfg, data_dir)
    paths = write_outputs(cal.result, data_dir)
    paths.append(save_calibration(cal, data_dir / CALIBRATION_FILE))
    print(f"SYNTHETIC attrition data generated with seed={cfg.seed}; hazard intercept "
          f"{cal.intercept:.4f} calibrated to annual attrition {cal.achieved_rate:.3f} "
          f"(target {cal.target_rate}; {cal.iterations} simulations, {cal.mode} search):")
    for p in paths:
        rows = sum(1 for _ in p.open(encoding="utf-8")) - 1
        print(f"  {p}  ({rows} lines)  sha256 {file_hash(p)[:16]}")
    return paths


if __name__ == "__main__":
    main()
