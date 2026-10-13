"""Smoke tests: the pulse training scripts run end to end on a tiny synthetic subset."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.features.build_pulse_features import PULSE_LABEL, PULSE_NUMERIC
from ml.features.split import time_split
from ml.models import evaluate_pulse, train_pulse_baseline, train_pulse_model


@pytest.fixture(scope="module")
def tiny_splits():
    """40 weeks x 20 employees; label = 0.7 * pulse + noise, so a model can beat naive."""
    rng = np.random.default_rng(0)
    weeks = pd.date_range("2024-01-01", periods=40, freq="W-MON")
    rows = []
    for ws in weeks:
        for e in range(20):
            feats = {f: float(rng.normal()) for f in PULSE_NUMERIC}
            feats["pulse_score"] = float(rng.uniform(1, 5))
            rows.append({
                "employee_id": f"E{e:03d}", "week_start": ws,
                "department": ["kitchen", "security"][e % 2],
                "role": ["cook", "guard", "helper"][e % 3],
                "contract_type": ["permanent", "seasonal"][e % 2],
                **feats,
                PULSE_LABEL: 0.7 * feats["pulse_score"] + 1.1 + float(rng.normal(0, 0.1)),
            })
    return time_split(pd.DataFrame(rows), embargo_weeks=1)


def test_pulse_pipeline_runs(tiny_splits, tmp_path: Path) -> None:
    models, metrics, plots = tmp_path / "models", tmp_path / "metrics", tmp_path / "plots"
    naive = train_pulse_baseline.main(tiny_splits, metrics)
    model = train_pulse_model.main(tiny_splits, models, metrics, plots)
    code = evaluate_pulse.main(tiny_splits, models)
    assert (models / "model.joblib").exists()
    assert (metrics / "pulse_naive.json").exists() and (metrics / "pulse_model.json").exists()
    assert (plots / "pulse_pred_vs_actual.png").exists()
    for m in (naive, model):
        assert {"mae", "rmse", "r2"} <= set(m["test"])
    assert model["test"]["mae"] < naive["test"]["mae"]
    assert code == 0  # the model beats naive here, so no flag


def test_not_better_flag_fires() -> None:
    table = pd.DataFrame({"model": ["naive", "pulse_model"], "mae": [0.20, 0.25],
                          "rmse": [0.3, 0.3], "r2": [0.5, 0.4]})
    flags = evaluate_pulse.flags_for(table)
    assert len(flags) == 1 and flags[0].startswith("NOT BETTER")
    assert evaluate_pulse.flags_for(table.assign(mae=[0.25, 0.20])) == []
