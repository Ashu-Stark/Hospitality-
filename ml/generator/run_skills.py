"""Extend employee_skill.csv to the replacement hires (bug fix after T12b), SYNTHETIC data.

Reads employee.csv (original staff), employee_skill.csv, employee_v2.csv and exits.csv; keeps the
original staff's rows exactly as run_staff wrote them and appends rows for every replacement hire
(own random stream `replacement_skills`). Only employee_skill.csv is written. Idempotent: rows of
non-original employees are dropped and rebuilt on every run.
Run from the repo root:  python -m ml.generator.run_skills  (part of python run.py generate)
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from ml.generator.config import GeneratorConfig, load_config
from ml.generator.rng import stream_rngs
from ml.generator.skills import extend_skills_to_replacements

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def build(data_dir: Path = DATA_DIR, cfg: GeneratorConfig | None = None) -> pd.DataFrame:
    """cfg: a hotel variant's config (ml/generator/hotel_variant.py); default config.yaml."""
    cfg = cfg if cfg is not None else load_config()
    original = set(pd.read_csv(data_dir / "employee.csv")["employee_id"])
    skills = pd.read_csv(data_dir / "employee_skill.csv")
    initial = skills[skills["employee_id"].isin(original)].reset_index(drop=True)
    (rng,) = stream_rngs(cfg.seed, "replacement_skills")
    return extend_skills_to_replacements(
        pd.read_csv(data_dir / "employee_v2.csv", keep_default_na=False), initial,
        pd.read_csv(data_dir / "exits.csv"), cfg, rng)


def main(data_dir: Path = DATA_DIR) -> Path:
    out = build(data_dir)
    path = data_dir / "employee_skill.csv"
    out.to_csv(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    print(f"SYNTHETIC skills extended to replacement hires: {path} ({len(out)} rows, "
          f"{out['employee_id'].nunique()} employees)  sha256 {digest}")
    return path


if __name__ == "__main__":
    main()
