"""LightGBM regressor for next week's department load_ratio (SYNTHETIC data).

Same pattern as the Task 6 pulse model: L1 objective (the comparison metric is MAE), early
stopping on validation L1, fixed seed, single thread. Smaller minimum leaf size than Task 6
because there are only ~1,200 training rows (6 departments x ~200 weeks). Hyperparameters were
set before seeing any results, not tuned.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402

from ml.features.split import Splits, load_workload_splits  # noqa: E402
from ml.generator.validate_occupancy import AXIS, BLUE, INK_2, SURFACE, style_axes  # noqa: E402
from ml.models.common import MODEL_FILE, WORKLOAD_ARTIFACT_DIR  # noqa: E402
from ml.models.workload_common import (  # noqa: E402
    PLOTS_DIR,
    make_workload_preprocessor,
    print_regression,
    regression_metrics,
    save_metrics,
    seed,
    workload_xy,
)

NAME = "workload_model"
EARLY_STOPPING_ROUNDS = 50
TOP_N = 10


def train_workload_model(splits: Splits, random_state: int) -> tuple[Pipeline, dict]:
    prep = make_workload_preprocessor().set_output(transform="pandas")
    x_train, y_train = workload_xy(splits.train)
    x_val, y_val = workload_xy(splits.val)
    xt_train = prep.fit_transform(x_train)
    xt_val = prep.transform(x_val)
    reg = lgb.LGBMRegressor(
        objective="regression_l1",
        n_estimators=3000,
        learning_rate=0.03,
        num_leaves=8,
        min_child_samples=30,
        reg_lambda=5.0,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        random_state=random_state,
        n_jobs=1,
        deterministic=True,
        force_row_wise=True,
        verbose=-1,
    )
    reg.fit(
        xt_train, y_train,
        eval_X=(xt_val,),
        eval_y=(y_val,),
        eval_metric="l1",
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    model = Pipeline([("prep", prep), ("reg", reg)])
    metrics: dict = {"model": NAME, "seed": random_state, "best_iteration": reg.best_iteration_}
    for name, part in (("val", splits.val), ("test", splits.test)):
        x, y = workload_xy(part)
        metrics[name] = regression_metrics(y, model.predict(x))
    metrics["feature_importance_gain"] = feature_importance(model).round(2).to_dict()
    return model, metrics


def feature_importance(model: Pipeline) -> pd.Series:
    reg = model.named_steps["reg"]
    names = model.named_steps["prep"].get_feature_names_out()
    gain = reg.booster_.feature_importance(importance_type="gain")
    return pd.Series(gain, index=names).sort_values(ascending=False)


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
    print(f"LightGBM workload regressor (SYNTHETIC data) -> {models_dir / MODEL_FILE}, "
          f"early-stopped at {metrics['best_iteration']} trees")
    print_regression(NAME, metrics)
    print(f"  top {TOP_N} feature importances (gain):")
    for feat, gain in list(metrics["feature_importance_gain"].items())[:TOP_N]:
        print(f"    {feat:28s} {gain:10.2f}")
    print(f"  metrics saved: {path}")
    x_test, y_test = workload_xy(splits.test)
    print(f"  plot saved: {save_pred_vs_actual(y_test, model.predict(x_test), plots_dir)}")
    return metrics


if __name__ == "__main__":
    main()
