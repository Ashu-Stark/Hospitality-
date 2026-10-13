"""Train and evaluate the attrition model (Task T7) on SYNTHETIC data.

Two separate evaluations:
  resignation   permanent staff, label = resignation in the next 90 days
  contract_end  seasonal staff, label = seasonal contract-end exit in the next 90 days
Expanding-window backtest per test year Y (config attrition_model.test_years):
  train = rows whose 90-day label window ends on or before 1 Jan of Y-1 (90-day gap)
  val   = rows of year Y-1 whose window ends on or before 1 Jan of Y: Platt calibration,
          the F1 threshold and the winner choice (pooled validation PR-AUC)
  test  = rows of year Y, untouched until the final metrics
The test metrics pool the calibrated test predictions of all folds. The DEPLOYED model repeats
the protocol with the last data year as validation (train window ends <= 1 Jan of that year).

Scorers: rules baseline, logistic regression, LightGBM (+ for contract_end, the contract-date
rule: fewer days to the contract end = higher risk). LightGBM is always kept for SHAP (T8) even
when it does not win. NOTE: logistic can win because the generator's planted hazard IS a
logistic function of these drivers; that is a property of the synthetic data, not evidence that
logistic regression is better on real hotel data.

Heroes (data/demo/) are never read here. Run from ml/:  python run.py train
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.attrition.bands import band_metrics, rule_band_metrics  # noqa: E402
from ml.attrition.features import (  # noqa: E402
    ARTIFACT_DIR,
    DATA_DIR,
    MODEL_FEATURES,
    SEGMENTS,
    load_attrition_features,
    segment_rows,
)
from ml.attrition.models import (  # noqa: E402
    CONTRACT_RULE,
    LIGHTGBM,
    LOGISTIC,
    RULES,
    SCORERS,
    FoldModel,
    PlattCalibrator,
    best_f1_threshold,
    calibration_table,
    classification_metrics,
    fit_scorers,
    training_means,
)
from ml.features.build_features import HORIZON_DAYS  # noqa: E402
from ml.generator.config import (  # noqa: E402
    AttritionModelConfig,
    GeneratorConfig,
    load_config,
)
from ml.generator.validate_occupancy import BLUE, INK_2, SURFACE, style_axes  # noqa: E402

ML_ROOT = Path(__file__).resolve().parents[1]
PLOT_PATH = ML_ROOT / "docs" / "plots" / "attrition_calibration.png"
EXPLAIN_MODEL = LIGHTGBM
LINE_COLORS = {RULES: "#eb6834", LOGISTIC: BLUE, LIGHTGBM: "#2e9e6b", CONTRACT_RULE: "#8a63d2"}


@dataclass(frozen=True)
class Fold:
    test_year: int | None  # None for the deployed fold
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame


def _window_end(rows: pd.DataFrame) -> pd.Series:
    return rows["week_start"] + pd.Timedelta(days=7 + HORIZON_DAYS)


def make_fold(rows: pd.DataFrame, val_year: int, test_year: int | None) -> Fold:
    year, end = rows["week_start"].dt.year, _window_end(rows)
    train = rows[end <= pd.Timestamp(val_year, 1, 1)]
    val = rows[(year == val_year) & (end <= pd.Timestamp(val_year + 1, 1, 1))]
    test = rows[year == test_year] if test_year is not None else rows.iloc[0:0]
    if test_year is None:  # deployed: all of the last year is validation
        val = rows[year == val_year]
    return Fold(test_year, train, val, test)


def backtest_folds(rows: pd.DataFrame, test_years: list[int]) -> list[Fold]:
    return [make_fold(rows, y - 1, y) for y in test_years]


def _usable(fold: Fold) -> bool:
    parts = [fold.train, fold.val] + ([fold.test] if fold.test_year is not None else [])
    return all(p["label"].nunique() == 2 for p in parts)


def scorer_names(segment: str) -> tuple[str, ...]:
    return SCORERS + ((CONTRACT_RULE,) if segment == "contract_end" else ())


def fit_fold(fold: Fold, segment: str, cfg: GeneratorConfig) -> FoldModel:
    y = fold.train["label"].to_numpy()
    scorers = fit_scorers(fold.train, y, cfg.attrition_model, cfg.seed)
    model = FoldModel(scorers, {}, {}, scorer_names(segment),
                      training_means(scorers, fold.train))
    y_val = fold.val["label"].to_numpy()
    for name, raw in model.raw(fold.val).items():
        cal = PlattCalibrator(on_logit=name in (LOGISTIC, LIGHTGBM)).fit(raw, y_val)
        model.calibrators[name] = cal
        model.thresholds[name] = best_f1_threshold(y_val, cal.transform(raw))
    return model


@dataclass
class SegmentResult:
    segment: str
    val_preds: pd.DataFrame
    test_preds: pd.DataFrame
    skipped_years: list[int]
    deployed: FoldModel
    deployed_window: dict[str, str]
    winner: str = ""
    metrics: dict = field(default_factory=dict)


def _preds(fold: Fold, part: pd.DataFrame, model: FoldModel) -> pd.DataFrame:
    p = model.calibrated(part)
    out = pd.DataFrame({"week": part["week_start"].to_numpy(),
                        "days_until_contract_end": part["days_until_contract_end"].to_numpy(),
                        "year": part["week_start"].dt.year.to_numpy(),
                        "employee_id": part["employee_id"].to_numpy(),
                        "label": part["label"].to_numpy()})
    for n in model.names:
        out[n] = p[n]
        out[f"{n}_flag"] = p[n] >= model.thresholds[n]
    return out


def run_segment(features: pd.DataFrame, segment: str, cfg: GeneratorConfig) -> SegmentResult:
    rows = segment_rows(features, segment)
    vals, tests, skipped = [], [], []
    for fold in backtest_folds(rows, cfg.attrition_model.test_years):
        if not _usable(fold):
            skipped.append(fold.test_year)
            continue
        model = fit_fold(fold, segment, cfg)
        vals.append(_preds(fold, fold.val, model))
        tests.append(_preds(fold, fold.test, model))
    last_year = int(rows["week_start"].dt.year.max())
    deploy_fold = make_fold(rows, last_year, None)
    deployed = fit_fold(deploy_fold, segment, cfg)
    window = {"train_last_week": str(deploy_fold.train["week_start"].max().date()),
              "validation_weeks": f"{deploy_fold.val['week_start'].min().date()}.."
                                  f"{deploy_fold.val['week_start'].max().date()}"}
    result = SegmentResult(segment, pd.concat(vals, ignore_index=True),
                           pd.concat(tests, ignore_index=True), skipped, deployed, window)
    result.winner, result.metrics = summarise(result, cfg.attrition_model)
    return result


def summarise(r: SegmentResult, cfg: AttritionModelConfig) -> tuple[str, dict]:
    names = r.deployed.names
    val_pr = {n: classification_metrics(r.val_preds["label"].to_numpy(), r.val_preds[n].to_numpy(),
                                        r.val_preds[f"{n}_flag"].to_numpy())["pr_auc"]
              for n in names}
    winner = max(val_pr, key=val_pr.get)
    y = r.test_preds["label"].to_numpy()
    test = {}
    for n in names:
        m = classification_metrics(y, r.test_preds[n].to_numpy(),
                                   r.test_preds[f"{n}_flag"].to_numpy())
        per_year = r.test_preds.groupby("year").apply(
            lambda g, n=n: classification_metrics(g["label"].to_numpy(), g[n].to_numpy(),
                                                  g[f"{n}_flag"].to_numpy())["roc_auc"],
            include_groups=False)
        m["roc_auc_by_year"] = {str(k): round(float(v), 4) for k, v in per_year.items()}
        m["leavers"] = int(r.test_preds.loc[r.test_preds["label"] == 1, "employee_id"].nunique())
        test[n] = m
    table = calibration_table(y, r.test_preds[winner].to_numpy())
    bands = {n: band_metrics(r.test_preds[["week", "label", n]], n, cfg) for n in names}
    metrics = {"segment": r.segment, "contract_type": SEGMENTS[r.segment][0],
               "winner": winner, "winner_rule": "highest pooled validation PR-AUC",
               "explain_model": EXPLAIN_MODEL, "validation_pr_auc": val_pr, "test": test,
               "test_years": sorted(int(y) for y in r.test_preds["year"].unique()),
               "skipped_test_years": r.skipped_years,
               "calibration_table_winner": table.to_dict(orient="records"),
               "rank_bands_test": bands,
               **({"contract_date_rule_bands_test": rule_band_metrics(r.test_preds, cfg)}
                  if r.segment == "contract_end" else {}),
               "deployed_window": r.deployed_window,
               "deployed_thresholds": {n: round(t, 4) for n, t in r.deployed.thresholds.items()}}
    return winner, metrics


def save_plot(results: dict[str, SegmentResult], path: Path = PLOT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, len(results), figsize=(6 * len(results), 5), facecolor=SURFACE)
    for ax, r in zip(np.atleast_1d(axes), results.values(), strict=True):
        y = r.test_preds["label"].to_numpy()
        top = 0.0
        for n in r.deployed.names:
            t = calibration_table(y, r.test_preds[n].to_numpy())
            top = max(top, t["mean_predicted"].max(), t["observed_rate"].max())
            ax.plot(t["mean_predicted"], t["observed_rate"], marker="o", color=LINE_COLORS[n],
                    linewidth=2.4 if n == r.winner else 1.2,
                    label=f"{n}{' (winner)' if n == r.winner else ''}")
        ax.plot([0, top], [0, top], color=INK_2, linestyle="--", linewidth=1, label="perfect")
        ax.legend(frameon=False, labelcolor=INK_2, loc="upper left")
        style_axes(ax, f"{r.segment}: calibration on pooled test years (SYNTHETIC)",
                   "Observed 90-day exit rate")
        ax.set_xlabel("Mean predicted risk (quantile bins)", color=INK_2)
    fig.tight_layout()
    fig.savefig(path, dpi=120, facecolor=SURFACE)
    plt.close(fig)
    return path


def bundle(results: dict[str, SegmentResult], cfg: GeneratorConfig) -> dict:
    m = cfg.attrition_model
    return {
        "features": MODEL_FEATURES,
        "bands": {"rule": "rank-based, ceil-count slots, tie groups never split",
                  "high_share": m.band_high_share, "watch_share": m.band_watch_share},
        "horizon_days": HORIZON_DAYS,
        "segments": {s: {"contract_type": SEGMENTS[s][0], "winner": r.winner,
                         "explain_model": EXPLAIN_MODEL, "model": r.deployed}
                     for s, r in results.items()},
    }


def save(results: dict[str, SegmentResult], cfg: GeneratorConfig,
         out_dir: Path = ARTIFACT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.joblib"
    joblib.dump(bundle(results, cfg), model_path)
    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps({s: r.metrics for s, r in results.items()}, indent=2)
                            + "\n", encoding="utf-8")
    features_path = out_dir / "feature_list.json"
    features_path.write_text(json.dumps(MODEL_FEATURES, indent=2) + "\n", encoding="utf-8")
    return [model_path, metrics_path, features_path]


def train_all(cfg: GeneratorConfig, data_dir: Path = DATA_DIR) -> dict[str, SegmentResult]:
    features = load_attrition_features(data_dir, cfg)
    return {s: run_segment(features, s, cfg) for s in SEGMENTS}


REPORT_COLUMNS = ["roc_auc", "pr_auc", "precision", "recall", "flagged_share", "brier",
                  "base_rate", "leavers"]


def report(results: dict[str, SegmentResult]) -> None:
    for r in results.values():
        m = r.metrics
        print(f"\n[{r.segment}] {m['contract_type']} staff, pooled test years {m['test_years']}"
              f" (skipped {m['skipped_test_years'] or 'none'}); winner = {r.winner} "
              f"(validation PR-AUC {m['validation_pr_auc'][r.winner]:.3f})")
        table = pd.DataFrame({n: {c: m["test"][n][c] for c in REPORT_COLUMNS}
                              for n in r.deployed.names}).T
        print(table.to_string())
        print("  ROC-AUC by test year: " + "; ".join(
            f"{n} {m['test'][n]['roc_auc_by_year']}" for n in r.deployed.names))
        for n in r.deployed.names:
            b = m["rank_bands_test"][n]
            print(f"  rank bands ({n}): high precision {b['high_precision']:.3f} = "
                  f"{b['high_lift']}x base {b['base_rate']:.3f}; leaver-weeks in high+watch "
                  f"{b['leaver_weeks_in_high_or_watch']:.1%}; tied share/week "
                  f"{b['tied_share_per_week_mean']:.2f}")
        if "contract_date_rule_bands_test" in m:
            b = m["contract_date_rule_bands_test"]
            print(f"  contract-date RULE bands (used for seasonal staff): high precision "
                  f"{b['high_precision']:.3f} = {b['high_lift']}x base {b['base_rate']:.3f}; "
                  f"leaver-weeks in high+watch {b['leaver_weeks_in_high_or_watch']:.1%}")
        print(f"  calibration ({r.winner}, test):")
        print(pd.DataFrame(m["calibration_table_winner"]).to_string(index=False))


def main(data_dir: Path = DATA_DIR, out_dir: Path = ARTIFACT_DIR,
         plot_path: Path = PLOT_PATH) -> dict[str, SegmentResult]:
    cfg = load_config()
    results = train_all(cfg, data_dir)
    print("Attrition model (SYNTHETIC data, planted drivers): expanding-window backtest, "
          f"{HORIZON_DAYS}-day label, 90-day gap")
    report(results)
    print("\nNOTE: logistic can win because the planted hazard is logistic in these drivers.")
    for p in save(results, cfg, out_dir):
        print(f"  saved {p}")
    print(f"  plot saved: {save_plot(results, plot_path)}")
    return results


if __name__ == "__main__":
    main()
