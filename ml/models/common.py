"""Shared preprocessing, metrics and I/O for the SYNTHETIC attrition models."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.features.build_features import CATEGORICAL_FEATURES, LABEL, NUMERIC_FEATURES
from ml.generator.config import load_config

ML_ROOT = Path(__file__).resolve().parents[1]  # the ml/ project folder
MODELS_DIR = ML_ROOT / "artifacts"
MODEL_FILE = "model.joblib"
PULSE_ARTIFACT_DIR = MODELS_DIR / "pulse" / "v1"
WORKLOAD_ARTIFACT_DIR = MODELS_DIR / "workload" / "v1"
METRICS_DIR = ML_ROOT / "docs" / "metrics"
PLOTS_DIR = ML_ROOT / "docs" / "plots"
THRESHOLD = 0.5


def seed() -> int:
    return load_config().seed


def make_preprocessor(scale_numeric: bool) -> ColumnTransformer:
    """One-hot categoricals; numeric standardized (logreg) or passed through (trees)."""
    numeric = StandardScaler() if scale_numeric else "passthrough"
    return ColumnTransformer(
        [
            ("num", numeric, NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
             CATEGORICAL_FEATURES),
        ],
        verbose_feature_names_out=False,
    )


def xy(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    return df[NUMERIC_FEATURES + CATEGORICAL_FEATURES], df[LABEL].to_numpy()


def calibration_by_decile(y: np.ndarray, p: np.ndarray) -> list[dict[str, float]]:
    """Mean predicted probability vs actual exit rate per predicted-probability decile."""
    bins = pd.qcut(pd.Series(p).rank(method="first"), 10, labels=False)
    out = []
    for b, idx in pd.Series(range(len(p))).groupby(bins):
        out.append({
            "decile": int(b) + 1,
            "n": int(len(idx)),
            "mean_predicted": round(float(p[idx].mean()), 4),
            "actual_rate": round(float(y[idx].mean()), 4),
        })
    return out


def evaluate_split(y: np.ndarray, p: np.ndarray, threshold: float = THRESHOLD) -> dict:
    pred = (p >= threshold).astype(int)
    return {
        "rows": int(len(y)),
        "positives": int(y.sum()),
        "positive_rate": round(float(y.mean()), 4),
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "threshold": threshold,
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        "calibration_by_decile": calibration_by_decile(y, p),
    }


def save_metrics(metrics: dict, name: str, out_dir: Path = METRICS_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    return path


def print_metrics(name: str, metrics: dict) -> None:
    for split in ("val", "test"):
        m = metrics[split]
        print(f"  {name} {split:4s}: ROC-AUC {m['roc_auc']:.4f}  PR-AUC {m['pr_auc']:.4f}  "
              f"P/R/F1@{m['threshold']} {m['precision']:.3f}/{m['recall']:.3f}/{m['f1']:.3f}  "
              f"(positives {m['positives']}/{m['rows']}, base rate {m['positive_rate']:.2%})")
    print(f"  {name} test calibration by decile (mean predicted -> actual):")
    for d in metrics["test"]["calibration_by_decile"]:
        print(f"    decile {d['decile']:2d}: {d['mean_predicted']:.4f} -> {d['actual_rate']:.4f}"
              f"  (n={d['n']})")
