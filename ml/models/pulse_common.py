"""Shared preprocessing and regression metrics for the SYNTHETIC pulse models (Task 6)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import OneHotEncoder

from ml.features.build_pulse_features import PULSE_CATEGORICAL, PULSE_LABEL, PULSE_NUMERIC
from ml.models.common import METRICS_DIR, MODELS_DIR, PLOTS_DIR, save_metrics, seed

__all__ = ["METRICS_DIR", "MODELS_DIR", "PLOTS_DIR", "save_metrics", "seed"]


def make_pulse_preprocessor() -> ColumnTransformer:
    """Raw numerics (trees need no scaling) + one-hot categoricals."""
    return ColumnTransformer(
        [
            ("num", "passthrough", PULSE_NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
             PULSE_CATEGORICAL),
        ],
        verbose_feature_names_out=False,
    )


def pulse_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    return df[PULSE_NUMERIC + PULSE_CATEGORICAL], df[PULSE_LABEL].to_numpy()


def naive_prediction(df: pd.DataFrame) -> np.ndarray:
    """Next week's pulse = this week's pulse."""
    return df["pulse_score"].to_numpy()


def regression_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    return {
        "rows": int(len(y)),
        "mae": round(float(mean_absolute_error(y, pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y, pred))), 4),
        "r2": round(float(r2_score(y, pred)), 4),
    }


def print_regression(name: str, metrics: dict) -> None:
    for split in ("val", "test"):
        m = metrics[split]
        print(f"  {name} {split:4s}: MAE {m['mae']:.4f}  RMSE {m['rmse']:.4f}  R2 {m['r2']:.4f}"
              f"  (rows {m['rows']})")
