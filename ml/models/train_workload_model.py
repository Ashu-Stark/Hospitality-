"""XGBoost regressor (trained on the GPU) for next week's department load_ratio (SYNTHETIC data).

Same pattern as the Task 6 pulse model: L1 objective (the comparison metric is MAE), early
stopping on validation L1, fixed seed. Trained and evaluated on the GPU (ml/gpu.py refuses to
run without CUDA); saved as a numpy TreeEnsemble for CPU inference. The minimum leaf size was
chosen on the VALIDATION split only (ml/models/gpu_trees.py), never on test.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402

from ml import gpu  # noqa: E402
from ml.features.split import Splits, load_workload_splits  # noqa: E402
from ml.generator.validate_occupancy import AXIS, BLUE, INK_2, SURFACE, style_axes  # noqa: E402
from ml.models.common import MODEL_FILE, WORKLOAD_ARTIFACT_DIR  # noqa: E402
from ml.models.gpu_trees import MIN_LEAF, fit_l1  # noqa: E402
from ml.models.workload_common import (  # noqa: E402
    PLOTS_DIR,
    make_workload_preprocessor,
    print_regression,
    regression_metrics,
    save_metrics,
    seed,
    workload_xy,
)
from ml.xgb_trees import predict_gpu  # noqa: E402

NAME = "workload_model"
TOP_N = 10


def train_workload_model(splits: Splits, random_state: int) -> tuple[Pipeline, dict]:
    prep = make_workload_preprocessor().set_output(transform="pandas")
    x_train, y_train = workload_xy(splits.train)
    x_val, y_val = workload_xy(splits.val)
    xt_train = prep.fit_transform(x_train)
    xt_val = prep.transform(x_val)
    _reg, ens, gain = fit_l1(xt_train, y_train, xt_val, y_val, random_state, min_leaf=MIN_LEAF)
    model = Pipeline([("prep", prep), ("reg", ens)])
    device = gpu.require_cuda()
    metrics: dict = {"model": NAME, "seed": random_state,
                     "best_iteration": int(_reg.best_iteration),
                     "trees": ens.n_trees, "algorithm": "XGBoost reg:absoluteerror (GPU)",
                     "train_device": device, "eval_device": device}
    for name, part in (("val", splits.val), ("test", splits.test)):
        x, y = workload_xy(part)
        metrics[name] = regression_metrics(y, predict_gpu(model, x))  # evaluated on the GPU
    metrics["feature_importance_gain"] = gain.round(2).to_dict()
    return model, metrics


def save_pred_vs_actual(y: np.ndarray, pred: np.ndarray, out_dir: Path = PLOTS_DIR) -> Path:
    """Scatter of predicted vs actual next-week load_ratio on test, with the y = x line."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lo = float(min(y.min(), pred.min())) - 0.05
    hi = float(max(y.max(), pred.max())) + 0.05
    fig, ax = plt.subplots(figsize=(6.5, 6), facecolor=SURFACE)
    ax.scatter(y, pred, s=14, color=BLUE, alpha=0.55, edgecolors="none")
    ax.plot([lo, hi], [lo, hi], color=AXIS, linestyle="--", linewidth=1.5)
    style_axes(ax, "Workload: predicted vs actual, test (SYNTHETIC data)",
               "Predicted next-week load_ratio")
    ax.set_xlabel("Actual next-week load_ratio (dashed line = perfect)", color=INK_2)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.grid(axis="x", color="#e1e0d9", linewidth=0.8)
    fig.tight_layout()
    path = out_dir / "workload_pred_vs_actual.png"
    fig.savefig(path, dpi=120, facecolor=SURFACE)
    plt.close(fig)
    return path


def main(splits: Splits | None = None, models_dir: Path = WORKLOAD_ARTIFACT_DIR,
         metrics_dir: Path | None = None, plots_dir: Path = PLOTS_DIR) -> dict:
    splits = splits if splits is not None else load_workload_splits()
    model, metrics = train_workload_model(splits, seed())
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, models_dir / MODEL_FILE)
    path = save_metrics(metrics, NAME) if metrics_dir is None else save_metrics(
        metrics, NAME, metrics_dir)
    print(f"XGBoost workload regressor on {metrics['train_device']} (SYNTHETIC data) -> "
          f"{models_dir / MODEL_FILE}, "
          f"early-stopped at {metrics['best_iteration']} trees")
    print_regression(NAME, metrics)
    print(f"  top {TOP_N} feature importances (gain):")
    for feat, gain in list(metrics["feature_importance_gain"].items())[:TOP_N]:
        print(f"    {feat:28s} {gain:10.2f}")
    print(f"  metrics saved: {path}")
    x_test, y_test = workload_xy(splits.test)
    print(f"  plot saved: {save_pred_vs_actual(y_test, predict_gpu(model, x_test), plots_dir)}")
    return metrics


if __name__ == "__main__":
    main()
