"""Train and evaluate the booking cancellation model on REAL data.

    cd ml; python run.py train-cancellation            # ~1-2 min; GPU only (refuses without CUDA)

Data: Hotel Booking Demand (Antonio, Almeida & Nunes 2019, CC BY 4.0), the same SHA-256
checked file as ml/realdata (sources.HOTELS). Split by ARRIVAL date, never random, the same
windows as the real-data forecast (forecast.Split): train arrivals <= 2016-10-31 | gap |
validation 2016-12-01..2017-01-31 | gap | TEST 2017-03-01..2017-08-31.

Scorers: base rate (training cancellation rate of the hotel for bookings the same number of
days from arrival), logistic regression (torch on the GPU) and XGBoost (GPU; replaced the
earlier LightGBM). Every fit and every evaluation prediction runs on the GPU (ml/gpu.py refuses
to train without CUDA). The deployed model is chosen BEFORE the test is read: the better of
logistic / XGBoost on validation log loss. No recalibration. The saved model is CPU-only (numpy
coefficients or an exported TreeEnsemble): the API servers need neither torch nor xgboost.

Uses of the probabilities, both evaluated on the test window:
  1. expected occupancy: rooms on the books for a night minus the expected cancellations, with
     an 80% range = mean + q * sd, sd = sqrt(sum p(1-p)); q from validation (normalised split
     conformal), because cancellations come in groups and the independent-booking range is too
     narrow.
  2. overbooking / no-show alert: expected cancellations among the rooms on the books >= 5% of
     the hotel's rooms.

Outputs: ml/artifacts/cancellation/real_v1/ (model.joblib, metrics.json, feature_list.json,
reference_stats.json, dataset_hash.json, model_card.md) and
ml/docs/plots/realdata_cancellation_calibration.png.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ml import gpu, guardrails
from ml.realdata import hotels, sources
from ml.realdata.forecast import SPLIT, Split, capacities
from ml.realdata.hotel_alerts import features as F
from ml.torch_logistic import TorchLogisticRegression
from ml.xgb_trees import TreeEnsemble

ML_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ML_ROOT / "artifacts" / "cancellation" / "real_v1"
PLOT = ML_ROOT / "docs" / "plots" / "realdata_cancellation_calibration.png"
SEED = 42
OCC_HORIZONS = (1, 7, 14, 30)
ALERT_SHARE = 0.05  # alert when expected cancellations >= 5% of the rooms (ASSUMED)
BAND = (0.10, 0.90)
Z80 = 1.2816
XGB = dict(n_estimators=3000, learning_rate=0.03, max_depth=8, min_child_weight=5,
           subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, eval_metric="logloss",
           early_stopping_rounds=100, random_state=SEED, **gpu.XGB_DEVICE)
EXPORT_CHECK_ROWS = 20_000  # training rows the exported trees must reproduce XGBoost on


# ------------------------------------------------------------------ split
def window(rows: pd.DataFrame, part: str, split: Split = SPLIT) -> pd.DataFrame:
    a = rows["arrival"]
    if part == "train":
        return rows[a <= pd.Timestamp(split.train_end)]
    lo, hi = ((split.val_start, split.val_end) if part == "val"
              else (split.test_start, split.test_end))
    return rows[(a >= pd.Timestamp(lo)) & (a <= pd.Timestamp(hi))]


# ------------------------------------------------------------------ metrics
def calibration_bins(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    out = []
    for i in range(n_bins):
        m = idx == i
        if m.any():
            out.append({"bin": f"{edges[i]:.1f}-{edges[i + 1]:.1f}", "n": int(m.sum()),
                        "mean_predicted": round(float(p[m].mean()), 4),
                        "observed_rate": round(float(y[m].mean()), 4)})
    return out


def ece(bins: list[dict]) -> float:
    n = sum(b["n"] for b in bins)
    return float(sum(b["n"] * abs(b["mean_predicted"] - b["observed_rate"]) for b in bins) / n)


def scores(y: np.ndarray, p: np.ndarray) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    bins = calibration_bins(y, p)
    single = len(np.unique(y)) < 2
    return {"n": int(len(y)), "positives": int(y.sum()), "base_rate": round(float(y.mean()), 4),
            "roc_auc": None if single else round(float(roc_auc_score(y, p)), 4),
            "pr_auc": None if single else round(float(average_precision_score(y, p)), 4),
            "brier": round(float(brier_score_loss(y, p)), 4),
            "log_loss": round(float(log_loss(y, p, labels=[0, 1])), 4),
            "ece": round(ece(bins), 4), "calibration": bins}


# ------------------------------------------------------------------ scorers
def base_rate_table(train: pd.DataFrame) -> dict[str, dict[str, float]]:
    """{hotel: {bucket index: cancellation rate}} from training snapshots (+ 'all')."""
    out: dict[str, dict[str, float]] = {}
    for name, part in [("all", train), *train.groupby("hotel")]:
        b = F.bucket_of(part["days_to_arrival"])
        rates = part.groupby(b)[F.LABEL].mean()
        overall = float(part[F.LABEL].mean())
        out[str(name)] = {str(i): float(rates.get(i, overall)) for i in range(len(F.BUCKETS))}
    return out


def base_rate_predict(table: dict, rows: pd.DataFrame) -> np.ndarray:
    b = F.bucket_of(rows["days_to_arrival"])
    hotel = rows["hotel"].astype(str).to_numpy()
    return np.array([table.get(h, table["all"])[str(i)] for h, i in zip(hotel, b, strict=True)])


def fit_logistic(x: pd.DataFrame, y: np.ndarray):
    """Standardise + L2 logistic regression (C = 1), torch on the GPU."""
    return make_pipeline(StandardScaler(), TorchLogisticRegression(C=1.0, max_iter=3000)).fit(x, y)


def fit_xgb(x, y, xv, yv):
    """XGBoost on the GPU, early stopping on validation log loss."""
    import xgboost as xgb

    gpu.require_cuda()
    m = xgb.XGBClassifier(**XGB)
    m.fit(x, y, eval_set=[(xv, yv)], verbose=False)
    gpu.assert_xgb_on_cuda(m)
    return m


def proba(model, x: pd.DataFrame) -> np.ndarray:
    return model.predict_proba(x)[:, 1]


# ------------------------------------------------------------------ occupancy use
def otb_rows(b: pd.DataFrame, nights: pd.DatetimeIndex, horizons=OCC_HORIZONS) -> pd.DataFrame:
    """Every (night d, horizon h, booking on the books at t = d - h covering d)."""
    stay = b[b["nights"] > 0]
    out = []
    for d in nights:
        cover = stay[(stay["arrival"] <= d)
                     & (stay["arrival"] + pd.to_timedelta(stay["nights"], unit="D") > d)]
        for h in horizons:
            t = d - pd.Timedelta(days=h)
            alive = cover[(cover["created"] <= t)
                          & ~(cover["cancelled_on"].notna() & (cover["cancelled_on"] <= t))]
            if alive.empty:
                continue
            out.append(pd.DataFrame({"night": d, "h": h, "booking_id": alive.index,
                                     "dta": (alive["arrival"] - t).dt.days.to_numpy()}))
    return pd.concat(out, ignore_index=True)


def otb_probabilities(b: pd.DataFrame, rows: pd.DataFrame, model, columns: list[str],
                      table: dict) -> pd.DataFrame:
    """p (model) and p_base (base rate) per on-the-books row; 0 for guests already in-house."""
    static = F._static(b).loc[rows["booking_id"]].reset_index(drop=True)
    future = rows["dta"].to_numpy() > 0
    snap = static.assign(days_to_arrival=np.maximum(rows["dta"].to_numpy(), 0).astype(float))
    snap["days_since_booking"] = snap["lead_time"] - snap["days_to_arrival"]
    p = np.zeros(len(rows))
    pb = np.zeros(len(rows))
    if future.any():
        p[future] = proba(model, F.encode(snap[future], columns))
        pb[future] = base_rate_predict(table, snap[future])
    out = rows.copy()
    out["hotel"] = b.loc[rows["booking_id"], "hotel"].to_numpy()
    out["p"], out["p_base"] = p, pb
    out["kept"] = 1 - b.loc[rows["booking_id"], F.LABEL].to_numpy()
    return out


def per_night(r: pd.DataFrame) -> pd.DataFrame:
    r = r.assign(var=r["p"] * (1 - r["p"]), var_base=r["p_base"] * (1 - r["p_base"]))
    g = r.groupby(["hotel", "h", "night"])
    return pd.DataFrame({"otb": g.size(), "kept": g["kept"].sum(),
                         "exp_cancel_model": g["p"].sum(), "exp_cancel_base": g["p_base"].sum(),
                         "sd_model": np.sqrt(g["var"].sum()),
                         "sd_base": np.sqrt(g["var_base"].sum())}).reset_index().assign(
        cancelled=lambda x: x["otb"] - x["kept"],
        exp_kept_model=lambda x: x["otb"] - x["exp_cancel_model"],
        exp_kept_base=lambda x: x["otb"] - x["exp_cancel_base"])


def conformal_q(z: np.ndarray, band=BAND) -> tuple[float, float]:
    n = len(z)
    lo = np.quantile(z, max(0.0, math.floor(band[0] * (n + 1)) / n))
    hi = np.quantile(z, min(1.0, math.ceil(band[1] * (n + 1)) / n))
    return float(lo), float(hi)


SOURCES = ("model", "base")


def _z(part: pd.DataFrame, src: str) -> np.ndarray:
    return ((part["kept"] - part[f"exp_kept_{src}"])
            / part[f"sd_{src}"].clip(lower=1e-6)).to_numpy()


def occupancy_eval(val_n: pd.DataFrame, test_n: pd.DataFrame, caps: dict[str, float]) -> dict:
    """Per horizon: the adjustment source (model or base-rate table) with the lower VALIDATION
    MAE is deployed; its 80% range uses normalised split-conformal multipliers from validation.
    Test numbers are reported for every option."""
    out: dict = {"by_horizon": {}, "range_q": {}, "source": {}, "validation_mae": {}}
    for h in OCC_HORIZONS:
        v, t = val_n[val_n["h"] == h], test_n[test_n["h"] == h]
        val_mae = {src: float((v[f"exp_kept_{src}"] - v["kept"]).abs().mean()) for src in SOURCES}
        val_mae["none"] = float((v["otb"] - v["kept"]).abs().mean())
        src = min(SOURCES, key=lambda s: val_mae[s])
        qs = {s: conformal_q(_z(v, s)) for s in SOURCES}
        out["source"][str(h)] = src
        out["validation_mae"][str(h)] = {k: round(x, 2) for k, x in val_mae.items()}
        out["range_q"][str(h)] = {s: [round(q[0], 4), round(q[1], 4)] for s, q in qs.items()}
        rows = {}
        for hotel, part in [("both", t), *t.groupby("hotel")]:
            k = part["kept"]
            q = qs[src]
            lo = part[f"exp_kept_{src}"] + q[0] * part[f"sd_{src}"]
            hi = part[f"exp_kept_{src}"] + q[1] * part[f"sd_{src}"]
            sd = part[f"sd_{src}"]
            rows[str(hotel)] = {
                "nights": int(len(part)), "mean_on_books": round(float(part["otb"].mean()), 1),
                "mean_cancelled": round(float(part["cancelled"].mean()), 2),
                "mae_no_adjustment": round(float((part["otb"] - k).abs().mean()), 2),
                "mae_base_rate": round(float((part["exp_kept_base"] - k).abs().mean()), 2),
                "mae_model": round(float((part["exp_kept_model"] - k).abs().mean()), 2),
                "deployed_source": src,
                "mae_deployed": round(float((part[f"exp_kept_{src}"] - k).abs().mean()), 2),
                "range80_coverage_conformal": round(float(((k >= lo) & (k <= hi)).mean()), 3),
                "range80_mean_width_conformal": round(float((hi - lo).mean()), 2),
                "range80_coverage_independent": round(float(
                    ((k - part[f"exp_kept_{src}"]).abs() <= Z80 * sd).mean()), 3),
            }
        out["by_horizon"][str(h)] = rows
    # overbooking / no-show alert at 7 and 1 days ahead
    out["alert"] = {}
    for h in (7, 1):
        t = test_n[test_n["h"] == h]
        res = {}
        for hotel, part in t.groupby("hotel"):
            k = math.ceil(ALERT_SHARE * caps[hotel])
            event = part["cancelled"] >= k
            r = {"threshold_rooms": k, "nights": int(len(part)), "event_nights": int(event.sum()),
                 "deployed_source": out["source"][str(h)]}
            for name in SOURCES:
                flag = part[f"exp_cancel_{name}"] >= k
                tp = int((flag & event).sum())
                r[name] = {"flagged": int(flag.sum()),
                           "precision": round(tp / flag.sum(), 3) if flag.any() else None,
                           "recall": round(tp / event.sum(), 3) if event.any() else None}
            res[str(hotel)] = r
        out["alert"][str(h)] = res
    return out


# ------------------------------------------------------------------ plot
def save_plot(test_scores: dict[str, dict], path: Path = PLOT) -> Path | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.plot([0, 1], [0, 1], color="#999", lw=1, ls="--", label="perfect")
    for name, s in test_scores.items():
        bins = s["calibration"]
        ax.plot([b["mean_predicted"] for b in bins], [b["observed_rate"] for b in bins],
                marker="o", label=f"{name} (Brier {s['brier']:.3f})")
    ax.set_xlabel("predicted chance of cancelling")
    ax.set_ylabel("share that really cancelled")
    ax.set_title("Booking cancellation, REAL data test Mar-Aug 2017\n"
                 "(Hotel Booking Demand, CC BY 4.0; at booking time)", fontsize=9)
    ax.legend(fontsize=8)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


# ------------------------------------------------------------------ main
def deployable(model, kind: str, x: pd.DataFrame):
    """The CPU-inference copy that is saved: numpy logistic or an exported TreeEnsemble."""
    if kind == "logistic":
        model[-1].to_cpu()
        return model
    return TreeEnsemble.from_xgb(model, x.sample(min(len(x), EXPORT_CHECK_ROWS),
                                                 random_state=SEED))


def model_card(m: dict) -> str:
    t = m["test_at_booking"]
    win = m["deployed"]["model"]
    lines = [
        "# Model card: booking cancellation risk (cancellation/real_v1)",
        "",
        "**Data: REAL** public bookings (not synthetic): Hotel Booking Demand, Antonio, Almeida &"
        " Nunes (2019), *Data in Brief* 22:41-49, CC BY 4.0. Two Portuguese hotels (Lisbon city,"
        " Algarve resort), arrivals 2015-07..2017-08. Data card: "
        "`ml/realdata/hotel_alerts/DATA_CARD.md`.",
        "",
        f"- Task: chance that a booking on the books is cancelled or a no-show. Deployed model: "
        f"**{win}** (chosen on validation log loss before the test was read).",
        f"- Trained on {m['split']['train_rows']:,} snapshots (arrivals <= "
        f"{m['split']['train_end']}); test = arrivals {m['split']['test']}.",
        f"- Features ({len(m['features'])}): booking-time fields only; excluded columns and "
        "reasons in `feature_list.json`.",
        "",
        "| Test, at booking time | ROC-AUC | PR-AUC | Brier | ECE |",
        "|---|---|---|---|---|",
    ]
    for name, s in t.items():
        lines.append(f"| {name} | {s['roc_auc']} | {s['pr_auc']} | {s['brier']} | {s['ece']} |")
    lines += [
        "",
        "Occupancy use (rooms on the books that really stay, test, both hotels; source chosen "
        "per horizon on validation MAE):",
        "",
        "| Days ahead | No adjustment | Base-rate table | Model | Deployed | 80% range coverage |",
        "|---|---|---|---|---|---|",
        *[f"| {h} | {v['both']['mae_no_adjustment']} | {v['both']['mae_base_rate']} | "
          f"{v['both']['mae_model']} | {v['both']['deployed_source']} | "
          f"{v['both']['range80_coverage_conformal']} |"
          for h, v in m["occupancy"]["by_horizon"].items()],
        "",
        "Limits: Portuguese city / resort hotels with high cancellation rates (city 42%, resort "
        "28%), not Uttarakhand hill hotels; HOI's synthetic hotel has no booking records, so "
        "the product uses the base-rate table unless real bookings are sent. Retrain on the "
        "hotel's own bookings before trusting the numbers.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.parse_args(argv)
    device = gpu.require_cuda()  # refuses without CUDA: no CPU fallback
    t0 = time.time()
    path = sources.fetch(sources.HOTELS)
    b = hotels.load_bookings(path)
    print(f"REAL data: {len(b):,} bookings from {path.name} (SHA-256 verified)")
    rows = F.snapshots(b)
    tr, va, te = (window(rows, p) for p in ("train", "val", "test"))
    print(f"snapshots: train {len(tr):,}, val {len(va):,}, test {len(te):,}")
    cols = list(F.encode(tr).columns)
    xtr, xva, xte = F.encode(tr, cols), F.encode(va, cols), F.encode(te, cols)
    ytr, yva, yte = (p[F.LABEL].to_numpy() for p in (tr, va, te))
    table = base_rate_table(tr)

    t1 = time.time()
    models = {"logistic": fit_logistic(xtr, ytr)}
    fit_seconds = {"logistic": round(time.time() - t1, 1)}
    t1 = time.time()
    models["xgboost"] = fit_xgb(xtr, ytr, xva, yva)
    fit_seconds["xgboost"] = round(time.time() - t1, 1)
    xgb_info = {"device": device, "fit_seconds": fit_seconds,
                "best_iteration": int(models["xgboost"].best_iteration)}
    preds = {"base_rate": {"val": base_rate_predict(table, va),
                           "test": base_rate_predict(table, te)}}
    for name, mdl in models.items():
        preds[name] = {"val": proba(mdl, xva), "test": proba(mdl, xte)}

    val_scores = {n: scores(yva, p["val"]) for n, p in preds.items()}
    winner = min(("logistic", "xgboost"), key=lambda n: val_scores[n]["log_loss"])
    print("validation log loss: " + ", ".join(f"{n} {s['log_loss']}"
                                                 for n, s in val_scores.items())
          + f" -> deployed: {winner}")
    test_all = {n: scores(yte, p["test"]) for n, p in preds.items()}
    snap = te["snapshot"].to_numpy()
    by_snapshot = {s: {n: {k: v for k, v in scores(yte[snap == s], p["test"][snap == s]).items()
                           if k != "calibration"} for n, p in preds.items()}
                   for s in ["booking", *(f"{h}d" for h in F.SNAPSHOT_DAYS)]}
    at_booking = {n: scores(yte[snap == "booking"], p["test"][snap == "booking"])
                  for n, p in preds.items()}
    hotel = te["hotel"].to_numpy()
    by_hotel = {h: {n: {k: v for k, v in scores(yte[(hotel == h) & (snap == "booking")],
                                                 p["test"][(hotel == h) & (snap == "booking")]
                                                 ).items() if k != "calibration"}
                    for n, p in preds.items()} for h in hotels.HOTELS}

    # ablation: drop the two final-value columns that may change after booking
    acols = list(F.encode(tr, drop=F.ABLATION_DROP).columns)
    abl = (fit_logistic if winner == "logistic" else
           lambda x, y: fit_xgb(x, y, F.encode(va, acols, F.ABLATION_DROP), yva))(
        F.encode(tr, acols, F.ABLATION_DROP), ytr)
    pa = proba(abl, F.encode(te, acols, F.ABLATION_DROP))
    ablation = {k: v for k, v in scores(yte[snap == "booking"], pa[snap == "booking"]).items()
                if k != "calibration"}

    # occupancy adjustment + alert
    daily = hotels.daily_room_nights(b)
    caps = capacities(daily)
    nights = {p: pd.date_range(*(SPLIT.val_start, SPLIT.val_end) if p == "val"
                               else (SPLIT.test_start, SPLIT.test_end)) for p in ("val", "test")}
    occ_n = {p: per_night(otb_probabilities(b, otb_rows(b, nights[p]), models[winner], cols,
                                            table)) for p in nights}
    occupancy = occupancy_eval(occ_n["val"], occ_n["test"], caps)

    ref = guardrails.build_reference(
        tr, F.FEATURES, model="cancellation/real_v1", trained_on=date.today().isoformat(),
        training_window=f"arrivals ..{SPLIT.train_end} (REAL data)")
    metrics = {
        "data": {"provenance": "REAL", "dataset": sources.HOTELS.name,
                 "citation": sources.HOTELS.citation, "licence": sources.HOTELS.licence,
                 "url": sources.HOTELS.url, "sha256": sources.HOTELS.sha256,
                 "bookings": int(len(b))},
        "split": {"by": "arrival date", "train_end": SPLIT.train_end,
                  "val": f"{SPLIT.val_start}..{SPLIT.val_end}",
                  "test": f"{SPLIT.test_start}..{SPLIT.test_end}",
                  "train_rows": int(len(tr)), "val_rows": int(len(va)), "test_rows": int(len(te)),
                  "snapshots": ["booking", *(f"{h}d" for h in F.SNAPSHOT_DAYS)]},
        "features": F.FEATURES, "excluded": F.EXCLUDED,
        "deployed": {"model": winner, "rule": "lower validation log loss of logistic / "
                     "XGBoost, decided before the test was read; no recalibration",
                     "xgboost_best_iteration": int(models["xgboost"].best_iteration)},
        "train_device": device, "eval_device": device,
        "validation": {n: {k: v for k, v in s.items() if k != "calibration"}
                       for n, s in val_scores.items()},
        "test_all_snapshots": {n: {k: v for k, v in s.items() if k != "calibration"}
                               for n, s in test_all.items()},
        "test_at_booking": at_booking,
        "test_by_snapshot": by_snapshot, "test_by_hotel_at_booking": by_hotel,
        "ablation_without_adr_and_special_requests": {"model": winner, **ablation},
        "occupancy": occupancy, "capacity_proxy": caps, "xgboost": xgb_info,
        "base_rate_table": {"buckets": [F.bucket_label(i) for i in range(len(F.BUCKETS))],
                            **table},
        "seconds": round(time.time() - t0, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": deployable(models[winner], winner, xtr), "kind": winner,
                 "columns": cols, "table": table,
                 "range_q": occupancy["range_q"],
                 "occ_source": occupancy["source"], "buckets": list(F.BUCKETS),
                 "features": F.FEATURES}, OUT_DIR / "model.joblib")
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", "utf-8")
    (OUT_DIR / "feature_list.json").write_text(json.dumps(
        {"features": F.FEATURES, "categorical": F.CATEGORICAL, "numeric": F.NUMERIC,
         "excluded": F.EXCLUDED, "encoded_columns": cols}, indent=2) + "\n", "utf-8")
    guardrails.save_reference(ref, OUT_DIR)
    (OUT_DIR / "dataset_hash.json").write_text(json.dumps(
        {"synthetic": False, "provenance": "REAL", "files": {"hotels.csv": sources.HOTELS.sha256},
         "combined_sha256": sources.HOTELS.sha256}, indent=2) + "\n", "utf-8")
    (OUT_DIR / "model_card.md").write_text(model_card(metrics), "utf-8")
    plot = save_plot({n: at_booking[n] for n in ("base_rate", "logistic", "xgboost")
                      if n in at_booking})
    print(json.dumps({"test_at_booking": {n: {k: s[k] for k in ("roc_auc", "pr_auc", "brier",
                                                                 "ece")}
                                          for n, s in at_booking.items()},
                      "occupancy": {h: v["both"] for h, v in occupancy["by_horizon"].items()},
                      "alert": occupancy["alert"]}, indent=1))
    print(f"wrote {OUT_DIR} and {plot} in {metrics['seconds']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
