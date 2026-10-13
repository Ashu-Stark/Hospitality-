"""LightGBM regressor for next week's pulse_score (SYNTHETIC data).

Objective: L1 (absolute error), early stopping on validation L1. The comparison metric is MAE,
which an L1 objective targets directly (the conditional median). An L2 objective was tried
first: validation MAE 0.2461 vs L1's 0.2447, and on test it only tied naive (0.2456 vs 0.2453).
L1 was chosen on validation, not test. Deterministic: fixed seed, single thread.
Same regularisation style as the Task 5 tree: small leaves and large minimum leaf size, so
the model learns population patterns rather than memorising individuals.
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

from ml.features.split import Splits, load_pulse_splits  # noqa: E402
from ml.generator.validate_occupancy import (  # noqa: E402
    AXIS,
    INK_2,
    SURFACE,
    style_axes,
)
from ml.models.common import MODEL_FILE, PULSE_ARTIFACT_DIR  # noqa: E402
from ml.models.pulse_common import (  # noqa: E402
    PLOTS_DIR,
    make_pulse_preprocessor,
    print_regression,
    pulse_xy,
    regression_metrics,
    save_metrics,
    seed,
)

NAME = "pulse_model"
EARLY_STOPPING_ROUNDS = 50
TOP_N = 10


def train_pulse_model(splits: Splits, random_state: int) -> tuple[Pipeline, dict]:
    prep = make_pulse_preprocessor().set_output(transform="pandas")
    x_train, y_train = pulse_xy(splits.train)
    x_val, y_val = pulse_xy(splits.val)
    xt_train = prep.fit_transform(x_train)
    xt_val = prep.transform(x_val)
    reg = lgb.LGBMRegressor(
        objective="regression_l1",
        n_estimators=3000,
        learning_rate=0.03,
        num_leaves=8,
        min_child_samples=100,
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
        x, y = pulse_xy(part)
        metrics[name] = regression_metrics(y, model.predict(x))
    metrics["feature_importance_gain"] = feature_importance(model).round(2).to_dict()
    return model, metrics


def feature_importance(model: Pipeline) -> pd.Series:
    reg = model.named_steps["reg"]
    names = model.named_steps["prep"].get_feature_names_out()
    gain = reg.booster_.feature_importance(importance_type="gain")
    return pd.Series(gain, index=names).sort_values(ascending=False)


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
    print(f"LightGBM pulse regressor (SYNTHETIC data) -> {models_dir / MODEL_FILE}, "
          f"early-stopped at {metrics['best_iteration']} trees")
    print_regression(NAME, metrics)
    print(f"  top {TOP_N} feature importances (gain):")
    for feat, gain in list(metrics["feature_importance_gain"].items())[:TOP_N]:
        print(f"    {feat:28s} {gain:12.1f}")
    print(f"  metrics saved: {path}")
    x_test, y_test = pulse_xy(splits.test)
    print(f"  plot saved: {save_pred_vs_actual(y_test, model.predict(x_test), plots_dir)}")
    return metrics


if __name__ == "__main__":
    main()
