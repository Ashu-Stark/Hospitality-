"""Smoke tests: the workload training scripts run end to end on a tiny synthetic subset."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.features.build_workload_features import WORKLOAD_LABEL, WORKLOAD_NUMERIC
from ml.features.split import time_split
from ml.models import evaluate_workload, train_workload_baseline, train_workload_model

DEPARTMENTS = ["kitchen", "security", "housekeeping"]


@pytest.fixture(scope="module")
def tiny_splits():
    """60 weeks x 3 departments; label depends on week_of_year, so a model can beat naive."""
    rng = np.random.default_rng(0)
    rows = []
    for ws in pd.date_range("2024-01-01", periods=60, freq="W-MON"):
        for dept in DEPARTMENTS:
            feats = {f: float(rng.normal()) for f in WORKLOAD_NUMERIC}
            feats["week_of_year"] = int(ws.isocalendar().week)
            feats["load_ratio"] = float(rng.uniform(0.5, 1.3))
            seasonal = 0.9 + 0.3 * np.sin(feats["week_of_year"] / 52 * 2 * np.pi)
            rows.append({"department": dept, "week_start": ws, **feats,
                         WORKLOAD_LABEL: seasonal + float(rng.normal(0, 0.02))})
    return time_split(pd.DataFrame(rows), embargo_weeks=1)


def test_workload_pipeline_runs(tiny_splits, tmp_path: Path) -> None:
    models, metrics, plots = tmp_path / "models", tmp_path / "metrics", tmp_path / "plots"
    naive = train_workload_baseline.main(tiny_splits, metrics)
    model = train_workload_model.main(tiny_splits, models, metrics, plots)
    code = evaluate_workload.main(tiny_splits, models)
    assert (models / "model.joblib").exists()
    assert (metrics / "workload_naive.json").exists()
    assert (metrics / "workload_model.json").exists()
    assert (plots / "workload_pred_vs_actual.png").exists()
    for m in (naive, model):
        assert {"mae", "rmse", "r2"} <= set(m["test"])
    assert model["test"]["mae"] < naive["test"]["mae"]
    assert code == 0


def test_not_better_flag_fires() -> None:
    table = pd.DataFrame({"model": ["naive", "workload_model"], "mae": [0.07, 0.08],
                          "rmse": [0.1, 0.1], "r2": [0.6, 0.5]})
    flags = evaluate_workload.flags_for(table)
    assert len(flags) == 1 and flags[0].startswith("NOT BETTER")
    assert evaluate_workload.flags_for(table.assign(mae=[0.08, 0.07])) == []
