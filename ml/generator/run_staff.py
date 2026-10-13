"""Generate the SYNTHETIC staff, skills and weekly workload CSVs into data/.

Needs data/occupancy_daily.csv first (python run.py generate runs both in order).
Run from the repo root:  python -m ml.generator.run_staff
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ml.generator.config import GeneratorConfig, load_config
from ml.generator.rng import stream_rngs
from ml.generator.skills import generate_employee_skills
from ml.generator.staff import generate_initial_staff
from ml.generator.workload import build_dept_week_load

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True)
class StaffFrames:
    employee: pd.DataFrame
    employee_latent: pd.DataFrame
    employee_skill: pd.DataFrame
    dept_week_load: pd.DataFrame


def generate_staff(cfg: GeneratorConfig, occupancy_daily: pd.DataFrame) -> StaffFrames:
    staff_rng, skills_rng = stream_rngs(cfg.seed, "staff", "skills")
    employee, latent = generate_initial_staff(cfg, staff_rng)
    return StaffFrames(
        employee=employee,
        employee_latent=latent,
        employee_skill=generate_employee_skills(employee, cfg, skills_rng),
        dept_week_load=build_dept_week_load(occupancy_daily, employee, cfg),
    )


def write_outputs(frames: StaffFrames, out_dir: Path) -> list[Path]:
    files = {
        out_dir / "employee.csv": frames.employee,
        out_dir / "employee_skill.csv": frames.employee_skill,
        out_dir / "dept_week_load.csv": frames.dept_week_load,
        out_dir / "internal" / "employee_latent.csv": frames.employee_latent,
    }
    for path, frame in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, date_format="%Y-%m-%d")
    return list(files)


def files_hash(paths: list[Path]) -> str:
    """SHA-256 over the bytes of all files, in the order given."""
    h = hashlib.sha256()
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()


def main(out_dir: Path = DATA_DIR, config_path: Path | None = None) -> list[Path]:
    cfg = load_config(config_path)
    occupancy_csv = out_dir / "occupancy_daily.csv"
    if not occupancy_csv.exists():
        raise FileNotFoundError(f"{occupancy_csv} missing; run python run.py generate")
    paths = write_outputs(generate_staff(cfg, pd.read_csv(occupancy_csv)), out_dir)
    print(f"SYNTHETIC staff data generated with seed={cfg.seed}:")
    for p in paths:
        print(f"  {p}  ({sum(1 for _ in p.open(encoding='utf-8')) - 1} rows)")
    print(f"  sha256 of staff files: {files_hash(paths)[:16]}")
    return paths


if __name__ == "__main__":
    main()
