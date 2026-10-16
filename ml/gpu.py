"""GPU-only training: the one helper every model training entry point uses.

    from ml import gpu
    device = gpu.require_cuda()          # refuses to go on without CUDA (no CPU fallback)
    XGBRegressor(**gpu.XGB_DEVICE, ...)  # XGBoost on the GPU
    metrics["train_device"] = device     # "cuda:0 NVIDIA GeForce RTX 4050 Laptop GPU"

require_cuda() checks BOTH torch.cuda.is_available() and a tiny XGBoost fit on device="cuda"
(the booster's own config must say it ran on cuda). If either fails it raises GPURequiredError
with the reason: training never falls back to the CPU. Prediction (inference) is NOT covered:
the deployed artifacts are evaluated on the CPU (ml/xgb_trees.py, numpy) on the servers.

torch and xgboost are optional dependencies (ml/realdata/requirements-gpu.txt); they are
imported only inside these functions, so the API servers never need them.
"""

from __future__ import annotations

import json
import warnings
from functools import lru_cache

XGB_DEVICE = {"device": "cuda", "tree_method": "hist"}


class GPURequiredError(RuntimeError):
    """Training was asked for without a usable CUDA GPU."""


@lru_cache(maxsize=1)
def require_cuda() -> str:
    """'cuda:0 <device name>' when torch AND XGBoost can use the GPU; otherwise GPURequiredError."""
    try:
        import torch
    except ImportError as e:
        raise GPURequiredError("Training needs the GPU: torch (CUDA build) is not installed; see "
                               "ml/realdata/requirements-gpu.txt. No CPU fallback.") from e
    try:
        ok = torch.cuda.is_available() and torch.cuda.device_count() > 0
        name = f"cuda:{torch.cuda.current_device()} {torch.cuda.get_device_name(0)}" if ok else ""
    except (AssertionError, RuntimeError):  # e.g. no visible device
        ok, name = False, ""
    if not ok:
        raise GPURequiredError("Training needs the GPU: torch.cuda.is_available() is False "
                               f"(torch {torch.__version__}, CUDA runtime "
                               f"{torch.version.cuda}). No CPU fallback.")
    try:
        import numpy as np
        import xgboost as xgb
    except ImportError as e:
        raise GPURequiredError("Training needs the GPU: xgboost is not installed; see "
                               "ml/realdata/requirements-gpu.txt. No CPU fallback.") from e
    try:
        x = np.arange(16, dtype=float).reshape(8, 2)
        m = xgb.XGBRegressor(n_estimators=2, max_depth=2, **XGB_DEVICE).fit(x, x[:, 0])
        assert_xgb_on_cuda(m)
    except GPURequiredError:
        raise
    except Exception as e:  # noqa: BLE001 - any XGBoost / CUDA failure means: no GPU training
        raise GPURequiredError(f"Training needs the GPU: the XGBoost CUDA test fit failed "
                               f"({type(e).__name__}: {e}). No CPU fallback.") from e
    # Evaluation feeds host (CPU) arrays to a CUDA booster: XGBoost copies them to the GPU and
    # predicts there, with a one-off "mismatched devices" warning that is expected here.
    warnings.filterwarnings("ignore", message=".*Falling back to prediction using DMatrix.*")
    return name


def assert_xgb_on_cuda(model) -> None:
    """The fitted XGBoost model's own config must report a CUDA device."""
    booster = model.get_booster() if hasattr(model, "get_booster") else model
    dev = json.loads(booster.save_config())["learner"]["generic_param"].get("device", "")
    if not str(dev).startswith("cuda"):
        raise GPURequiredError(f"XGBoost trained on {dev!r}, not on the GPU")


def torch_device():
    """The CUDA torch device (after require_cuda)."""
    import torch

    require_cuda()
    return torch.device("cuda:0")


def peak_torch_memory_mib() -> float:
    import torch

    return round(torch.cuda.max_memory_allocated() / 2**20, 1)
