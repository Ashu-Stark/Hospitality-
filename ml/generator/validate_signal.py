"""Attrition SIGNAL checks (Task T4): are the planted drivers visible but not dominant?

Uses only observable data (the attrition feature matrix built from output tables), never
data/internal/.

IMPORTANT: the difficulty bands are generator-difficulty targets chosen by this project, not
real-world benchmarks. The planted drivers make every probe result a demonstration of the
mechanism, never evidence of real-world predictive accuracy.

Difficulty probes (PERMANENT staff only; seasonal contract ends are a separate exit route):
- Expanding window: for every test year Y from the third calendar year of data to the last year
  with uncensored rows, train on ALL usable rows whose 90-day label window ends before
  1 January of Y (a 90-day gap, so no training label looks into the test year), test on Y.
- Three scorers: the overtime-only rule (4-week overtime average), a regularised LightGBM and a
  standardised logistic regression on the attrition features. The pass/fail model is the better
  of LightGBM and logistic, and the report names it.
- Two numbers per scorer: (a) the mean of the per-year ROC-AUCs and (b) the ROC-AUC after
  converting each year's scores to within-year percentile ranks and pooling. (b) is pass/fail.
  Ranking within each year matters because every year has its own model, whose raw scores are
  not on a common scale; pooling raw scores penalised the models (an earlier version did that).
- A single test year holds only ~7-15 permanent leavers, so single-year AUCs swing by about
  +/-0.07 on the same data. validate_seeds.py pools several generator seeds for a steadier view.
- The no-visible-driver share is pass/fail only on the 3-seed pool (validate_seeds.py, band
  5%-20%); python run.py validate shows the single-seed share as INFO because ~50 leavers per
  seed make it noisy (it ranged 2.7%-11.8% across seeds 42-53 with the A5 config).

Definitions (thresholds from config.yaml):
- A driver is "visible" in an employee-week when its logit contribution (behaviour.py
  driver_contributions, computed from observable features) is >= visible_driver_min_logit.
- An exit has "no visible driver" when it is a resignation and the employee's last active week
  shows no visible driver (seasonal_end exits always have one: the contract end).
- A "high-driver employee" has an uncensored week with >= high_driver_min_count visible
  drivers; "did not leave" means no exit in the label horizon after their first such week.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.features.build_features import (
    CATEGORICAL_FEATURES,
    CENSORED,
    FEATURES,
    HORIZON_DAYS,
    LABEL,
    NUMERIC_FEATURES,
    build_features,
)
from ml.generator.attrition import SEASONAL_END, AttritionResult, annual_attrition_rate
from ml.generator.behaviour import DRIVERS, DriverInputs, driver_contributions
from ml.generator.config import GeneratorConfig
from ml.generator.validate_occupancy import Check

# Acceptance targets for Task T4 (generator-difficulty targets, not real-world benchmarks).
ATTRITION_TOLERANCE = 0.05
OVERTIME_RULE_AUC = (0.60, 0.72)
MODEL_AUC = (0.68, 0.82)
MIN_MODEL_GAIN = 0.04  # best model must beat the overtime-only rule by at least this much
NO_DRIVER_SHARE = (0.05, 0.20)  # gated on the 3-seed pool only (validate_seeds.py)
MIN_HIGH_DRIVER_STAYERS = 0.15
DAYS_PER_YEAR = 365.25

# Probe models: fixed and regularised for tiny data (not tuned; the real model is T7).
MIN_TRAIN_YEARS = 2  # first test year = first data year + this
LGBM_PARAMS = dict(n_estimators=200, learning_rate=0.05, num_leaves=8, min_child_samples=50,
                   colsample_bytree=0.8, n_jobs=1, deterministic=True, force_row_wise=True,
                   verbose=-1)
LOGISTIC_MAX_ITER = 2000
RULE = "overtime_rule"
MODELS = ("lightgbm", "logistic")
SCORERS = (RULE, *MODELS)


@dataclass(frozen=True)
class ScorerResult:
    auc_rank_pooled: float  # (b): pass/fail number
    pr_auc_rank_pooled: float
    auc_mean_years: float  # (a): reported beside it


@dataclass(frozen=True)
class ProbeSummary:
    scorers: dict[str, ScorerResult]
    best_model: str
    leavers: int
    rows: int
    base_rate: float

    @property
    def rule(self) -> ScorerResult:
        return self.scorers[RULE]

    @property
    def best(self) -> ScorerResult:
        return self.scorers[self.best_model]

    @property
    def gap(self) -> float:
        return self.best.auc_rank_pooled - self.rule.auc_rank_pooled


@dataclass(frozen=True)
class SignalNumbers:
    attrition: float
    predictions: pd.DataFrame  # one row per permanent test employee-week, all scorers
    probes: ProbeSummary
    no_driver_share: float
    exits_considered: int
    high_driver_employees: int
    high_driver_stayers: float
    censored_rows: int
    driver_share_of_exits: dict[str, float]


def driver_frame(features: pd.DataFrame, cfg: GeneratorConfig) -> pd.DataFrame:
    """Per-row logit contribution of every observable driver."""
    d = DriverInputs(
        overtime_avg=features["overtime_window_mean"].to_numpy(),
        weeks_without_leave=features["weeks_without_leave"].to_numpy(),
        pulse_4wk=features["pulse_roll4_mean"].to_numpy(),
        pulse_drop_4wk=-features["pulse_trend_4w"].to_numpy(),
        pay_ratio=features["pay_ratio"].to_numpy(),
        months_since_raise=features["months_since_raise"].to_numpy(),
        load_ratio=features["load_ratio"].to_numpy(),
        peer_exits=features["peer_exits"].to_numpy(),
        tenure_years=features["tenure_days"].to_numpy() / DAYS_PER_YEAR,
    )
    return pd.DataFrame(driver_contributions(d, cfg.attrition.hazard), index=features.index)


def result_features(result: AttritionResult, cfg: GeneratorConfig) -> pd.DataFrame:
    return build_features(result.employees, result.weekly_behaviour, result.exits,
                          result.contract_renewals, result.pay_changes, cfg)


# --- probes ---------------------------------------------------------------------------------


def expanding_probe_splits(
    features: pd.DataFrame,
) -> list[tuple[int, pd.DataFrame, pd.DataFrame]]:
    """(test_year, train, test): train = all rows whose label window ends before 1 Jan of Y."""
    usable = features[~features[CENSORED] & (features["contract_type"] == "permanent")]
    year = usable["week_start"].dt.year
    window_end = usable["week_start"] + pd.Timedelta(days=7 + HORIZON_DAYS)
    splits = []
    for test_year in range(int(year.min()) + MIN_TRAIN_YEARS, int(year.max()) + 1):
        train = usable[window_end <= pd.Timestamp(test_year, 1, 1)]
        test = usable[year == test_year]
        if test[LABEL].nunique() == 2 and train[LABEL].nunique() == 2:
            splits.append((test_year, train, test))
    return splits


def _lightgbm_scores(train: pd.DataFrame, test: pd.DataFrame, seed: int) -> np.ndarray:
    def design(df: pd.DataFrame) -> pd.DataFrame:
        return pd.get_dummies(df[FEATURES], columns=CATEGORICAL_FEATURES, dtype=float)

    x_train = design(train)
    x_test = design(test).reindex(columns=x_train.columns, fill_value=0.0)
    model = lgb.LGBMClassifier(random_state=seed, **LGBM_PARAMS)
    model.fit(x_train, train[LABEL])
    return model.predict_proba(x_test)[:, 1]


def _logistic_scores(train: pd.DataFrame, test: pd.DataFrame, seed: int) -> np.ndarray:
    prep = ColumnTransformer([
        ("num", StandardScaler(), NUMERIC_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    model = Pipeline([("prep", prep), ("clf", LogisticRegression(
        max_iter=LOGISTIC_MAX_ITER, random_state=seed))])
    model.fit(train[FEATURES], train[LABEL])
    return model.predict_proba(test[FEATURES])[:, 1]


def probe_predictions(features: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Every expanding-window test row: test_year, employee_id, label and one score per scorer."""
    frames = []
    for year, train, test in expanding_probe_splits(features):
        frames.append(pd.DataFrame({
            "test_year": year,
            "employee_id": test["employee_id"].to_numpy(),
            "label": test[LABEL].to_numpy(),
            RULE: test["overtime_roll4_mean"].to_numpy(),
            "lightgbm": _lightgbm_scores(train, test, seed),
            "logistic": _logistic_scores(train, test, seed),
        }))
    columns = ["test_year", "employee_id", "label", *SCORERS]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def summarise_probes(preds: pd.DataFrame, group_cols: list[str]) -> ProbeSummary:
    """(a) mean per-group AUC and (b) AUC of within-group percentile ranks, per scorer.

    group_cols is ["test_year"] for one seed and ["seed", "test_year"] across seeds.
    """
    y = preds["label"]
    groups = preds.groupby(group_cols, sort=False)
    scorers = {}
    for name in SCORERS:
        ranks = groups[name].rank(pct=True)
        per_group = [roc_auc_score(g["label"], g[name]) for _, g in groups
                     if g["label"].nunique() == 2]
        scorers[name] = ScorerResult(
            auc_rank_pooled=float(roc_auc_score(y, ranks)),
            pr_auc_rank_pooled=float(average_precision_score(y, ranks)),
            auc_mean_years=float(np.mean(per_group)),
        )
    best = max(MODELS, key=lambda m: scorers[m].auc_rank_pooled)
    id_cols = [c for c in ("seed", "employee_id") if c in preds]
    leavers = int(preds.loc[y == 1, id_cols].drop_duplicates().shape[0])
    return ProbeSummary(scorers, best, leavers, len(preds), float(y.mean()))


def probe_checks(p: ProbeSummary, scope: str) -> list[Check]:
    """Difficulty checks shared by validate (one seed) and validate-seeds (pooled)."""
    (r_lo, r_hi), (m_lo, m_hi) = OVERTIME_RULE_AUC, MODEL_AUC
    return [
        Check(f"{scope}: overtime-only rule ROC-AUC (ranked, pooled) in [{r_lo}, {r_hi}]",
              r_lo <= p.rule.auc_rank_pooled <= r_hi,
              f"{p.rule.auc_rank_pooled:.3f} (mean of years {p.rule.auc_mean_years:.3f}, "
              f"{p.leavers} leavers)"),
        Check(f"{scope}: best model ROC-AUC (ranked, pooled) in [{m_lo}, {m_hi}]",
              m_lo <= p.best.auc_rank_pooled <= m_hi,
              f"{p.best_model} {p.best.auc_rank_pooled:.3f} (mean of years "
              f"{p.best.auc_mean_years:.3f}, PR-AUC {p.best.pr_auc_rank_pooled:.3f})"),
        Check(f"{scope}: best model beats the rule by >= {MIN_MODEL_GAIN}",
              p.gap >= MIN_MODEL_GAIN, f"gap {p.gap:+.3f}"),
    ]


def no_driver_check(no_driver_share: float, scope: str) -> Check:
    """Gate for the pooled multi-seed run only; single-seed shares are too noisy."""
    lo, hi = NO_DRIVER_SHARE
    return Check(f"{scope}: exits with no visible driver in [{lo:.0%}, {hi:.0%}]",
                 lo <= no_driver_share <= hi, f"{no_driver_share:.1%}")


def no_driver_info(n: SignalNumbers) -> str:
    """Single-seed no-driver share, reported for information (not pass/fail)."""
    lo, hi = NO_DRIVER_SHARE
    return (f"INFO  exits with no visible driver (single seed): {n.no_driver_share:.1%} of "
            f"{n.exits_considered}. Not pass/fail: a single seed has only ~50 permanent leavers, "
            f"so this share is noisy; it is gated on the 3-seed pool in python run.py "
            f"validate-seeds (band {lo:.0%}-{hi:.0%}).")


def probe_table(preds: pd.DataFrame, p: ProbeSummary) -> pd.DataFrame:
    """Per-test-year AUCs plus (a) the mean of years and (b) the ranked pooled AUC."""
    rows = []
    for year, g in preds.groupby("test_year"):
        rows.append({"test_year": year, "rows": len(g),
                     "leavers": int(g.loc[g["label"] == 1, "employee_id"].nunique()),
                     **{f"{s}_auc": round(roc_auc_score(g["label"], g[s]), 3)
                        for s in SCORERS}})
    rows.append({"test_year": "(a) mean of years", "rows": p.rows, "leavers": p.leavers,
                 **{f"{s}_auc": round(p.scorers[s].auc_mean_years, 3) for s in SCORERS}})
    rows.append({"test_year": "(b) ranked pooled", "rows": p.rows, "leavers": p.leavers,
                 **{f"{s}_auc": round(p.scorers[s].auc_rank_pooled, 3) for s in SCORERS}})
    return pd.DataFrame(rows)


# --- whole-dataset numbers ------------------------------------------------------------------


def signal_numbers(result: AttritionResult, cfg: GeneratorConfig) -> SignalNumbers:
    a = cfg.attrition
    feats = result_features(result, cfg)
    visible = driver_frame(feats, cfg) >= a.visible_driver_min_logit
    feats["n_visible"] = visible.sum(axis=1)

    # Exits: drivers visible in the employee's last active week.
    last_rows = feats.sort_values("week_start").groupby("employee_id").tail(1)
    last = last_rows.set_index("employee_id")
    exits = result.exits[result.exits["employee_id"].isin(last.index)]
    resign = exits[exits["exit_reason"] != SEASONAL_END]
    no_driver = (last.loc[resign["employee_id"], "n_visible"] == 0).to_numpy()
    last_visible = visible.loc[last_rows.index].set_axis(last.index)
    share = {drv: float(last_visible.loc[resign["employee_id"], drv].mean()) for drv in DRIVERS}

    unc = feats[~feats[CENSORED]]
    high = unc[unc["n_visible"] >= a.high_driver_min_count]
    first_high = high.sort_values("week_start").groupby("employee_id").head(1)

    preds = probe_predictions(feats, cfg.seed)
    return SignalNumbers(
        attrition=annual_attrition_rate(result),
        predictions=preds,
        probes=summarise_probes(preds, ["test_year"]),
        no_driver_share=float(no_driver.sum() / len(exits)) if len(exits) else 0.0,
        exits_considered=len(exits),
        high_driver_employees=len(first_high),
        high_driver_stayers=float((first_high[LABEL] == 0).mean()) if len(first_high) else 0.0,
        censored_rows=int(feats[CENSORED].sum()),
        driver_share_of_exits=share,
    )


def censoring_ok(result: AttritionResult, cfg: GeneratorConfig) -> tuple[bool, str]:
    """Label horizon equals config; every censored row's window passes the data end."""
    feats = result_features(result, cfg)
    end = feats["week_start"].max() + pd.Timedelta(days=7)
    window_end = feats["week_start"] + pd.Timedelta(days=7 + HORIZON_DAYS)
    censored = feats[CENSORED]
    ok = (HORIZON_DAYS == cfg.label_horizon_days
          and bool((censored == (window_end > end)).all())
          and bool(feats.loc[censored, LABEL].isna().all())
          and bool(censored.any()))
    first = feats.loc[censored, "week_start"].min()
    return ok, f"{HORIZON_DAYS}d, {int(censored.sum())} rows censored from {first.date()}"


def signal_checks(
    result: AttritionResult, cfg: GeneratorConfig, n: SignalNumbers | None = None
) -> list[Check]:
    n = n if n is not None else signal_numbers(result, cfg)
    target = cfg.target_annual_attrition
    censor_ok, censor_detail = censoring_ok(result, cfg)
    return [
        Check(f"annual attrition within {ATTRITION_TOLERANCE:.0%} of target {target:.0%}",
              abs(n.attrition - target) <= ATTRITION_TOLERANCE, f"{n.attrition:.1%}"),
        *probe_checks(n.probes, "permanent"),
        Check(f"high-driver employees who did not leave >= {MIN_HIGH_DRIVER_STAYERS:.0%}",
              n.high_driver_stayers >= MIN_HIGH_DRIVER_STAYERS,
              f"{n.high_driver_stayers:.1%} of {n.high_driver_employees}"),
        Check(f"label horizon {cfg.label_horizon_days} days with censoring", censor_ok,
              censor_detail),
    ]
