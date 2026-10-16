"""Write the training reference (reference_stats.json) next to each SYNTHETIC v1 model, for the
guardrail drift checks (ml/guardrails.py). Recomputes feature statistics from the training
window only; the models themselves are NOT retrained or changed.

    cd ml; python run.py guard-reference

trained_on = the date of the last git commit that changed the model file (2026-10-13 for all
four v1 models at the time of writing): the artifacts carry no training timestamp of their own.
The cancellation model (real_v1) writes its own reference when it is trained.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pandas as pd

from ml import guardrails as G
from ml.attrition.features import MODEL_FEATURES, load_attrition_features
from ml.features.build_workload_features import (
    WORKLOAD_FEATURES,
    build_workload_features,
    load_inputs,
)
from ml.forecast.core import build_frame, daily_table, feature_names, split_frame
from ml.generator.config import load_config

ML_ROOT = Path(__file__).resolve().parents[1]
ART = ML_ROOT / "artifacts"
DATA = ML_ROOT / "data"
# Training windows (as documented in the ml model notes): attrition's deployed model trains on rows
# whose 90-day label window ends before its 2029 validation year; workload Task 7 train weeks.
ATTRITION_TRAIN_END = "2028-10-02"
WORKLOAD_TRAIN = ("2023-01-30", "2026-12-07")


def committed_on(path: Path) -> str:
    """Date of the last git commit that changed `path` (today if git is unavailable)."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", str(path)],
                             capture_output=True, text=True, cwd=ML_ROOT, timeout=30)
        return out.stdout.strip() or date.today().isoformat()
    except (OSError, subprocess.SubprocessError):
        return date.today().isoformat()


def forecast_reference() -> dict:
    cfg = load_config()
    daily = daily_table(pd.read_csv(DATA / "occupancy_daily.csv"),
                        pd.read_csv(DATA / "event_calendar.csv"),
                        pd.read_csv(DATA / "weather_daily.csv"))
    train, _ = split_frame(build_frame(daily, 1, cfg.forecast, cfg.property.rooms), cfg.forecast)
    d = ART / "occupancy_forecast" / "v1"
    return G.build_reference(train, feature_names(1, cfg.forecast), model="occupancy_forecast/v1",
                             trained_on=committed_on(d / "model.joblib"),
                             training_window=f"targets ..{cfg.forecast.train_end} (SYNTHETIC)",
                             extra={"synthetic": True, "trained_on_source": "last git commit"})


def attrition_reference() -> dict:
    f = load_attrition_features(DATA)
    train = f[pd.to_datetime(f["week_start"]) < pd.Timestamp(ATTRITION_TRAIN_END)]
    d = ART / "attrition" / "v1"
    return G.build_reference(train, MODEL_FEATURES, model="attrition/v1",
                             trained_on=committed_on(d / "model.joblib"),
                             training_window=f"weeks ..{ATTRITION_TRAIN_END} (SYNTHETIC)",
                             extra={"synthetic": True, "trained_on_source": "last git commit"})


def workload_reference() -> dict:
    f = build_workload_features(*load_inputs(DATA))
    w = pd.to_datetime(f["week_start"])
    train = f[w.between(*map(pd.Timestamp, WORKLOAD_TRAIN))]
    d = ART / "workload" / "v1"
    return G.build_reference(train, WORKLOAD_FEATURES, model="workload/v1",
                             trained_on=committed_on(d / "model.joblib"),
                             training_window=f"weeks {WORKLOAD_TRAIN[0]}..{WORKLOAD_TRAIN[1]} "
                                             "(SYNTHETIC)",
                             extra={"synthetic": True, "trained_on_source": "last git commit"})


def main() -> int:
    for name, fn in (("occupancy_forecast", forecast_reference), ("attrition", attrition_reference),
                     ("workload", workload_reference)):
        ref = fn()
        path = G.save_reference(ref, ART / name / "v1")
        print(f"{path}: {ref['rows']} training rows, {len(ref['features'])} features, "
              f"trained_on {ref['trained_on']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
