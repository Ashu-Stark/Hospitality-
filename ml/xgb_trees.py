"""CPU inference for XGBoost models trained on the GPU, with numpy only (no xgboost needed).

Training runs on CUDA (ml/gpu.py); the servers (Render, 512 MB, no GPU) only predict. A fitted
XGBoost model is exported ONCE at training time into plain arrays (TreeEnsemble.from_xgb):
per tree the children, split feature, split threshold, default direction for missing values
and leaf values, plus the constant base margin. The arrays are pickled into model.joblib.

XGBoost semantics reproduced: features are compared in float32; `x < threshold` goes left;
NaN goes the node's default direction; output = base margin + sum of leaves (identity for
regression, sigmoid for binary:logistic). from_xgb() checks the export against XGBoost's own
predictions on the training rows and refuses a mismatch.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd


class TreeEnsemble:
    """An exported XGBoost booster. predict() for regression, predict_proba() for binary."""

    def __init__(self, trees: list[dict[str, np.ndarray]], base_margin: float,
                 feature_names: list[str], objective: str, params: dict | None = None) -> None:
        self.trees_ = trees
        self.base_margin_ = float(base_margin)
        self.feature_names_in_ = np.asarray(feature_names, dtype=object)
        self.n_features_in_ = len(feature_names)
        self.objective = objective
        self.params = dict(params or {})
        self.classes_ = np.array([0, 1]) if objective.startswith("binary:") else None

    # ---- sklearn-style surface (so a Pipeline can end in a TreeEnsemble) -----------------
    def get_params(self, deep: bool = True) -> dict:  # noqa: ARG002
        return {}

    def __sklearn_is_fitted__(self) -> bool:
        return True

    def __sklearn_tags__(self):
        from sklearn.utils import ClassifierTags, RegressorTags, Tags, TargetTags

        binary = self.objective.startswith("binary:")
        return Tags(estimator_type="classifier" if binary else "regressor",
                    target_tags=TargetTags(required=True),
                    classifier_tags=ClassifierTags() if binary else None,
                    regressor_tags=None if binary else RegressorTags())

    def fit(self, *_args, **_kwargs):  # pragma: no cover - export only, never trained here
        raise TypeError("TreeEnsemble is an exported model: train with XGBoost on the GPU")

    # ---- export ----------------------------------------------------------------------------
    @classmethod
    def from_xgb(cls, model, check_x: pd.DataFrame | np.ndarray | None = None,
                 tol: float = 1e-4) -> TreeEnsemble:
        """Export a fitted XGBRegressor / XGBClassifier (its best iteration when early stopping
        was used). With check_x, the export must reproduce XGBoost's margins on those rows."""
        import xgboost as xgb

        booster = model.get_booster() if hasattr(model, "get_booster") else model
        best = getattr(model, "best_iteration", None)
        if best is not None and getattr(model, "early_stopping_rounds", None):
            booster = booster[: best + 1]
        raw = json.loads(booster.save_raw("json"))
        learner = raw["learner"]
        objective = learner["objective"]["name"]
        names = booster.feature_names or [f"f{i}" for i in range(booster.num_features())]
        trees = []
        for t in learner["gradient_booster"]["model"]["trees"]:
            left = np.asarray(t["left_children"], dtype=np.int32)
            trees.append({
                "left": left,
                "right": np.asarray(t["right_children"], dtype=np.int32),
                "feature": np.asarray(t["split_indices"], dtype=np.int32),
                "threshold": np.asarray(t["split_conditions"], dtype=np.float32),
                "default_left": np.asarray(t["default_left"], dtype=bool),
                "leaf": np.where(left == -1, np.asarray(t["split_conditions"], np.float32),
                                 0).astype(np.float32),
            })
        params = {k: v for k, v in (model.get_params() if hasattr(model, "get_params")
                                    else {}).items() if isinstance(v, int | float | str)}
        ens = cls(trees, 0.0, list(names), objective, params)
        ref_x = check_x if check_x is not None else None
        if ref_x is None:
            raise ValueError("from_xgb needs check_x (rows to verify the export on)")
        dm = xgb.DMatrix(ens._array(ref_x), feature_names=list(names))
        margin = booster.predict(dm, output_margin=True)
        offset = margin - ens._sum_leaves(ens._array(ref_x))
        ens.base_margin_ = float(np.median(offset))
        err = float(np.max(np.abs(offset - ens.base_margin_)))
        if err > tol:
            raise ValueError(f"exported trees differ from XGBoost by {err:.2e} (> {tol})")
        ens.export_check_max_abs_diff_ = err
        ens.xgb_json_ = bytes(booster.save_raw("json"))  # to re-load on the GPU for evaluation
        return ens

    def gpu_booster(self):
        """The same model as an XGBoost booster on CUDA (evaluation runs on the GPU)."""
        import xgboost as xgb

        from ml import gpu

        gpu.require_cuda()
        b = getattr(self, "_gpu_booster", None)
        if b is None:
            b = xgb.Booster(model_file=bytearray(self.xgb_json_))
            b.set_param({"device": "cuda"})
            self._gpu_booster = b
        return b

    def __getstate__(self) -> dict:
        state = dict(self.__dict__)
        state.pop("_gpu_booster", None)
        return state

    # ---- prediction ------------------------------------------------------------------------
    def _array(self, x) -> np.ndarray:
        if isinstance(x, pd.DataFrame):
            names = list(self.feature_names_in_)
            if all(n in x.columns for n in names):
                x = x[names]
            x = x.to_numpy(dtype=float)
        return np.asarray(x, dtype=np.float32)

    def _sum_leaves(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        rows = np.arange(n)
        out = np.zeros(n, dtype=np.float64)
        for t in self.trees_:
            node = np.zeros(n, dtype=np.int32)
            while True:
                inner = t["left"][node] != -1
                if not inner.any():
                    break
                r, nd = rows[inner], node[inner]
                v = x[r, t["feature"][nd]]
                go_left = np.where(np.isnan(v), t["default_left"][nd], v < t["threshold"][nd])
                node[inner] = np.where(go_left, t["left"][nd], t["right"][nd])
            out += t["leaf"][node]
        return out

    def margin(self, x) -> np.ndarray:
        return self.base_margin_ + self._sum_leaves(self._array(x))

    def predict(self, x) -> np.ndarray:
        m = self.margin(x)
        if self.objective.startswith("binary:"):
            return (m >= 0).astype(int)
        return m

    def predict_proba(self, x) -> np.ndarray:
        if not self.objective.startswith("binary:"):
            raise TypeError(f"predict_proba needs a binary model, not {self.objective}")
        p = 1.0 / (1.0 + np.exp(-self.margin(x)))
        return np.column_stack([1 - p, p])

    @property
    def n_trees(self) -> int:
        return len(self.trees_)


def predict_gpu(model, x, proba: bool = False) -> np.ndarray:
    """Evaluation-time prediction ON THE GPU for a TreeEnsemble, or a Pipeline ending in one
    (preprocessing steps run first). Returns P(class 1) when proba=True."""
    import xgboost as xgb

    if hasattr(model, "steps"):
        for _, step in model.steps[:-1]:
            x = step.transform(x)
        model = model.steps[-1][1]
    arr = model._array(x)
    dm = xgb.DMatrix(arr, feature_names=list(model.feature_names_in_))
    out = model.gpu_booster().predict(dm)
    return np.asarray(out, dtype=float) if proba or not model.objective.startswith(
        "binary:") else (np.asarray(out) >= 0.5).astype(int)


def total_gain(model, names: list[str]) -> pd.Series:
    """XGBoost total-gain importance per feature (0 for unused features), largest first."""
    booster = model.get_booster() if hasattr(model, "get_booster") else model
    score = booster.get_score(importance_type="total_gain")
    return pd.Series({n: float(score.get(n, 0.0)) for n in names}).sort_values(ascending=False)
