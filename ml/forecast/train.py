"""Train and evaluate the occupancy forecast (Task T6) on SYNTHETIC data.

For each horizon in config forecast.horizons_days: an XGBoost mean model plus two quantile
models (the 80% band), trained AND evaluated on the GPU (ml/gpu.py refuses to run without CUDA;
the saved model is a numpy TreeEnsemble for CPU inference), compared with the seasonal-naive
baseline on the 2025 test year. Where
the model's test MAPE is not lower than the baseline's, that horizon USES THE BASELINE.
Band (T12): split-conformal. A twin of the chosen forecaster, trained only on targets before
forecast.conformal_calibration_start, is scored on the calibration window up to train_end; the
(n + 1)-corrected quantiles of its residuals are added to the point forecast. The T6 quantile
models are still fitted, only to report their coverage beside it. Saves the bundle to
artifacts/occupancy_forecast/v1/, metrics, and an actual-vs-forecast plot.

Run from ml/:  python run.py train-forecast
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml import gpu  # noqa: E402
from ml.forecast.core import (  # noqa: E402
    ARTIFACT_DIR,
    BASELINE,
    TARGET,
    alert_flags,
    build_frame,
    daily_table,
    feature_names,
    mae,
    mape,
    split_frame,
)
from ml.generator.config import GeneratorConfig, load_config  # noqa: E402
from ml.generator.validate_occupancy import (  # noqa: E402
    BLUE,
    BLUE_LIGHT,
    INK_2,
    SURFACE,
    style_axes,
)
from ml.xgb_trees import TreeEnsemble  # noqa: E402

ML_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ML_ROOT / "data"
PLOT_PATH = ML_ROOT / "docs" / "plots" / "occupancy_forecast.png"
ORANGE = "#eb6834"
PLOT_HORIZON = 7

# Fixed model settings (not tuned): the earlier LightGBM settings mapped to XGBoost (leaf-wise,
# 15 leaves, min 20 rows per leaf, no L2 penalty, 0.8 row / column subsampling).
MEAN_PARAMS = dict(n_estimators=400, learning_rate=0.03, grow_policy="lossguide", max_leaves=15,
                   max_depth=0, min_child_weight=20, reg_lambda=0.0, subsample=0.8,
                   colsample_bytree=0.8, **gpu.XGB_DEVICE)
OBJECTIVES = {"regression": "reg:squarederror", "quantile": "reg:quantileerror"}


def load_daily(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    return daily_table(pd.read_csv(data_dir / "occupancy_daily.csv"),
                       pd.read_csv(data_dir / "event_calendar.csv"),
                       pd.read_csv(data_dir / "weather_daily.csv"))


def _fit(x: pd.DataFrame, y: pd.Series, seed: int, objective: str, alpha: float | None = None):
    """XGBoost on CUDA (refuses without a GPU); predict() on it also runs on the GPU."""
    import xgboost as xgb

    gpu.require_cuda()
    extra = {"quantile_alpha": alpha} if alpha is not None else {}
    model = xgb.XGBRegressor(objective=OBJECTIVES[objective], random_state=seed, **MEAN_PARAMS,
                             **extra).fit(x, y)
    gpu.assert_xgb_on_cuda(model)
    return model


def conformal_quantiles(residuals: np.ndarray, q_lo: float, q_hi: float) -> tuple[float, float]:
    """Split-conformal residual quantiles with the finite-sample (n + 1) correction."""
    r = np.sort(np.asarray(residuals, dtype=float))
    n = len(r)
    lo = max(np.floor((n + 1) * q_lo) / n, 0.0)
    hi = min(np.ceil((n + 1) * q_hi) / n, 1.0)
    return (float(np.quantile(r, lo, method="inverted_cdf")),
            float(np.quantile(r, hi, method="inverted_cdf")))


def calibration_residuals(train: pd.DataFrame, feats: list[str], cfg: GeneratorConfig,
                          use: str) -> np.ndarray:
    """Residuals on [conformal_calibration_start, train_end] of a twin trained BEFORE it."""
    cal_start = pd.Timestamp(cfg.forecast.conformal_calibration_start)
    early, cal = train[train.index < cal_start], train[train.index >= cal_start]
    if use == "baseline":
        return (cal[TARGET] - cal[BASELINE]).dropna().to_numpy()
    twin = _fit(early[feats], early[TARGET], cfg.seed, "regression")
    return (cal[TARGET] - np.clip(twin.predict(cal[feats]), 0, 1)).to_numpy()


def train_horizon(daily: pd.DataFrame, horizon: int, cfg: GeneratorConfig) -> dict:
    f = cfg.forecast
    frame = build_frame(daily, horizon, f, cfg.property.rooms)
    train, test = split_frame(frame, f)
    feats = feature_names(horizon, f)
    q_lo, q_hi = f.band_quantiles
    mean_model = _fit(train[feats], train[TARGET], cfg.seed, "regression")
    y = test[TARGET].to_numpy()
    pred = np.clip(mean_model.predict(test[feats]), 0, 1)
    base = test[BASELINE].to_numpy()
    model_mape, base_mape = mape(y, pred), mape(y, base)
    use = "model" if model_mape < base_mape else "baseline"
    chosen = pred if use == "model" else base
    resid = calibration_residuals(train, feats, cfg, use)
    r_lo, r_hi = conformal_quantiles(resid, q_lo, q_hi)
    lo, hi = np.clip(chosen + r_lo, 0, 1), np.clip(chosen + r_hi, 0, 1)
    # comparison only: the T6 quantile-regression band (not stored, not served)
    qlo = _fit(train[feats], train[TARGET], cfg.seed, "quantile", q_lo).predict(test[feats])
    qhi = _fit(train[feats], train[TARGET], cfg.seed, "quantile", q_hi).predict(test[feats])
    quantile_cover = np.mean((y >= np.minimum(qlo, pred)) & (y <= np.maximum(qhi, pred)))
    high, low = alert_flags(chosen, f)
    actual_high = y >= f.alert_high_occupancy
    metrics = {
        "horizon_days": horizon, "test_days": len(test), "train_days": len(train),
        "model_mape": round(model_mape, 4), "baseline_mape": round(base_mape, 4),
        "model_mae": round(mae(y, pred), 4), "baseline_mae": round(mae(y, base), 4),
        "used": use, "band_method": "split_conformal",
        "band_coverage": round(float(np.mean((y >= lo) & (y <= hi))), 4),
        "band_nominal": round(q_hi - q_lo, 2),
        "band_mean_width": round(float(np.mean(hi - lo)), 4),
        "conformal_calibration_days": int(len(resid)),
        "conformal_residual_quantiles": [round(r_lo, 4), round(r_hi, 4)],
        "quantile_regression_band_coverage": round(float(quantile_cover), 4),
        "high_alert_days": int(high.sum()), "low_alert_days": int(low.sum()),
        "high_alert_precision": round(float(actual_high[high].mean()), 3) if high.any() else None,
        "high_alert_recall": round(float(high[actual_high].mean()), 3) if actual_high.any()
        else None,
        "uses_booking_pace": "booking_pace_7d" in feats,
        "algorithm": "XGBoost (GPU), exported to a numpy TreeEnsemble",
        "train_device": gpu.require_cuda(), "eval_device": gpu.require_cuda(),
    }
    exported = TreeEnsemble.from_xgb(mean_model, train[feats])
    bundle = {"use": use, "features": feats, "mean": exported, "band": "split_conformal",
              "residual_quantiles": [r_lo, r_hi]}
    curve = pd.DataFrame({"actual": y, "forecast": chosen, "low": lo, "high": hi},
                         index=test.index)
    return {"metrics": metrics, "bundle": bundle, "curve": curve}


def save_plot(curve: pd.DataFrame, horizon: int, used: str, path: Path = PLOT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 4.5), facecolor=SURFACE)
    ax.fill_between(curve.index, curve["low"], curve["high"], color=BLUE_LIGHT, alpha=0.5,
                    linewidth=0, label="80% band (split-conformal)")
    ax.plot(curve.index, curve["actual"], color=ORANGE, linewidth=1.2, label="Actual")
    ax.plot(curve.index, curve["forecast"], color=BLUE, linewidth=2,
            label=f"Forecast ({used}, {horizon} days ahead)")
    ax.legend(frameon=False, labelcolor=INK_2, loc="lower right")
    style_axes(ax, f"Occupancy: actual vs {horizon}-day-ahead forecast, 2025 test "
                   "(SYNTHETIC data)", "Occupancy")
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=SURFACE)
    plt.close(fig)
    return path


def train_all(cfg: GeneratorConfig, data_dir: Path = DATA_DIR) -> dict[int, dict]:
    daily = load_daily(data_dir)
    return {h: train_horizon(daily, h, cfg) for h in cfg.forecast.horizons_days}


def save(results: dict[int, dict], out_dir: Path = ARTIFACT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.joblib"
    joblib.dump({h: r["bundle"] for h, r in results.items()}, model_path)
    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps({str(h): r["metrics"] for h, r in results.items()},
                                       indent=2) + "\n", encoding="utf-8")
    features_path = out_dir / "feature_list.json"
    features_path.write_text(json.dumps({str(h): r["bundle"]["features"]
                                         for h, r in results.items()}, indent=2) + "\n",
                             encoding="utf-8")
    return [model_path, metrics_path, features_path]


def main(data_dir: Path = DATA_DIR, out_dir: Path = ARTIFACT_DIR,
         plot_path: Path = PLOT_PATH) -> dict[int, dict]:
    cfg = load_config()
    results = train_all(cfg, data_dir)
    print("Occupancy forecast (SYNTHETIC data): train targets <= "
          f"{cfg.forecast.train_end}, test {cfg.forecast.test_start}..{cfg.forecast.test_end}")
    rows = pd.DataFrame([r["metrics"] for r in results.values()])
    cols = ["horizon_days", "model_mape", "baseline_mape", "model_mae", "baseline_mae", "used",
            "band_coverage", "quantile_regression_band_coverage", "band_mean_width",
            "high_alert_days", "high_alert_precision",
            "high_alert_recall", "uses_booking_pace"]
    print(rows[cols].to_string(index=False))
    for r in results.values():
        m = r["metrics"]
        if m["used"] == "baseline":
            print(f"  NOTE: {m['horizon_days']}-day horizon uses the seasonal-naive baseline "
                  f"(model MAPE {m['model_mape']:.4f} >= baseline {m['baseline_mape']:.4f}).")
    for p in save(results, out_dir):
        print(f"  saved {p}")
    plot_h = PLOT_HORIZON if PLOT_HORIZON in results else min(results)
    used = results[plot_h]["metrics"]["used"]
    print(f"  plot saved: {save_plot(results[plot_h]['curve'], plot_h, used, plot_path)}")
    return results


if __name__ == "__main__":
    main()
