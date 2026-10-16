"""Attrition scorers, Platt calibration, threshold choice and metrics (Task T7).

Scorers:
  rules     count (0-3) of: sustained overtime (overtime_window_mean >= rule hours), no weekend
            off for >= rule weeks, pulse fell by >= rule drop over 4 weeks. Thresholds are
            ASSUMED values in config.yaml attrition_model.
  logistic  standardised numerics + one-hot categoricals, L2 logistic regression (C = 1, no
            class weights), trained with torch on the GPU (ml/torch_logistic.py)
  xgboost   small, heavily regularised gradient-boosted trees (fixed settings, not tuned),
            trained with XGBoost on the GPU; replaces the earlier LightGBM comparison
Every scorer is calibrated with Platt scaling (a 1-D logistic fit of the label on the raw score,
on the VALIDATION year, also on the GPU) because a validation year holds only ~5-15 leavers, too
few for isotonic regression. The flag threshold maximises F1 on the validation year.
Training refuses to run without CUDA (ml/gpu.py). For evaluation the fitted models predict on
the GPU; the saved bundle is switched to CPU inference (numpy coefficients and an exported
TreeEnsemble), so the servers need neither torch nor xgboost.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml import gpu
from ml.attrition.features import MODEL_FEATURES, MODEL_NUMERIC
from ml.features.build_features import CATEGORICAL_FEATURES, CONTRACT_END_CAP_DAYS
from ml.generator.config import AttritionModelConfig
from ml.torch_logistic import TorchLogisticRegression, platt_fit
from ml.xgb_trees import TreeEnsemble

RULES, LOGISTIC, XGBOOST = "rules", "logistic", "xgboost"
SCORERS = (RULES, LOGISTIC, XGBOOST)
CONTRACT_RULE = "contract_rule"  # contract_end only: fewer days to the contract end = higher risk
LOGISTIC_MAX_ITER = 2000
# The earlier LightGBM settings mapped to XGBoost: 200 rounds, rate 0.05, leaf-wise with at most
# 8 leaves, 0.8 column subsampling. LightGBM's "at least 50 rows per leaf" has no XGBoost
# equivalent (min_child_weight is a hessian sum, p(1-p) per row for a rare label), so the
# XGBoost default min_child_weight 1 and L2 lambda 1 are kept.
XGB_PARAMS = dict(n_estimators=200, learning_rate=0.05, grow_policy="lossguide", max_leaves=8,
                  max_depth=0, colsample_bytree=0.8, **gpu.XGB_DEVICE)
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


class XGBoostScorer:
    """XGBoost (GPU) on one-hot categoricals; keeps the design columns for scoring and SHAP.

    After fit, `model` is the exported TreeEnsemble (numpy, CPU inference); while `on_gpu` is
    True (training / evaluation) predictions and TreeSHAP run on the GPU."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.model: TreeEnsemble | None = None
        self.columns: list[str] = []
        self.on_gpu = False

    def design(self, df: pd.DataFrame) -> pd.DataFrame:
        x = pd.get_dummies(df[MODEL_FEATURES], columns=CATEGORICAL_FEATURES, dtype=float)
        return x.reindex(columns=self.columns, fill_value=0.0) if self.columns else x

    def fit(self, df: pd.DataFrame, y: np.ndarray) -> XGBoostScorer:
        import xgboost as xgb

        gpu.require_cuda()
        x = self.design(df)
        self.columns = list(x.columns)
        clf = xgb.XGBClassifier(random_state=self.seed, **XGB_PARAMS).fit(x, y)
        gpu.assert_xgb_on_cuda(clf)
        self.model = TreeEnsemble.from_xgb(clf, x)
        self.on_gpu = True
        return self

    def to_cpu(self) -> XGBoostScorer:
        self.on_gpu = False
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if self.on_gpu:
            from ml.xgb_trees import predict_gpu

            return predict_gpu(self.model, self.design(df), proba=True)
        return self.model.predict_proba(self.design(df))[:, 1]

    def shap(self, df: pd.DataFrame) -> np.ndarray:
        """TreeSHAP (log-odds) per design column, bias column dropped; XGBoost on the GPU."""
        import xgboost as xgb

        x = self.design(df)
        dm = xgb.DMatrix(x.to_numpy(dtype=np.float32), feature_names=self.columns)
        return self.model.gpu_booster().predict(dm, pred_contribs=True)[:, :-1]


def fit_logistic(df: pd.DataFrame, y: np.ndarray, seed: int) -> Pipeline:
    prep = ColumnTransformer([
        ("num", StandardScaler(), MODEL_NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])
    model = Pipeline([("prep", prep), ("clf", TorchLogisticRegression(
        C=1.0, max_iter=LOGISTIC_MAX_ITER, random_state=seed))])
    return model.fit(df[MODEL_FEATURES], y)


@dataclass
class FittedScorers:
    logistic: Pipeline
    xgboost: XGBoostScorer
    rule_cfg: AttritionModelConfig

    def raw(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        return {RULES: rule_score(df, self.rule_cfg),
                LOGISTIC: self.logistic.predict_proba(df[MODEL_FEATURES])[:, 1],
                XGBOOST: self.xgboost.predict_proba(df)}


def fit_scorers(df: pd.DataFrame, y: np.ndarray, cfg: AttritionModelConfig,
                seed: int) -> FittedScorers:
    return FittedScorers(fit_logistic(df, y, seed), XGBoostScorer(seed).fit(df, y), cfg)


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
        self.a, self.b = platt_fit(self._x(raw), y)
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
      xgboost        a * TreeSHAP_j (already relative to the expected value; GPU, needs xgboost)
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
        tree = self.scorers.xgboost
        return pd.DataFrame(a * tree.shap(df), columns=tree.columns, index=df.index)

    def raw(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        raw = self.scorers.raw(df)
        if CONTRACT_RULE in self.names:
            raw[CONTRACT_RULE] = (CONTRACT_END_CAP_DAYS - df["days_until_contract_end"]).to_numpy(
                dtype=float)
        return raw

    def calibrated(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        return {n: self.calibrators[n].transform(r) for n, r in self.raw(df).items()}
