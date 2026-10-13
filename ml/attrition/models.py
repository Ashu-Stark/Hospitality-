"""Attrition scorers, Platt calibration, threshold choice and metrics (Task T7).

Scorers:
  rules     count (0-3) of: sustained overtime (overtime_window_mean >= rule hours), no weekend
            off for >= rule weeks, pulse fell by >= rule drop over 4 weeks. Thresholds are
            ASSUMED values in config.yaml attrition_model.
  logistic  standardised numerics + one-hot categoricals, L2 logistic regression
  lightgbm  small, heavily regularised gradient-boosted trees (fixed settings, not tuned)
Every scorer is calibrated with Platt scaling (a 1-D logistic fit of the label on the raw score,
on the VALIDATION year) because a validation year holds only ~5-15 leavers, too few for
isotonic regression. The flag threshold maximises F1 on the validation year.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.attrition.features import MODEL_FEATURES, MODEL_NUMERIC
from ml.features.build_features import CATEGORICAL_FEATURES, CONTRACT_END_CAP_DAYS
from ml.generator.config import AttritionModelConfig

RULES, LOGISTIC, LIGHTGBM = "rules", "logistic", "lightgbm"
SCORERS = (RULES, LOGISTIC, LIGHTGBM)
CONTRACT_RULE = "contract_rule"  # contract_end only: fewer days to the contract end = higher risk
LOGISTIC_MAX_ITER = 2000
LGBM_PARAMS = dict(n_estimators=200, learning_rate=0.05, num_leaves=8, min_child_samples=50,
                   colsample_bytree=0.8, n_jobs=1, deterministic=True, force_row_wise=True,
                   verbose=-1)
LOGIT_CLIP = 1e-6
CALIBRATION_BINS = 5


def rule_conditions(df: pd.DataFrame, cfg: AttritionModelConfig) -> pd.DataFrame:
    return pd.DataFrame({
        "sustained_overtime": df["overtime_window_mean"] >= cfg.rule_sustained_overtime_hours,
        "no_weekend_off": df["weeks_since_weekend_off"] >= cfg.rule_weeks_without_weekend_off,
        "falling_pulse": -df["pulse_trend_4w"] >= cfg.rule_pulse_drop,
    }, index=df.index)


def rule_score(df: pd.DataFrame, cfg: AttritionModelConfig) -> np.ndarray:
    return rule_conditions(df, cfg).sum(axis=1).to_numpy(dtype=float)


class LightGBMScorer:
    """LightGBM on one-hot categoricals; keeps the design columns for scoring and SHAP."""

    def __init__(self, seed: int) -> None:
        self.model = lgb.LGBMClassifier(random_state=seed, **LGBM_PARAMS)
        self.columns: list[str] = []

    def design(self, df: pd.DataFrame) -> pd.DataFrame:
        x = pd.get_dummies(df[MODEL_FEATURES], columns=CATEGORICAL_FEATURES, dtype=float)
        return x.reindex(columns=self.columns, fill_value=0.0) if self.columns else x

    def fit(self, df: pd.DataFrame, y: np.ndarray) -> LightGBMScorer:
        x = self.design(df)
        self.columns = list(x.columns)
        self.model.fit(x, y)
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(self.design(df))[:, 1]


def fit_logistic(df: pd.DataFrame, y: np.ndarray, seed: int) -> Pipeline:
    prep = ColumnTransformer([
        ("num", StandardScaler(), MODEL_NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    model = Pipeline([("prep", prep), ("clf", LogisticRegression(
        max_iter=LOGISTIC_MAX_ITER, random_state=seed))])
    return model.fit(df[MODEL_FEATURES], y)


@dataclass
class FittedScorers:
    logistic: Pipeline
    lightgbm: LightGBMScorer
    rule_cfg: AttritionModelConfig

    def raw(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        return {RULES: rule_score(df, self.rule_cfg),
                LOGISTIC: self.logistic.predict_proba(df[MODEL_FEATURES])[:, 1],
                LIGHTGBM: self.lightgbm.predict_proba(df)}


def fit_scorers(df: pd.DataFrame, y: np.ndarray, cfg: AttritionModelConfig,
                seed: int) -> FittedScorers:
    return FittedScorers(fit_logistic(df, y, seed), LightGBMScorer(seed).fit(df, y), cfg)


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, LOGIT_CLIP, 1 - LOGIT_CLIP)
    return np.log(p / (1 - p))


@dataclass
class PlattCalibrator:
    """p = sigmoid(a * x + b), x = logit(raw) for probabilities, raw itself for rule counts."""

    on_logit: bool
    a: float = 1.0
    b: float = 0.0

    def _x(self, raw: np.ndarray) -> np.ndarray:
        return _logit(raw) if self.on_logit else np.asarray(raw, dtype=float)

    def fit(self, raw: np.ndarray, y: np.ndarray) -> PlattCalibrator:
        lr = LogisticRegression(C=np.inf).fit(self._x(raw).reshape(-1, 1), y)
        self.a, self.b = float(lr.coef_[0, 0]), float(lr.intercept_[0])
        return self

    def transform(self, raw: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-(self.a * self._x(raw) + self.b)))


def best_f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    """Probability threshold with the highest F1 (flag when p >= threshold)."""
    precision, recall, thresholds = precision_recall_curve(y, p)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    return float(thresholds[int(np.argmax(f1))])


def classification_metrics(y: np.ndarray, p: np.ndarray, flag: np.ndarray) -> dict[str, float]:
    tp = int((flag & (y == 1)).sum())
    return {
        "rows": int(len(y)), "positives": int(y.sum()), "base_rate": round(float(y.mean()), 4),
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "precision": round(tp / flag.sum(), 4) if flag.any() else 0.0,
        "recall": round(tp / y.sum(), 4) if y.any() else 0.0,
        "flagged_share": round(float(flag.mean()), 4),
        "brier": round(float(brier_score_loss(y, p)), 5),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = CALIBRATION_BINS) -> pd.DataFrame:
    """Quantile bins of predicted risk: rows, mean predicted, observed rate."""
    q = pd.qcut(pd.Series(p).rank(method="first"), bins, labels=False)
    t = pd.DataFrame({"bin": q, "y": y, "p": p}).groupby("bin").agg(
        rows=("y", "size"), mean_predicted=("p", "mean"), observed_rate=("y", "mean"))
    return t.round(4).reset_index()


# Raw feature behind each rule condition, so rule contributions map to driver categories.
RULE_FEATURES = {"sustained_overtime": "overtime_window_mean",
                 "no_weekend_off": "weeks_since_weekend_off",
                 "falling_pulse": "pulse_trend_4w"}


def logistic_design(model: Pipeline, df: pd.DataFrame) -> pd.DataFrame:
    """The logistic model's transformed inputs (standardised numerics, one-hot categoricals)."""
    prep = model.named_steps["prep"]
    x = prep.transform(df[MODEL_FEATURES])
    x = x.toarray() if hasattr(x, "toarray") else np.asarray(x)
    names = [n.split("__", 1)[1] for n in prep.get_feature_names_out()]
    return pd.DataFrame(x, columns=names, index=df.index)


def training_means(scorers: FittedScorers, train: pd.DataFrame) -> dict[str, pd.Series]:
    """Training-set means of each scorer's inputs: the reference point of its contributions."""
    return {
        LOGISTIC: logistic_design(scorers.logistic, train).mean(),
        RULES: rule_conditions(train, scorers.rule_cfg).astype(float).mean(),
        CONTRACT_RULE: pd.Series({"days_until_contract_end":
                                  float(train["days_until_contract_end"].mean())}),
    }


@dataclass
class FoldModel:
    """Every scorer of one fold with its validation calibration, threshold and training means.

    contributions(df, name) explains the SAME scorer that produces the risk, in CALIBRATED
    log-odds (the Platt slope a times the scorer's own terms), relative to the training mean:
      logistic       a * coef_j * (x_j - mean_j) on the standardised / one-hot inputs
      rules          a * (condition_j - mean_j)
      contract_rule  a * -(days_until_contract_end - mean)   (fewer days = higher risk)
      lightgbm       a * TreeSHAP_j (already relative to the expected value)
    Columns are feature names (one-hot columns as 'feature_value').
    """

    scorers: FittedScorers
    calibrators: dict[str, PlattCalibrator]
    thresholds: dict[str, float]
    names: tuple[str, ...]
    means: dict[str, pd.Series] = field(default_factory=dict)

    def contributions(self, df: pd.DataFrame, name: str) -> pd.DataFrame:
        a = self.calibrators[name].a
        if name == LOGISTIC:
            x = logistic_design(self.scorers.logistic, df)
            coef = self.scorers.logistic.named_steps["clf"].coef_[0]
            return a * (x - self.means[LOGISTIC]) * coef
        if name == RULES:
            cond = rule_conditions(df, self.scorers.rule_cfg).astype(float)
            return (a * (cond - self.means[RULES])).rename(columns=RULE_FEATURES)
        if name == CONTRACT_RULE:
            col = "days_until_contract_end"
            return pd.DataFrame({col: -a * (df[col] - self.means[CONTRACT_RULE][col])},
                                index=df.index)
        lgbm = self.scorers.lightgbm
        contrib = lgbm.model.booster_.predict(lgbm.design(df), pred_contrib=True)[:, :-1]
        return pd.DataFrame(a * contrib, columns=lgbm.columns, index=df.index)

    def raw(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        raw = self.scorers.raw(df)
        if CONTRACT_RULE in self.names:
            raw[CONTRACT_RULE] = (CONTRACT_END_CAP_DAYS - df["days_until_contract_end"]).to_numpy(
                dtype=float)
        return raw

    def calibrated(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        return {n: self.calibrators[n].transform(r) for n, r in self.raw(df).items()}
