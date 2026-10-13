"""Write the T5 SYNTHETIC weekly signals, leave / pulse tables and the demo heroes into data/.

Reads earlier outputs (weekly_behaviour.csv, event_calendar.csv, dept_week_load_dynamic.csv,
employee_v2.csv, internal/employee_latent.csv) and never modifies them. Writes:
  weekly_signals.csv, leave_records.csv, pulse_responses.csv,
  demo/hero_employees.csv, demo/hero_weekly.csv, demo/hero_display_names.json
Run from the repo root:  python -m ml.generator.run_signals
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ml.generator.config import GeneratorConfig, load_config
from ml.generator.heroes import build_heroes
from ml.generator.rng import stream_rngs
from ml.generator.signals import compute_weekly_signals, leave_records, pulse_responses

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEMO_DIR = Path("demo")


@dataclass(frozen=True)
class SignalOutputs:
    signals: pd.DataFrame
    leave: pd.DataFrame
    pulse: pd.DataFrame
    hero_employees: pd.DataFrame
    hero_weekly: pd.DataFrame
    hero_names: dict[str, str]


def build_outputs(cfg: GeneratorConfig, data_dir: Path) -> SignalOutputs:
    behaviour = pd.read_csv(data_dir / "weekly_behaviour.csv")
    latent = pd.read_csv(data_dir / "internal" / "employee_latent.csv")
    calendar = pd.read_csv(data_dir / "event_calendar.csv")
    (rng,) = stream_rngs(cfg.seed, "signals")
    signals = compute_weekly_signals(behaviour, latent, calendar, cfg, rng)
    heroes = build_heroes(cfg, pd.read_csv(data_dir / "dept_week_load_dynamic.csv"), calendar,
                          pd.read_csv(data_dir / "employee_v2.csv", keep_default_na=False))
    return SignalOutputs(signals, leave_records(behaviour, signals), pulse_responses(behaviour),
                         *heroes)


def write_outputs(out: SignalOutputs, data_dir: Path) -> list[Path]:
    files = {
        Path("weekly_signals.csv"): out.signals,
        Path("leave_records.csv"): out.leave,
        Path("pulse_responses.csv"): out.pulse,
        DEMO_DIR / "hero_employees.csv": out.hero_employees,
        DEMO_DIR / "hero_weekly.csv": out.hero_weekly,
    }
    paths = []
    for rel, frame in files.items():
        path = data_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, date_format="%Y-%m-%d")
        paths.append(path)
    names = data_dir / DEMO_DIR / "hero_display_names.json"
    names.write_text(json.dumps(out.hero_names, indent=2) + "\n", encoding="utf-8")
    return paths + [names]


def main(data_dir: Path = DATA_DIR, config_path: Path | None = None) -> list[Path]:
    cfg = load_config(config_path)
    paths = write_outputs(build_outputs(cfg, data_dir), data_dir)
    print(f"SYNTHETIC weekly signals and demo heroes generated with seed={cfg.seed}:")
    for p in paths:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        print(f"  {p}  ({sum(1 for _ in p.open(encoding='utf-8')) - 1} lines)  sha256 {digest}")
    return paths


if __name__ == "__main__":
    main()
