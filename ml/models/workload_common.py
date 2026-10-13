"""Shared preprocessing for the SYNTHETIC workload (next-week load_ratio) models (Task 7).

Regression metrics and printing are reused from the pulse models (pulse_common).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder

from ml.features.build_workload_features import (
    WORKLOAD_CATEGORICAL,
    WORKLOAD_LABEL,
    WORKLOAD_NUMERIC,
)
from ml.models.pulse_common import (
    METRICS_DIR,
    MODELS_DIR,
    PLOTS_DIR,
    print_regression,
    regression_metrics,
    save_metrics,
    seed,
)

__all__ = [
    "METRICS_DIR", "MODELS_DIR", "PLOTS_DIR", "print_regression", "regression_metrics",
    "save_metrics", "seed",
]


def make_workload_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        [
            ("num", "passthrough", WORKLOAD_NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
             WORKLOAD_CATEGORICAL),
        ],
        verbose_feature_names_out=False,
    )


def workload_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    return df[WORKLOAD_NUMERIC + WORKLOAD_CATEGORICAL], df[WORKLOAD_LABEL].to_numpy()


def naive_workload(df: pd.DataFrame) -> np.ndarray:
    """Next week's load_ratio = this week's load_ratio."""
    return df["load_ratio"].to_numpy()
