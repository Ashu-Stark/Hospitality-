"""Generate the SYNTHETIC daily calendar, weather and occupancy CSVs into data/.

Run from the repo root:  python run.py generate   (or python -m ml.generator.run_occupancy)
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.generator.calendar import build_calendar
from ml.generator.config import GeneratorConfig, load_config
from ml.generator.occupancy import OCCUPANCY_COLUMNS, simulate_occupancy
from ml.generator.rng import stream_rngs
from ml.generator.weather import simulate_weather

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def generate_daily(cfg: GeneratorConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (calendar, weather, merged occupancy) frames, seeded from cfg.seed.

    Each stage gets its own child Generator so changing one stage's draws
    does not shift the random streams of the others.
    """
    weather_rng, occupancy_rng = stream_rngs(cfg.seed, "weather", "occupancy")
    calendar = build_calendar(cfg)
    weather = simulate_weather(calendar, cfg, weather_rng)
    daily = simulate_occupancy(calendar, weather, cfg, occupancy_rng)
    return calendar, weather, daily


def write_outputs(
    calendar: pd.DataFrame, weather: pd.DataFrame, daily: pd.DataFrame, out_dir: Path
) -> list[Path]:
    """Write the three CSVs; occupancy_daily.csv holds date + occupancy columns only."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "event_calendar.csv": calendar,
        "weather_daily.csv": weather,
        "occupancy_daily.csv": daily[["date", *OCCUPANCY_COLUMNS]],
    }
    paths = []
    for name, frame in files.items():
        path = out_dir / name
        frame.to_csv(path, index=False, date_format="%Y-%m-%d")
        paths.append(path)
    return paths


def main(out_dir: Path = DATA_DIR, config_path: Path | None = None) -> list[Path]:
    cfg = load_config(config_path)
    paths = write_outputs(*generate_daily(cfg), out_dir)
    print(f"SYNTHETIC data generated with seed={cfg.seed}:")
    for p in paths:
        print(f"  {p}  ({sum(1 for _ in p.open(encoding='utf-8')) - 1} rows)")
    return paths


if __name__ == "__main__":
    main()
