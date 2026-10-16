"""Backtest monitoring: rolling error of the deployed models on the most recent actuals, against
their baselines. Warns when a model is worse than its baseline.

    cd ml; python run.py backtest-monitor                       # default hotel (ml/data)
    cd ml; python run.py backtest-monitor --hotel himsagar      # the served demo hotel
    cd ml; python run.py backtest-monitor --days 84 --strict    # exit 1 on any warning

Occupancy forecast: for each of the last `days` days d with an actual, the forecast made at
d - h (h = 1 and 7) vs the seasonal-naive baseline, error in rooms; rolling `window`-day MAE.
Workload: the last `weeks` weeks, next-week load_ratio vs naive (next week = this week).
Data are SYNTHETIC (the "recent actuals" are the generator's last days). Writes
ml/docs/metrics/backtest_monitor[_<hotel>].json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.forecast import api as fapi
from ml.forecast.core import BASELINE, build_frame
from ml.generator.config import load_config
from ml.models import workload_api

ML_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ML_ROOT / "docs" / "metrics"


def _data(hotel: str | None) -> tuple[Path, int]:
    if not hotel:
        return ML_ROOT / "data", load_config().property.rooms
    from ml.generator.hotel_variant import data_dir, load_hotel

    cfg, _ = load_hotel(hotel)
    return data_dir(hotel), cfg.property.rooms


def forecast_backtest(data_dir: Path, rooms: int, days: int, window: int,
                      horizons=(1, 7)) -> dict:
    cfg = load_config()
    _, daily = fapi._load(fapi.ARTIFACT_DIR, data_dir)
    end = daily.index.max()
    targets = pd.date_range(end - pd.Timedelta(days=days - 1), end)
    out = {}
    for h in horizons:
        frame = build_frame(daily, h, cfg.forecast, rooms)
        rows = []
        for d in targets:
            p = fapi.predict(d, d, as_of=d - pd.Timedelta(days=h), data_dir=data_dir,
                             rooms=rooms).days[0]
            actual = float(daily.loc[d, "occupancy_pct"])
            rows.append({"date": d, "model": abs(p.mean - actual) * rooms,
                         "baseline": abs(float(frame.loc[d, BASELINE]) - actual) * rooms,
                         "in_band": p.low <= actual <= p.high})
        r = pd.DataFrame(rows).set_index("date")
        roll = r[["model", "baseline"]].rolling(window).mean().dropna()
        worse = roll[roll["model"] > roll["baseline"]]
        out[f"{h}d"] = {
            "days": int(len(r)), "mae_rooms_model": round(float(r["model"].mean()), 3),
            "mae_rooms_baseline": round(float(r["baseline"].mean()), 3),
            "band_coverage": round(float(r["in_band"].mean()), 3),
            "latest_window_mae_model": round(float(roll["model"].iloc[-1]), 3),
            "latest_window_mae_baseline": round(float(roll["baseline"].iloc[-1]), 3),
            "windows": int(len(roll)), "windows_model_worse": int(len(worse)),
            "warning": bool(roll["model"].iloc[-1] > roll["baseline"].iloc[-1]),
        }
    return out


def workload_backtest(data_dir: Path, weeks: int) -> dict:
    load = pd.read_csv(data_dir / "dept_week_load_dynamic.csv")
    ws = sorted(pd.to_datetime(load["week_start"]).unique())
    errs = []
    for w in ws[-(weeks + 1):-1]:  # a next week must exist to score
        f = workload_api.predict_next_week(data_dir, w)
        nxt = load[pd.to_datetime(load["week_start"]) == w + pd.Timedelta(days=7)].set_index(
            "department")["load_ratio"]
        for d in f.departments:
            if d.department in nxt:
                actual = float(nxt[d.department])
                errs.append({"model": abs(d.next_week_load - actual),
                             "baseline": abs(d.this_week_load - actual)})
    e = pd.DataFrame(errs)
    m, b = float(e["model"].mean()), float(e["baseline"].mean())
    return {"weeks": weeks, "rows": int(len(e)), "mae_model": round(m, 4),
            "mae_baseline": round(b, 4), "warning": bool(m > b)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="rolling backtest vs baselines (SYNTHETIC data)")
    ap.add_argument("--hotel", default="", help="hotel variant key (default: ml/data)")
    ap.add_argument("--days", type=int, default=84)
    ap.add_argument("--window", type=int, default=28)
    ap.add_argument("--weeks", type=int, default=12)
    ap.add_argument("--strict", action="store_true", help="exit 1 when any warning fires")
    a = ap.parse_args(argv)
    data_dir, rooms = _data(a.hotel or None)
    report = {"synthetic": True, "hotel": a.hotel or "default", "rooms": rooms,
              "forecast": forecast_backtest(data_dir, rooms, a.days, a.window),
              "workload": workload_backtest(data_dir, a.weeks)}
    warnings = [f"forecast {k}: model MAE {v['latest_window_mae_model']} rooms > baseline "
                f"{v['latest_window_mae_baseline']} over the last {a.window} days"
                for k, v in report["forecast"].items() if v["warning"]]
    if report["workload"]["warning"]:
        w = report["workload"]
        warnings.append(f"workload: model MAE {w['mae_model']} > naive {w['mae_baseline']}")
    report["warnings"] = warnings
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"backtest_monitor{'_' + a.hotel if a.hotel else ''}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    for w in warnings:
        print("WARNING:", w)
    if not warnings:
        print("OK: every model at or below its baseline's error in the latest window")
    return 1 if (warnings and a.strict) else 0


if __name__ == "__main__":
    np.seterr(all="ignore")
    raise SystemExit(main())
