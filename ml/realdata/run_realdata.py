"""Reproduce every REAL-data result: python run.py realdata [--no-timesfm]

GPU ONLY: ml/gpu.py refuses to run without CUDA; every fit and every evaluation prediction runs
on the GPU (there is no CPU mode and no CPU timing comparison any more).
1. downloads (or re-verifies by SHA-256) the public datasets in sources.py
2. occupancy: seasonal-naive / pickup baselines, XGBoost (calendar and pace features, GPU),
   TimesFM 2.5 zero-shot and fine-tuned (GPU) at horizons 1 / 7 / 30, time split in
   forecast.Split
3. attrition: rules vs logistic (torch, GPU) vs XGBoost (GPU) on public datasets
   (ml/realdata/attrition.py; the rating is in ml/realdata/attrition/VALIDATION.md)
4. GPU evidence: device, nvidia-smi before / during / after, GPU timings
Writes ml/artifacts/{occupancy_forecast,attrition,realdata_gpu}/real_v1/ and the
test-period plot ml/docs/plots/realdata_forecast.png. Seeded (42); the model choice per
horizon is made on the VALIDATION window, never on the test window.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.gpu import require_cuda
from ml.realdata import attrition as attr
from ml.realdata import forecast as fc
from ml.realdata import gpu, hotels, sources

ML_ROOT = Path(__file__).resolve().parents[1]
ART = ML_ROOT / "artifacts"
OCC_DIR = ART / "occupancy_forecast" / "real_v1"
ATTR_DIR = ART / "attrition" / "real_v1"
GPU_DIR = ART / "realdata_gpu" / "real_v1"
FT_DIR = ML_ROOT / "data" / "realdata" / "timesfm_finetuned"  # gitignored (~330 MB)
PLOT = ML_ROOT / "docs" / "plots" / "realdata_forecast.png"
SEED = 42
LOG: list[str] = []


def log(msg: str = "") -> None:
    print(msg, flush=True)
    LOG.append(msg)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")


# ---- occupancy ---------------------------------------------------------------------------

def tree_and_baselines(daily, otbs, caps) -> tuple[list[dict], dict, dict]:
    rows, preds, models = [], {}, {}
    for h in fc.HORIZONS:
        parts = fc.split_frame(fc.build_frame(daily, otbs[h], h, caps))
        tr, va, te = parts["train"], parts["val"], parts["test"]
        log(f"  h={h}: train {len(tr)} rows ({tr.index.min().date()}..{tr.index.max().date()}),"
            f" val {len(va)}, test {len(te)} ({te.index.min().date()}..{te.index.max().date()})")
        cands = {}
        for name in ("snaive_week", "snaive_year", "pickup_naive"):
            cands[name] = (va[name].to_numpy(float), te[name].to_numpy(float), "baseline")
        for kind, feats_kind, fit in (
                ("xgb_calendar_gpu", "calendar", lambda x, y: fc.fit_xgb(x, y, SEED)),
                ("xgb_pace_gpu", "pace", lambda x, y: fc.fit_xgb(x, y, SEED))):
            feats = fc.features(feats_kind)
            t0 = time.perf_counter()
            m = fit(tr[feats], tr[fc.TARGET])
            secs = time.perf_counter() - t0
            cap_v, cap_t = va["capacity"].to_numpy(), te["capacity"].to_numpy()
            cands[kind] = (m.predict(va[feats]) * cap_v, m.predict(te[feats]) * cap_t, "model")
            models[(h, kind)] = {"model": m, "features": feats, "fit_seconds": round(secs, 3)}
        for name, (pv, pt, group) in cands.items():
            p, lo, hi = fc.evaluate_point_model(parts, pv, pt)
            val_mae = fc.mae(va["y_true"].to_numpy()[~np.isnan(pv)], pv[~np.isnan(pv)])
            for r in fc.score_rows(te, p, lo, hi):
                rows.append({"horizon": h, "model": name, "group": group,
                             "val_mae_room_nights": round(val_mae, 2), **r})
            preds[(h, name)] = pd.DataFrame({"hotel": te["hotel"], "actual": te["y_true"],
                                             "pred": p, "lo": lo, "hi": hi}, index=te.index)
    return rows, preds, models


def timesfm_block(daily, out_rows, preds, evidence) -> dict:
    import torch

    from ml.realdata import tfm
    torch.manual_seed(SEED)
    t0 = time.perf_counter()
    model = tfm.load_model()
    log(f"  TimesFM 2.5 loaded in {time.perf_counter() - t0:.1f}s on {model.model.device}")
    if not str(model.model.device).startswith("cuda"):
        raise RuntimeError(f"TimesFM loaded on {model.model.device}, not on the GPU")
    evidence["timesfm_device"] = str(model.model.device)
    err = tfm.check_forward_matches(model, daily["City Hotel"], pd.Timestamp("2017-02-28"),
                                    30, 512)
    tfm.compile_model(model)
    log(f"  differentiable forward vs library forecast: max abs diff {err:.2e} room-nights")
    s = fc.SPLIT
    val_d = pd.date_range(s.val_start, s.val_end)
    test_d = pd.date_range(s.test_start, s.test_end)
    out = {"forward_check_max_abs_diff": err}

    def run(label: str) -> None:
        val_res = {}
        for h in fc.HORIZONS:
            per = []
            for part, dates in (("val", val_d), ("test", test_d)):
                for hotel in hotels.HOTELS:
                    origins = dates - pd.Timedelta(days=h)
                    q = tfm.forecast_origins(model, daily[hotel], origins, h)[:, h - 1, :]
                    per.append(pd.DataFrame({
                        "part": part, "hotel": hotel, "actual": daily[hotel].reindex(dates).values,
                        "pred": q[:, 5], "lo": q[:, tfm.Q_LO], "hi": q[:, tfm.Q_HI],
                        "capacity": fc.capacities(daily)[hotel]}, index=dates))
            df = pd.concat(per)
            va, te = df[df.part == "val"], df[df.part == "test"]
            val_res[h] = fc.mae(va["actual"], va["pred"])
            te_rows = te.rename(columns={"actual": "y_true"})
            for r in fc.score_rows(te_rows, te["pred"].to_numpy(), te["lo"].to_numpy(),
                                   te["hi"].to_numpy()):
                out_rows.append({"horizon": h, "model": label, "group": "model",
                                 "val_mae_room_nights": round(val_res[h], 2), **r})
            preds[(h, label)] = te[["hotel", "actual", "pred", "lo", "hi"]]
        out[label] = {"val_mae": {h: round(v, 2) for h, v in val_res.items()}}

    t0 = time.perf_counter()
    run("timesfm_zero_shot")
    out["zero_shot_seconds"] = round(time.perf_counter() - t0, 1)
    log(f"  zero-shot: {out['zero_shot_seconds']}s for val + test, 3 horizons, 2 hotels")

    cfg = tfm.FineTuneConfig(seed=SEED)
    series = {h: daily[h] for h in hotels.HOTELS}
    train_w = tfm.make_windows(series, None, pd.Timestamp(s.train_end), cfg)
    val_w = tfm.make_windows(series, None, pd.Timestamp(s.val_end), cfg,
                             first_target=pd.Timestamp(s.val_start))
    with gpu.SmiSampler(every=2.0) as smp:
        ft = tfm.fine_tune(model, train_w, val_w, cfg, log=log)
    ft["nvidia_smi_during_fine_tune"] = smp.peak()
    log(f"  fine-tune: best epoch {ft['best_epoch']} (val MAE {ft['best_val_mae']}), "
        f"{ft['seconds']}s on {ft['device']}, peak torch memory {ft['peak_gpu_memory_gb']} GB, "
        f"nvidia-smi peak {ft['nvidia_smi_during_fine_tune']}")
    out["fine_tune"] = ft
    if ft["best_epoch"] > 0:
        tfm.compile_model(model)
        run("timesfm_fine_tuned")
        _save_ft(model, cfg, out)
    else:
        log("  fine-tune never beat zero-shot on validation: zero-shot weights kept, "
            "no fine-tuned rows reported")
    out["timings"] = timesfm_timings(model, daily, cfg, train_w)
    return out


def _save_ft(model, cfg, out) -> None:
    from safetensors.torch import save_file

    from ml.realdata import tfm
    FT_DIR.mkdir(parents=True, exist_ok=True)
    path = FT_DIR / "finetuned_layers.safetensors"
    save_file({k: v.contiguous() for k, v in tfm.trainable_state(model, cfg.n_layers).items()},
              str(path))
    out["fine_tuned_weights"] = {"path": str(path.relative_to(ML_ROOT)),
                                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                 "note": "only the fine-tuned layers; gitignored, re-created by "
                                         "python run.py realdata"}


def timesfm_timings(model, daily, cfg, train_w) -> dict:
    """TimesFM on the GPU: inference of 64 contexts, and 3 fine-tune steps (timing only)."""
    import torch

    from ml.realdata import tfm
    origins = pd.date_range("2017-01-01", periods=64)
    res = {}
    tfm.compile_model(model)
    torch.cuda.synchronize()
    res["inference_64_contexts_cuda_s"] = gpu.timed(
        lambda: tfm.forecast_origins(model, daily["City Hotel"], origins, 30), repeats=2)
    v, m, y = (torch.tensor(a[:8], device="cuda") for a in train_w)
    params = [p for p in model.model.parameters() if p.requires_grad] or list(
        model.model.output_projection_point.parameters())
    for p in params:
        p.requires_grad_(True)
    opt = torch.optim.SGD(params, lr=0.0)  # lr 0: timing only, weights unchanged

    def steps():
        for _ in range(3):
            out, _, _ = tfm.train_forward(model.model, v, m, cfg.horizon)
            loss = tfm.pinball(out, y)
            opt.zero_grad()
            loss.backward()
            opt.step()
        torch.cuda.synchronize()
    res["fine_tune_3_steps_batch8_cuda_s"] = gpu.timed(steps)
    log(f"  TimesFM timings (GPU): {res}")
    return res


def xgb_timings(daily, otbs, caps) -> dict:
    """XGBoost GPU fit time on the h=7 frame (small) and on a 100x row-replicated copy."""
    parts = fc.split_frame(fc.build_frame(daily, otbs[7], 7, caps))
    tr = parts["train"]
    feats = fc.features("pace")
    big = pd.concat([tr] * 100)
    res = {"rows_small": len(tr), "rows_large": len(big)}
    fc.fit_xgb(tr[feats], tr[fc.TARGET], SEED)  # warm-up
    res["xgb_fit_small_cuda_s"] = gpu.timed(
        lambda: fc.fit_xgb(tr[feats], tr[fc.TARGET], SEED), repeats=3)
    res["xgb_fit_large_cuda_s"] = gpu.timed(lambda: fc.fit_xgb(big[feats], big[fc.TARGET], SEED))
    log(f"  XGBoost timings (GPU): {res}")
    return res


def choose_best(rows: pd.DataFrame) -> pd.DataFrame:
    """Per horizon: the model with the lowest VALIDATION MAE (pooled over hotels)."""
    pooled = rows.groupby(["horizon", "model"])["val_mae_room_nights"].mean().reset_index()
    return pooled.loc[pooled.groupby("horizon")["val_mae_room_nights"].idxmin()]


def results_markdown(rows: pd.DataFrame, best: pd.DataFrame) -> str:
    lines = ["| Horizon | Hotel | Model | MAPE | MAE (room-nights) | Typical error | "
             "80% band coverage | Val MAE |", "|---|---|---|---|---|---|---|---|"]
    for _, r in rows.sort_values(["horizon", "hotel", "mae_room_nights"]).iterrows():
        star = " **(chosen on validation)**" if (
            (best["horizon"] == r["horizon"]) & (best["model"] == r["model"])).any() else ""
        lines.append(f"| {r['horizon']}d | {r['hotel']} | {r['model']}{star} | "
                     f"{r['mape'] * 100:.1f}% | {r['mae_room_nights']:.1f} | "
                     f"{r['median_abs_error_room_nights']:.1f} | "
                     f"{r['coverage_80'] * 100:.0f}% | {r['val_mae_room_nights']:.1f} |")
    return "\n".join(lines) + "\n"


def save_plot(preds: dict, best: pd.DataFrame, h: int = 7, path: Path = PLOT) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    name = best.loc[best["horizon"] == h, "model"].iloc[0]
    p, base = preds[(h, name)], preds[(h, "snaive_week")]
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for ax, hotel in zip(axes, hotels.HOTELS, strict=True):
        g, b = p[p["hotel"] == hotel], base[base["hotel"] == hotel]
        ax.fill_between(g.index, g["lo"], g["hi"], color="#9ec5f4", alpha=0.5, linewidth=0,
                        label="80% band")
        ax.plot(g.index, g["actual"], color="#eb6834", lw=1.2, label="Actual (real data)")
        ax.plot(b.index, b["pred"], color="#888888", lw=1, ls="--",
                label="Same weekday last week")
        ax.plot(g.index, g["pred"], color="#1f5fbf", lw=1.8, label=f"{name}, {h} days ahead")
        ax.set_title(f"{hotel}: occupied room-nights, test Mar-Aug 2017 "
                     "(REAL data, Antonio et al. 2019)", fontsize=10, loc="left")
        ax.set_ylabel("Room-nights")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False, fontsize=8, ncol=4, loc="lower right")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def occupancy(evidence: dict, use_timesfm: bool, device: str) -> dict:
    log("== Occupancy forecasting on REAL data (Hotel Booking Demand, CC BY 4.0) ==")
    path = sources.fetch(sources.HOTELS)
    bookings = hotels.load_bookings(path)
    log(f"  {path.name}: {len(bookings)} bookings, columns verified, SHA-256 "
        f"{sources.HOTELS.sha256[:16]}...")
    daily = hotels.daily_room_nights(bookings)
    otbs = {h: hotels.on_the_books(bookings, h) for h in fc.HORIZONS}
    caps = fc.capacities(daily)
    log(f"  capacity proxy (max nightly room-nights in train window): {caps}")
    rows, preds, models = tree_and_baselines(daily, otbs, caps)
    tfm_info = {}
    if use_timesfm:
        tfm_info = timesfm_block(daily, rows, preds, evidence)
    evidence["xgboost_timings"] = xgb_timings(daily, otbs, caps)
    table = pd.DataFrame(rows)
    best = choose_best(table)
    OCC_DIR.mkdir(parents=True, exist_ok=True)
    (OCC_DIR / "results_table.md").write_text(results_markdown(table, best), encoding="utf-8")
    pd.concat({f"{h}|{m}": p for (h, m), p in preds.items()}, names=["key", "date"]) \
        .reset_index().to_csv(OCC_DIR / "test_predictions.csv", index=False)
    joblib.dump({f"{h}|{k}": v for (h, k), v in models.items()}, OCC_DIR / "tree_models.joblib")
    _write_json(OCC_DIR / "feature_list.json",
                {"calendar": fc.features("calendar"), "pace": fc.features("pace")})
    daily.to_csv(OCC_DIR / "daily_room_nights.csv")
    metrics = {
        "data": "REAL: Hotel Booking Demand (Antonio, Almeida & Nunes 2019), CC BY 4.0",
        "dataset_sha256": sources.HOTELS.sha256, "split": fc.SPLIT.__dict__,
        "horizons": list(fc.HORIZONS), "capacity_proxy": caps,
        "chosen_on_validation": best.to_dict(orient="records"),
        "rows": table.to_dict(orient="records"), "timesfm": tfm_info,
        "train_device": device, "eval_device": device,
    }
    _write_json(OCC_DIR / "metrics.json", metrics)
    log(f"  plot: {save_plot(preds, best)}")
    log(results_markdown(table, best))
    return metrics


def attrition_block() -> dict:
    log("== Attrition on PUBLIC datasets (protected attributes dropped) ==")
    out = {}
    for spec, loader, ds in ((attr.IBM_SPEC, attr.load_ibm, sources.IBM_HR),
                             (attr.TURNOVER_SPEC, attr.load_turnover, sources.TURNOVER)):
        df = loader(sources.fetch(ds))
        subsets = ({"hospitality (industry == HoReCa)": (df["industry"] == "HoReCa").to_numpy()}
                   if spec is attr.TURNOVER_SPEC else None)
        res = attr.cross_validate(df, spec, subsets=subsets)
        res.update({"source_url": ds.url, "licence": ds.licence, "provenance": ds.provenance,
                    "sha256": ds.sha256})
        out[spec.name] = res
        log(f"  {spec.name} ({ds.provenance}): {res['rows']} rows, {res['positives']} leavers "
            f"(base {res['base_rate']:.3f}); dropped {res['dropped_protected']}")
        for k, v in res["scorers"].items():
            log(f"    {k:9s} ROC-AUC {v['roc_auc']['mean']:.3f}+/-{v['roc_auc']['sd']:.3f}  "
                f"PR-AUC {v['pr_auc']['mean']:.3f}  Brier {v['brier']['mean']:.4f}  "
                f"ECE {v['ece']['mean']:.4f}  fit {v['fit_seconds_total']}s")
        for name, sub in res["subsets"].items():
            log(f"  subset {name}: {sub['rows']} rows, {sub['positives']} leavers")
            for k, v in sub["scorers"].items():
                log(f"    {k:9s} ROC-AUC {v['roc_auc']} (95% CI {v['ci95']}), Brier {v['brier']}")
    _write_json(ATTR_DIR / "metrics.json", out)
    _write_json(ATTR_DIR / "dataset_hash.json",
                {ds.name: {"sha256": ds.sha256, "url": ds.url}
                 for ds in (sources.IBM_HR, sources.TURNOVER)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-timesfm", action="store_true")
    a = ap.parse_args(argv)
    warnings.filterwarnings("ignore", message=".*Falling back to prediction using DMatrix.*")
    warnings.filterwarnings("ignore", category=FutureWarning)
    np.random.default_rng(SEED)  # no global state used; every model takes SEED explicitly
    device = require_cuda()  # refuses without CUDA: no CPU fallback
    evidence = {"python": platform.python_version(), "platform": platform.platform(),
                **gpu.torch_info(), "device_used": device,
                "nvidia_smi_before": gpu.nvidia_smi()}
    log(f"== Device: {device} | {evidence} ==")
    t0 = time.perf_counter()
    occupancy(evidence, not a.no_timesfm, device)
    attrition_block()
    import xgboost as xgb
    evidence["xgboost"] = xgb.__version__
    evidence["nvidia_smi_after"] = gpu.nvidia_smi()
    evidence["total_seconds"] = round(time.perf_counter() - t0, 1)
    _write_json(GPU_DIR / "gpu_evidence.json", evidence)
    log(f"== done in {evidence['total_seconds']}s; nvidia-smi after: "
        f"{evidence['nvidia_smi_after']} ==")
    GPU_DIR.mkdir(parents=True, exist_ok=True)
    (GPU_DIR / "run_log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
