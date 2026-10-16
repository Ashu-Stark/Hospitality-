"""Attrition models re-fitted on PUBLIC employee-turnover datasets (no hotel staff data is
public, so neither dataset is from a hotel).

Datasets (see sources.py / README):
  ibm_hr      IBM HR Analytics, FICTIONAL (created by IBM data scientists), 1,470 rows,
              label Attrition == "Yes".
  turnover    Babushkin employee turnover, stated by its author to be REAL (provenance not
              documented), 1,129 rows of survival data: stag = tenure (months, by its range),
              event = 1 quit / 0 still employed (censored). Label = quit within 12 months;
              people still employed with < 12 months tenure are EXCLUDED (unknown outcome).

PROTECTED / PERSONAL columns are dropped BEFORE any modelling, even though the files have
them: age, gender, marital status, the supervisor's gender, and (turnover) the five
personality-test scores (psychometric data a hotel would not and should not hold).
Neither dataset has dates, so a time split is impossible: evaluation is repeated stratified
5-fold cross-validation (3 repeats, seeds 42-44), with calibration fitted INSIDE each
training fold (Platt / sigmoid, 5 inner folds, the 5 calibrated inner models averaged) so no
test-fold row touches any fitted part.

Scorers: rules baseline (count of ASSUMED warning conditions fixed before seeing results),
logistic regression (standardised numerics + one-hot, L2, C = 1: the same model as the
deployed ml/attrition logistic, trained with torch on the GPU) and XGBoost (GPU; it replaced
the earlier LightGBM comparison). GPU ONLY: every fit, every Platt fit and every evaluation
prediction runs on CUDA (ml/gpu.py refuses without it). Only pandas feature preparation, the
fold splitting and sklearn.metrics on the final prediction arrays run on the CPU.
Plain-language rating and limits: ml/realdata/attrition/VALIDATION.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from ml import gpu
from ml.torch_logistic import TorchLogisticRegression, platt_fit

LABEL = "label"
QUIT_WINDOW_MONTHS = 12.0
SEEDS = (42, 43, 44)
N_FOLDS = 5


@dataclass(frozen=True)
class Spec:
    name: str
    protected: tuple[str, ...]   # dropped: personal / protected attributes
    unused: tuple[str, ...]      # dropped: ids, constants, label sources
    categorical: tuple[str, ...]
    rules: str                   # plain description of the rules baseline


IBM_SPEC = Spec(
    name="ibm_hr",
    protected=("Age", "Gender", "MaritalStatus"),
    unused=("Attrition", "EmployeeCount", "EmployeeNumber", "Over18", "StandardHours"),
    categorical=("BusinessTravel", "Department", "EducationField", "JobRole", "OverTime"),
    rules="count of: OverTime == Yes, JobSatisfaction <= 2, WorkLifeBalance <= 2",
)
TURNOVER_SPEC = Spec(
    name="turnover",
    protected=("gender", "age", "head_gender", "extraversion", "independ", "selfcontrol",
               "anxiety", "novator"),
    unused=("stag", "event"),
    categorical=("industry", "profession", "traffic", "coach", "greywage", "way"),
    rules="count of: greywage == grey (unofficial pay), coach == no (no probation coach)",
)
SPECS = {s.name: s for s in (IBM_SPEC, TURNOVER_SPEC)}


def load_ibm(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df[LABEL] = (df["Attrition"] == "Yes").astype(int)
    return df


def load_turnover(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="latin-1")
    for c in TURNOVER_SPEC.categorical:
        df[c] = df[c].astype(str).str.strip()
    quit_early = (df["event"] == 1) & (df["stag"] <= QUIT_WINDOW_MONTHS)
    known = quit_early | (df["stag"] > QUIT_WINDOW_MONTHS)
    df = df[known].copy()
    df[LABEL] = quit_early[known].astype(int)
    return df.reset_index(drop=True)


def model_table(df: pd.DataFrame, spec: Spec) -> tuple[pd.DataFrame, np.ndarray]:
    """Features with protected and unused columns removed, and the label."""
    drop = [c for c in (*spec.protected, *spec.unused, LABEL) if c in df.columns]
    return df.drop(columns=drop), df[LABEL].to_numpy()


def rule_score(x: pd.DataFrame, spec: Spec) -> np.ndarray:
    if spec.name == "ibm_hr":
        conds = [x["OverTime"] == "Yes", x["JobSatisfaction"] <= 2, x["WorkLifeBalance"] <= 2]
    else:
        conds = [x["greywage"] == "grey", x["coach"] == "no"]
    return np.sum([c.to_numpy() for c in conds], axis=0).astype(float)


def _prep(x: pd.DataFrame, spec: Spec, ordinal: bool) -> ColumnTransformer:
    cat = [c for c in spec.categorical if c in x.columns]
    num = [c for c in x.columns if c not in cat]
    enc = (OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1) if ordinal
           else OneHotEncoder(handle_unknown="ignore"))
    return ColumnTransformer([("num", StandardScaler(), num), ("cat", enc, cat)])


def make_estimator(kind: str, x: pd.DataFrame, spec: Spec, seed: int):
    """Unfitted GPU estimator: torch logistic regression or XGBoost on CUDA."""
    if kind == "logistic":
        clf = TorchLogisticRegression(C=1.0, max_iter=5000, random_state=seed)
        return Pipeline([("prep", _prep(x, spec, False)), ("clf", clf)])
    if kind == "xgboost":
        import xgboost as xgb
        clf = xgb.XGBClassifier(n_estimators=300, learning_rate=0.05, max_depth=3,
                                min_child_weight=3, subsample=0.8, colsample_bytree=0.8,
                                random_state=seed, **gpu.XGB_DEVICE)
        return Pipeline([("prep", _prep(x, spec, False)), ("clf", clf)])
    raise ValueError(kind)


def _raw(est: Pipeline, x: pd.DataFrame) -> np.ndarray:
    """Score that Platt scaling calibrates: log-odds (logistic) or P(leave) (XGBoost); both are
    computed on the GPU."""
    if hasattr(est[-1], "decision_function"):
        return est[-1].decision_function(est[:-1].transform(x))
    return est.predict_proba(x)[:, 1]


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))


def calibrated_fit_predict(est: Pipeline, xtr: pd.DataFrame, ytr: np.ndarray,
                           xte: pd.DataFrame, seed: int) -> np.ndarray:
    """Platt-calibrated P(leave) for xte, as scikit-learn's CalibratedClassifierCV(sigmoid, cv=5)
    does it but on the GPU: per inner fold, fit on 4/5, Platt-fit on the held-out 1/5, predict
    xte; average the 5 calibrated predictions."""
    out = np.zeros(len(xte))
    inner = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=seed)
    for a, b in inner.split(xtr, ytr):
        m = clone(est).fit(xtr.iloc[a], ytr[a])
        slope, icpt = platt_fit(_raw(m, xtr.iloc[b]), ytr[b])
        out += _sigmoid(slope * _raw(m, xte) + icpt)
    return out / N_FOLDS


def _platt_rules(train_score: np.ndarray, y: np.ndarray, test_score: np.ndarray) -> np.ndarray:
    slope, icpt = platt_fit(train_score, y)
    return _sigmoid(slope * test_score + icpt)


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error over equal-count bins."""
    order = np.argsort(p, kind="stable")
    total = 0.0
    for chunk in np.array_split(order, bins):
        if len(chunk):
            total += len(chunk) * abs(p[chunk].mean() - y[chunk].mean())
    return float(total / len(y))


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 5) -> list[dict]:
    order = np.argsort(p, kind="stable")
    return [{"bin": i + 1, "rows": int(len(c)), "mean_predicted": round(float(p[c].mean()), 4),
             "observed_rate": round(float(y[c].mean()), 4)}
            for i, c in enumerate(np.array_split(order, bins))]


KINDS = ("rules", "logistic", "xgboost")
BOOTSTRAP = 2000  # resamples for the subset ROC-AUC confidence interval


def bootstrap_auc_ci(y: np.ndarray, p: np.ndarray, seed: int = 42,
                     n: int = BOOTSTRAP) -> dict:
    """ROC-AUC with a percentile bootstrap 95% CI (resamples with one class only are skipped)."""
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if 0 < y[i].sum() < len(i):
            vals.append(roc_auc_score(y[i], p[i]))
    point = roc_auc_score(y, p) if 0 < y.sum() < len(y) else float("nan")
    lo, hi = (np.percentile(vals, [2.5, 97.5]) if vals else (np.nan, np.nan))
    return {"roc_auc": round(float(point), 4), "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "valid_resamples": len(vals)}


def subset_report(y: np.ndarray, oof_mean: dict[str, np.ndarray], mask: np.ndarray,
                  name: str) -> dict:
    """Metrics of the full-data models on one subset (e.g. the hospitality industry)."""
    ys = y[mask]
    out = {"subset": name, "rows": int(mask.sum()), "positives": int(ys.sum()),
           "base_rate": round(float(ys.mean()), 4) if mask.any() else None,
           "note": "out-of-fold predictions of models trained on ALL industries (mean of the 3 "
                   "repeats); tiny sample: the interval is very wide", "scorers": {}}
    for k, p in oof_mean.items():
        ps = p[mask]
        r = bootstrap_auc_ci(ys, ps)
        r["pr_auc"] = (round(float(average_precision_score(ys, ps)), 4)
                       if 0 < ys.sum() < len(ys) else None)
        r["brier"] = round(float(brier_score_loss(ys, ps)), 4)
        out["scorers"][k] = r
    return out


def cross_validate(df: pd.DataFrame, spec: Spec, seeds: tuple[int, ...] = SEEDS,
                   kinds: tuple[str, ...] = KINDS,
                   subsets: dict[str, np.ndarray] | None = None) -> dict:
    """Out-of-fold calibrated probabilities per repeat; metrics per repeat and mean / sd.
    GPU only (refuses without CUDA). subsets: {name: boolean row mask} reported separately."""
    device = gpu.require_cuda()
    x, y = model_table(df, spec)
    oof_sum = {k: np.zeros(len(y)) for k in kinds}
    per_repeat: dict[str, list[dict]] = {k: [] for k in kinds}
    oof_first: dict[str, np.ndarray] = {}
    fit_seconds = {k: 0.0 for k in kinds}
    for seed in seeds:
        oof = {k: np.zeros(len(y)) for k in kinds}
        folds = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=seed)
        for tr, te in folds.split(x, y):
            xtr, xte, ytr = x.iloc[tr], x.iloc[te], y[tr]
            for k in kinds:
                t0 = time.perf_counter()
                if k == "rules":
                    oof[k][te] = _platt_rules(rule_score(xtr, spec), ytr, rule_score(xte, spec))
                else:
                    est = make_estimator(k, xtr, spec, seed)
                    oof[k][te] = calibrated_fit_predict(est, xtr, ytr, xte, seed)
                fit_seconds[k] += time.perf_counter() - t0
        for k in kinds:
            p = oof[k]
            oof_sum[k] += p
            per_repeat[k].append({"seed": seed, "roc_auc": roc_auc_score(y, p),
                                  "pr_auc": average_precision_score(y, p),
                                  "brier": brier_score_loss(y, p), "ece": ece(y, p)})
            if seed == seeds[0]:
                oof_first[k] = p
    summary = {}
    for k, reps in per_repeat.items():
        r = pd.DataFrame(reps)
        summary[k] = {m: {"mean": round(float(r[m].mean()), 4),
                          "sd": round(float(r[m].std(ddof=0)), 4)}
                      for m in ("roc_auc", "pr_auc", "brier", "ece")}
        summary[k]["fit_seconds_total"] = round(fit_seconds[k], 2)
        summary[k]["calibration_seed42"] = calibration_table(y, oof_first[k])
    oof_mean = {k: v / len(seeds) for k, v in oof_sum.items()}
    for k, p in oof_mean.items():  # pooled over repeats: point ROC-AUC with a bootstrap CI
        summary[k]["roc_auc_oof_mean_ci95"] = bootstrap_auc_ci(y, p)["ci95"]
    subs = {name: subset_report(y, oof_mean, np.asarray(m, bool), name)
            for name, m in (subsets or {}).items()}
    return {"dataset": spec.name, "rows": int(len(y)), "positives": int(y.sum()),
            "base_rate": round(float(y.mean()), 4), "features": list(x.columns),
            "train_device": device, "eval_device": device, "subsets": subs,
            "dropped_protected": [c for c in spec.protected if c in df.columns],
            "rules_baseline": spec.rules, "scorers": summary,
            "evaluation": f"repeated stratified {N_FOLDS}-fold CV, seeds {list(seeds)}; "
                          "Platt calibration inside each training fold (5 inner folds); "
                          "all fits and predictions on the GPU"}
