from pathlib import Path

import pandas as pd

from ml.generator.run_occupancy import main

CSV_NAMES = ["event_calendar.csv", "occupancy_daily.csv", "weather_daily.csv"]


def test_main_writes_three_csvs(cfg, tmp_path: Path) -> None:
    paths = main(out_dir=tmp_path)
    assert sorted(p.name for p in paths) == CSV_NAMES
    occ = pd.read_csv(tmp_path / "occupancy_daily.csv", parse_dates=["date"])
    assert list(occ.columns) == [
        "date",
        "occupancy_pct",
        "rooms_sold",
        "adr",
        "room_revenue",
        "booking_pace_7d",
    ]
    for name in CSV_NAMES:
        assert len(pd.read_csv(tmp_path / name)) == (cfg.property.end - cfg.property.start).days + 1


def test_main_is_deterministic(tmp_path: Path) -> None:
    main(out_dir=tmp_path / "a")
    main(out_dir=tmp_path / "b")
    for name in CSV_NAMES:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
