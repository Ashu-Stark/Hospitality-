"""Google TimesFM 2.5 (200M, Apache-2.0, google/timesfm-2.5-200m-pytorch) on the REAL hotel
series: zero-shot forecasts and a light fine-tune, on the GPU when available.

Zero-shot: univariate; the context is every observed night up to the origin (max 1024).
Fine-tune: only the LAST `n_layers` transformer layers plus both output heads are trained
(the rest is frozen), with a pinball (quantile) loss on the next 30 nights, on windows whose
targets all fall in the TRAIN period. The epoch with the lowest validation MAE (validation
window, see forecast.Split) is kept. Inference after fine-tuning uses exactly the same
library decode path as zero-shot. `train_forward` re-implements that path WITH gradients for
horizons <= 128 (one output patch); `check_forward_matches` verifies it against the library.

Needs: torch, timesfm 2.5 (installed from github.com/google-research/timesfm), model weights
from the Hugging Face cache. Imported lazily so tests and the rest of ml/ never need them.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

MODEL_ID = "google/timesfm-2.5-200m-pytorch"
MAX_CONTEXT, MAX_HORIZON = 1024, 128
QUANTILES = np.arange(1, 10) / 10  # output channels 1..9; channel 5 = median = point forecast
Q_LO, Q_HI = 1, 9  # 10% / 90% -> 80% band


def load_model(max_context: int = MAX_CONTEXT):
    import timesfm
    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(MODEL_ID)
    compile_model(model, max_context)
    return model


def compile_model(model, max_context: int = MAX_CONTEXT) -> None:
    import timesfm
    model.compile(timesfm.ForecastConfig(
        max_context=max_context, max_horizon=MAX_HORIZON, normalize_inputs=True,
        use_continuous_quantile_head=True, force_flip_invariance=True, infer_is_positive=True,
        fix_quantile_crossing=True, per_core_batch_size=64))


def forecast_origins(model, series: pd.Series, origins: pd.DatetimeIndex, horizon: int
                     ) -> np.ndarray:
    """(len(origins), horizon, 10) forecasts; row i uses nights up to and including origins[i]."""
    s = series.dropna()
    ctx = [s[s.index <= t].to_numpy(dtype=np.float32) for t in origins]
    _, q = model.forecast(horizon=horizon, inputs=ctx)
    return np.asarray(q)


# ---- fine-tuning -----------------------------------------------------------------------

def _decode_last_patch(module, inputs, masks):
    """The library's prefill (no KV cache) with gradients: (B, 128, 10) forecasts in the
    globally normalised space, plus the continuous-quantile spread (B, 1024, 10)."""
    import torch
    from timesfm.torch.util import revin, update_running_stats
    b = inputs.shape[0]
    p = module.p
    pi = inputs.reshape(b, -1, p)
    pm = masks.reshape(b, -1, p)
    n = torch.zeros(b, device=inputs.device)
    mu = torch.zeros(b, device=inputs.device)
    sigma = torch.zeros(b, device=inputs.device)
    mus, sigmas = [], []
    for i in range(pi.shape[1]):
        (n, mu, sigma), _ = update_running_stats(n, mu, sigma, pi[:, i], pm[:, i])
        mus.append(mu)
        sigmas.append(sigma)
    cmu, csig = torch.stack(mus, 1), torch.stack(sigmas, 1)
    normed = torch.where(pm, 0.0, revin(pi, cmu, csig, reverse=False))
    (_, _, out, spread), _ = module(normed, pm, None)
    out = revin(out, cmu, csig, reverse=True).reshape(b, -1, module.o, module.q)[:, -1]
    spread = revin(spread, cmu, csig, reverse=True).reshape(b, -1, module.os, module.q)[:, -1]
    return out, spread


def train_forward(module, values, masks, horizon: int):
    """Differentiable version of the compiled decode used by model.forecast (horizon <= 128):
    global normalisation, flip invariance, continuous quantile head. Returns (B, horizon, 10)
    in ORIGINAL units, plus the global mean / std used."""
    import torch
    from timesfm.torch.util import revin
    mu = values.mean(dim=-1, keepdim=True)
    sd = values.std(dim=-1, keepdim=True)
    x = revin(values, mu, sd, reverse=False)
    out, spread = _decode_last_patch(module, x, masks)
    f_out, f_spread = _decode_last_patch(module, -x, masks)

    def flip(t):
        return torch.cat([t[..., :1], torch.flip(t[..., 1:], dims=(-1,))], dim=-1)

    out = (out - flip(f_out)) / 2
    spread = (spread - flip(f_spread)) / 2
    q = out[:, :horizon].clone()
    med = out[:, :horizon, 5]
    qs = [1, 2, 3, 4, 6, 7, 8, 9]
    q[:, :, qs] = spread[:, :horizon, qs] - spread[:, :horizon, 5:6] + med[..., None]
    return revin(q, mu, sd, reverse=True), mu, sd


def _pad(ctx: np.ndarray, length: int) -> tuple[np.ndarray, np.ndarray]:
    ctx = ctx[-length:]
    pad = length - len(ctx)
    return (np.concatenate([np.zeros(pad, np.float32), ctx]).astype(np.float32),
            np.concatenate([np.ones(pad, bool), np.zeros(len(ctx), bool)]))


def check_forward_matches(model, series: pd.Series, origin: pd.Timestamp, horizon: int,
                          context: int) -> float:
    """Max |library forecast - train_forward| on one context (should be ~0)."""
    import torch
    s = series.dropna()
    ctx = s[s.index <= origin].to_numpy(np.float32)
    compile_model(model, context)
    _, lib = model.forecast(horizon=horizon, inputs=[ctx])
    v, m = _pad(ctx, context)
    dev = model.model.device
    with torch.no_grad():
        mine, _, _ = train_forward(model.model, torch.tensor(v[None], device=dev),
                                   torch.tensor(m[None], device=dev), horizon)
    mine = np.maximum(mine.cpu().numpy(), 0)
    return float(np.max(np.abs(np.asarray(lib)[0, :, 1:] - mine[0, :, 1:])))


@dataclass
class FineTuneConfig:
    n_layers: int = 4          # last transformer layers trained; the rest stay frozen
    context: int = 512         # training context (nights), multiple of 32
    horizon: int = 30
    lr: float = 1e-5
    weight_decay: float = 0.01
    batch_size: int = 16
    epochs: int = 8
    min_context: int = 64      # windows need at least this many observed nights
    seed: int = 42


def make_windows(series: dict[str, pd.Series], first_origin_target: pd.Timestamp | None,
                 last_target: pd.Timestamp, cfg: FineTuneConfig,
                 first_target: pd.Timestamp | None = None
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """All (context, next-30-nights) windows whose targets lie in [first_target, last_target]."""
    vals, masks, ys = [], [], []
    for s in series.values():
        s = s.dropna()
        arr = s.to_numpy(np.float32)
        dates = s.index
        for i in range(cfg.min_context, len(arr) - cfg.horizon + 1):
            t_first, t_last = dates[i], dates[i + cfg.horizon - 1]
            if t_last > last_target or (first_target is not None and t_first < first_target):
                continue
            v, m = _pad(arr[:i], cfg.context)
            vals.append(v)
            masks.append(m)
            ys.append(arr[i:i + cfg.horizon])
    return np.stack(vals), np.stack(masks), np.stack(ys)


def pinball(pred, y):
    """Mean pinball loss over the 9 quantile channels; pred (B, H, 10), y (B, H)."""
    import torch
    q = torch.tensor(QUANTILES, dtype=pred.dtype, device=pred.device)
    err = y[..., None] - pred[..., 1:]
    return torch.mean(torch.maximum(q * err, (q - 1) * err))


def fine_tune(model, train: tuple, val: tuple, cfg: FineTuneConfig, log=print) -> dict:
    """Fine-tune in place on the model's device; keeps the best-validation-MAE weights.
    Losses are computed on series scaled by each window's own context mean, so both hotels
    weigh the same."""
    import torch
    torch.manual_seed(cfg.seed)
    module = model.model
    dev = module.device
    for p in module.parameters():
        p.requires_grad_(False)
    trainable = list(module.stacked_xf[-cfg.n_layers:]) + [
        module.output_projection_point, module.output_projection_quantiles]
    params = [p for m in trainable for p in m.parameters()]
    for p in params:
        p.requires_grad_(True)
    n_train = sum(p.numel() for p in params)
    n_total = sum(p.numel() for p in module.parameters())
    opt = torch.optim.AdamW(params, lr=cfg.lr, weight_decay=cfg.weight_decay)
    tv, tm, ty = (torch.tensor(a, device=dev) for a in train)
    vv, vm, vy = (torch.tensor(a, device=dev) for a in val)

    def scaled(v, m, y):
        scale = (v * (~m)).sum(-1, keepdim=True) / (~m).sum(-1, keepdim=True).clamp(min=1)
        scale = scale.clamp(min=1.0)
        return v / scale, y / scale, scale

    def val_mae() -> float:
        module.eval()
        errs = []
        with torch.no_grad():
            for i in range(0, len(vv), 64):
                v, y, sc = scaled(vv[i:i + 64], vm[i:i + 64], vy[i:i + 64])
                out, _, _ = train_forward(module, v, vm[i:i + 64], cfg.horizon)
                errs.append(torch.abs(torch.clamp(out[..., 5], min=0) * sc - y * sc))
        return float(torch.cat(errs).mean())

    gen = torch.Generator(device="cpu").manual_seed(cfg.seed)
    history = [{"epoch": 0, "val_mae": round(val_mae(), 3), "train_loss": None}]
    best = (history[0]["val_mae"], 0, copy.deepcopy([p.detach().clone() for p in params]))
    log(f"  fine-tune: {n_train / 1e6:.1f}M of {n_total / 1e6:.1f}M parameters trainable, "
        f"{len(tv)} train windows, {len(vv)} validation windows, device {dev}")
    log(f"  epoch 0 (zero-shot) validation MAE {history[0]['val_mae']:.3f} room-nights")
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    for epoch in range(1, cfg.epochs + 1):
        module.train()
        order = torch.randperm(len(tv), generator=gen)
        losses = []
        for i in range(0, len(order), cfg.batch_size):
            b = order[i:i + cfg.batch_size].to(dev)
            v, y, _ = scaled(tv[b], tm[b], ty[b])
            out, _, _ = train_forward(module, v, tm[b], cfg.horizon)
            loss = pinball(out, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            losses.append(float(loss.detach()))
        vm_ = val_mae()
        history.append({"epoch": epoch, "val_mae": round(vm_, 3),
                        "train_loss": round(float(np.mean(losses)), 5)})
        log(f"  epoch {epoch} train pinball {np.mean(losses):.4f}  validation MAE {vm_:.3f}")
        if vm_ < best[0]:
            best = (vm_, epoch, copy.deepcopy([p.detach().clone() for p in params]))
    seconds = time.perf_counter() - t0
    with torch.no_grad():
        for p, w in zip(params, best[2], strict=True):
            p.copy_(w)
    module.eval()
    peak = torch.cuda.max_memory_allocated() / 2**30 if dev.type == "cuda" else None
    return {"best_epoch": best[1], "best_val_mae": round(best[0], 3), "history": history,
            "trainable_params": n_train, "total_params": n_total, "seconds": round(seconds, 1),
            "device": str(dev), "peak_gpu_memory_gb": round(peak, 2) if peak else None,
            "config": cfg.__dict__}


def trainable_state(model, n_layers: int) -> dict:
    """State dict of only the fine-tuned parts (to save a small artifact)."""
    module = model.model
    keep = {f"stacked_xf.{i}." for i in range(module.x - n_layers, module.x)}
    keep |= {"output_projection_point.", "output_projection_quantiles."}
    return {k: v.detach().cpu() for k, v in module.state_dict().items()
            if any(k.startswith(p) for p in keep)}
