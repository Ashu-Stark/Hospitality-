"""XGBoost regressor (trained on the GPU) for next week's pulse_score (SYNTHETIC data).

Objective: L1 (absolute error), early stopping on validation L1. The comparison metric is MAE,
which an L1 objective targets directly (the conditional median). An L2 objective was tried
first: validation MAE 0.2461 vs L1's 0.2447, and on test it only tied naive (0.2456 vs 0.2453).
L1 was chosen on validation, not test (that comparison was made with the earlier LightGBM
model). Fixed seed. Trained and evaluated on the GPU (ml/gpu.py refuses to run without CUDA);
saved as a numpy TreeEnsemble for CPU inference. Small trees (8 leaves); the minimum leaf size
was chosen on the VALIDATION split only (ml/models/gpu_trees.py).
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
from ml.features.split import Splits, load_pulse_splits  # noqa: E402
from ml.generator.validate_occupancy import (  # noqa: E402
    AXIS,
    INK_2,
    SURFACE,
    style_axes,
)
from ml.models.common import MODEL_FILE, PULSE_ARTIFACT_DIR  # noqa: E402
from ml.models.gpu_trees import MIN_LEAF, fit_l1  # noqa: E402
from ml.models.pulse_common import (  # noqa: E402
    PLOTS_DIR,
    make_pulse_preprocessor,
    print_regression,
    pulse_xy,
    regression_metrics,
    save_metrics,
    seed,
)
from ml.xgb_trees import predict_gpu  # noqa: E402

NAME = "pulse_model"
TOP_N = 10


def train_pulse_model(splits: Splits, random_state: int) -> tuple[Pipeline, dict]:
    prep = make_pulse_preprocessor().set_output(transform="pandas")
    x_train, y_train = pulse_xy(splits.train)
    x_val, y_val = pulse_xy(splits.val)
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
        x, y = pulse_xy(part)
        metrics[name] = regression_metrics(y, predict_gpu(model, x))  # evaluated on the GPU
    metrics["feature_importance_gain"] = gain.round(2).to_dict()
    return model, metrics


def save_pred_vs_actual(y: np.ndarray, pred: np.ndarray, out_dir: Path = PLOTS_DIR) -> Path:
    """Hexbin density of predicted vs actual next-week pulse (test), with the y = x line."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6.5, 6), facecolor=SURFACE)
    hb = ax.hexbin(y, pred, gridsize=35, cmap="Blues", mincnt=1, extent=(1, 5, 1, 5))
    ax.plot([1, 5], [1, 5], color=AXIS, linestyle="--", linewidth=1.5)
    cbar = fig.colorbar(hb, ax=ax)
    cbar.set_label("employee-weeks", color=INK_2)
    style_axes(ax, "Pulse: predicted vs actual, test (SYNTHETIC data)", "Predicted next-week pulse")
    ax.set_xlabel("Actual next-week pulse (dashed line = perfect)", color=INK_2)
    ax.set_xlim(1, 5)
    ax.set_ylim(1, 5)
    ax.grid(axis="x", color="#e1e0d9", linewidth=0.8)
    fig.tight_layout()
    path = out_dir / "pulse_pred_vs_actual.png"
    fig.savefig(path, dpi=120, facecolor=SURFACE)
    plt.close(fig)
    return path


def main(splits: Splits | None = None, models_dir: Path = PULSE_ARTIFACT_DIR,
         metrics_dir: Path | None = None, plots_dir: Path = PLOTS_DIR) -> dict:
    splits = splits if splits is not None else load_pulse_splits()
    model, metrics = train_pulse_model(splits, seed())
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, models_dir / MODEL_FILE)
    path = save_metrics(metrics, NAME) if metrics_dir is None else save_metrics(
        metrics, NAME, metrics_dir)
    print(f"XGBoost pulse regressor on {metrics['train_device']} (SYNTHETIC data) -> "
          f"{models_dir / MODEL_FILE}, "
          f"early-stopped at {metrics['best_iteration']} trees")
    print_regression(NAME, metrics)
    print(f"  top {TOP_N} feature importances (gain):")
    for feat, gain in list(metrics["feature_importance_gain"].items())[:TOP_N]:
        print(f"    {feat:28s} {gain:12.1f}")
    print(f"  metrics saved: {path}")
    x_test, y_test = pulse_xy(splits.test)
    print(f"  plot saved: {save_pred_vs_actual(y_test, predict_gpu(model, x_test), plots_dir)}")
    return metrics


if __name__ == "__main__":
    main()
