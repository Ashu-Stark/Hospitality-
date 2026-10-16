"""XGBoost L1 regressor on the GPU for the pulse and workload models (SYNTHETIC data).

Replaces the earlier LightGBM L1 regressor with the same settings mapped one to one:
leaf-wise growth with at most 8 leaves (LightGBM num_leaves=8 -> grow_policy lossguide,
max_leaves 8), minimum leaf size (min_child_samples -> min_child_weight; the absolute-error
hessian is 1 per row), L2 lambda 5, row / column subsampling 0.8, learning rate 0.03, up to
3,000 rounds with early stopping on validation MAE (50 rounds). Trained and evaluated on CUDA;
the saved model is the numpy TreeEnsemble (CPU inference on the servers).

Minimum leaf size: with LightGBM's sizes (30 workload / 100 pulse) the GPU model was worse on
VALIDATION (workload 0.0640 vs LightGBM 0.0611), so a small grid was searched on the validation
split only (max_leaves 8/16/31 x min_child_weight 10/30/100 x lambda 1/5, early stopping on
validation): 8 leaves, min_child_weight 10, lambda 5 had the lowest validation MAE for BOTH
models (workload 0.0604, pulse 0.2447). The test split was not used to choose.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml import gpu
from ml.xgb_trees import TreeEnsemble, total_gain

EARLY_STOPPING_ROUNDS = 50
MIN_LEAF = 10  # chosen on validation (see above)


def fit_l1(xt_train: pd.DataFrame, y_train: np.ndarray, xt_val: pd.DataFrame, y_val: np.ndarray,
           random_state: int, min_leaf: int):
    """-> (fitted XGBRegressor on cuda, exported TreeEnsemble, gain importance)."""
    import xgboost as xgb

    gpu.require_cuda()
    reg = xgb.XGBRegressor(
        objective="reg:absoluteerror", n_estimators=3000, learning_rate=0.03,
        grow_policy="lossguide", max_leaves=8, max_depth=0, min_child_weight=min_leaf,
        reg_lambda=5.0, subsample=0.8, colsample_bytree=0.8, random_state=random_state,
        early_stopping_rounds=EARLY_STOPPING_ROUNDS, eval_metric="mae", **gpu.XGB_DEVICE)
    reg.fit(xt_train, y_train, eval_set=[(xt_val, y_val)], verbose=False)
    gpu.assert_xgb_on_cuda(reg)
    ens = TreeEnsemble.from_xgb(reg, xt_train)
    return reg, ens, total_gain(reg, list(xt_train.columns))
