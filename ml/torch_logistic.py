"""L2 logistic regression trained with torch on the GPU (replaces sklearn LogisticRegression).

Same model and objective as scikit-learn's default lbfgs logistic regression:
    minimise  sum_i w_i * logloss_i  +  ||coef||^2 / (2 C)     (intercept not penalised)
with w_i = 1 (class_weight=None) or n / (2 * n_class) ('balanced'); C = inf means no penalty
(used for Platt scaling). Solved in float64 with torch.optim.LBFGS (strong Wolfe line search)
on CUDA; the problem is convex, so the optimum matches scikit-learn's to solver tolerance.

During training / evaluation predict_proba also runs on the GPU. to_cpu() switches a fitted
model to numpy-only inference (coef_ and intercept_ are plain arrays), which is what gets pickled
for the servers: they need neither torch nor a GPU.
"""

from __future__ import annotations

import numpy as np


class TorchLogisticRegression:
    """Binary L2 logistic regression; sklearn-compatible fit / predict_proba / get_params."""

    def __init__(self, C: float = 1.0, max_iter: int = 1000, tol: float = 1e-10,
                 class_weight: str | None = None, fit_intercept: bool = True,
                 random_state: int | None = None) -> None:
        self.C = C
        self.max_iter = max_iter
        self.tol = tol
        self.class_weight = class_weight
        self.fit_intercept = fit_intercept
        self.random_state = random_state  # unused (deterministic solver); kept for sklearn parity

    # sklearn estimator protocol (clone / Pipeline)
    def get_params(self, deep: bool = True) -> dict:  # noqa: ARG002
        return {"C": self.C, "max_iter": self.max_iter, "tol": self.tol,
                "class_weight": self.class_weight, "fit_intercept": self.fit_intercept,
                "random_state": self.random_state}

    def set_params(self, **params) -> TorchLogisticRegression:
        for k, v in params.items():
            setattr(self, k, v)
        return self

    def __sklearn_tags__(self):
        from sklearn.utils import ClassifierTags, Tags, TargetTags

        return Tags(estimator_type="classifier", target_tags=TargetTags(required=True),
                    classifier_tags=ClassifierTags())

    def fit(self, x, y, sample_weight=None) -> TorchLogisticRegression:
        import torch

        from ml import gpu

        self.train_device_ = gpu.require_cuda()
        dev = gpu.torch_device()
        x = _dense(x)
        y = np.asarray(y).astype(float).ravel()
        self.classes_ = np.array([0, 1])
        if not set(np.unique(y)) <= {0.0, 1.0}:
            raise ValueError("binary labels 0 / 1 expected")
        w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, float)
        if self.class_weight == "balanced":
            n, pos = len(y), y.sum()
            w = w * np.where(y == 1, n / (2 * max(pos, 1)), n / (2 * max(n - pos, 1)))
        elif self.class_weight is not None:
            raise ValueError("class_weight must be None or 'balanced'")
        xt = torch.tensor(x, dtype=torch.float64, device=dev)
        yt = torch.tensor(y, dtype=torch.float64, device=dev)
        wt = torch.tensor(w, dtype=torch.float64, device=dev)
        coef = torch.zeros(x.shape[1], dtype=torch.float64, device=dev, requires_grad=True)
        b = torch.zeros(1, dtype=torch.float64, device=dev, requires_grad=self.fit_intercept)
        params = [coef, b] if self.fit_intercept else [coef]
        scale = float(wt.sum())  # objective / scale: better conditioned, same optimum
        pen = 0.0 if np.isinf(self.C) else 1.0 / (2.0 * self.C)
        opt = torch.optim.LBFGS(params, lr=1.0, max_iter=self.max_iter, history_size=20,
                                tolerance_grad=self.tol, tolerance_change=1e-14,
                                line_search_fn="strong_wolfe")

        def closure():
            opt.zero_grad()
            z = xt @ coef + b
            loss = (wt * torch.nn.functional.softplus(-(2 * yt - 1) * z)).sum()
            loss = (loss + pen * (coef * coef).sum()) / scale
            loss.backward()
            return loss

        opt.step(closure)
        self.n_iter_ = np.array([opt.state[opt._params[0]].get("n_iter", 0)])
        self.coef_ = coef.detach().cpu().numpy().reshape(1, -1)
        self.intercept_ = b.detach().cpu().numpy().reshape(1) if self.fit_intercept \
            else np.zeros(1)
        self.n_features_in_ = x.shape[1]
        self.device_ = "cuda"
        return self

    def to_cpu(self) -> TorchLogisticRegression:
        """Numpy-only inference from now on (for the pickled, deployed model)."""
        self.device_ = "cpu"
        return self

    def decision_function(self, x) -> np.ndarray:
        x = _dense(x)
        if getattr(self, "device_", "cpu") == "cuda":
            import torch

            from ml import gpu

            dev = gpu.torch_device()
            xt = torch.tensor(x, dtype=torch.float64, device=dev)
            c = torch.tensor(self.coef_[0], dtype=torch.float64, device=dev)
            return (xt @ c + float(self.intercept_[0])).cpu().numpy()
        return x @ self.coef_[0] + self.intercept_[0]

    def predict_proba(self, x) -> np.ndarray:
        p = 1.0 / (1.0 + np.exp(-self.decision_function(x)))
        return np.column_stack([1 - p, p])

    def predict(self, x) -> np.ndarray:
        return (self.decision_function(x) >= 0).astype(int)


def _dense(x) -> np.ndarray:
    if hasattr(x, "toarray"):
        x = x.toarray()
    if hasattr(x, "to_numpy"):
        x = x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def platt_fit(score: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Platt scaling p = sigmoid(a * score + b), unpenalised, fitted on the GPU."""
    m = TorchLogisticRegression(C=np.inf).fit(np.asarray(score, float).reshape(-1, 1), y)
    return float(m.coef_[0, 0]), float(m.intercept_[0])


def to_cpu_all(obj) -> None:
    """Switch every GPU-evaluating model inside a (nested) object to CPU inference: each
    TorchLogisticRegression and any other object with a to_cpu() method (XGBoost scorers)."""
    seen: set[int] = set()

    def walk(o) -> None:
        if id(o) in seen or o is None or isinstance(o, str | int | float | bool | np.ndarray):
            return
        seen.add(id(o))
        if isinstance(o, TorchLogisticRegression):
            o.to_cpu()
            return
        if callable(getattr(o, "to_cpu", None)) and not isinstance(o, type):
            o.to_cpu()
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list | tuple | set):
            for v in o:
                walk(v)
        elif hasattr(o, "steps"):
            for _, s in o.steps:
                walk(s)
        elif hasattr(o, "__dict__"):
            for v in vars(o).values():
                walk(v)

    walk(obj)
