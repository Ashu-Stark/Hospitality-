"""Train and evaluate the Char Dham crowd model on REAL public data; write artifacts and the bundle.

    python -m ml.realdata.crowd.train                 # from the repo root (about a minute, CPU)
    python -m ml.realdata.crowd.train --export-only   # re-copy bundle + predict code to the portal

Forecast set-up. A forecast is made on an ORIGIN day t when a real figure has just been published
(an anchor of the cumulative curve: see target.py) and covers days t+1..t+14. Lags use only days
<= t, and every day value <= t depends only on anchors <= t, so the target construction cannot
leak later figures into the features. Weather on the target day is used for horizons <= 7 (the
serving-time forecast reach); training uses the archive, i.e. a PERFECT weather forecast
(optimistic; the no-weather ablation shows how much it matters).

Splits, by season only (never random):
  selection : train <= V-2, validate on V-1 (choose the objective)
  test      : twin trained <= T-2 calibrates the 80% range on T-1 (split conformal); final model
              trained <= T-1; scored on season T
Evaluated twice: T = 2025 (latest complete season) and T = 2026 (season to date; this final model
is the deployed one).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.realdata.crowd import calendar_data, target
from ml.realdata.crowd import predict as P
from ml.realdata.crowd.sources import (
    ARTIFACT_DIR,
    PORTAL_CODE,
    PORTAL_MODEL,
    RAW_DIR,
    SOURCES,
)

SEED = 42
MIN_ANCHORS = 4  # real anchors a season needs to be trained on (ASSUMED)
DENSE_ANCHORS = 8  # real anchors a season needs to be scored / calibrated on (ASSUMED)
PARAMS = {
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 40,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "seed": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "verbose": -1,
    "num_threads": 4,
}
ROUNDS = 400
# Small grid, chosen on the VALIDATION season only (never on a test season).
GRID = [
    {"num_leaves": nl, "min_data_in_leaf": md, "rounds": r}
    for nl in (7, 15)
    for md in (20, 60)
    for r in (200, 600)
]
CHOSEN: dict = {}
ALPHA = 0.2  # 80% range
GUARD = {
    "drift_margin": 0.25,
    "lag_grace_days": 3,
    "fallback_low": 0.5,
    "fallback_high": 1.5,
    "width_floor": 200.0,
    "high_width": 0.6,
    "low_width": 1.2,
    "abstain_width": 3.0,
}
# Feature-group ablations, reported (never deployed): does each group help on the test season?
ABLATIONS = {
    "model_no_school": ("school_vac",),
    "model_no_holidays": ("is_holiday", "is_long_weekend", "is_festival"),
    "model_no_lags": ("lag1", "lag7", "lag_trend", "yoy"),
}
CAP_FACTOR = 1.25  # cap = 1.25 x highest real single-day count seen (ASSUMED physical ceiling)


# ----------------------------------------------------------------------------- inputs


def load_weather() -> dict:
    w = pd.read_csv(RAW_DIR / "openmeteo_archive_daily.csv")
    out: dict = {}
    for r in w.itertuples():
        out.setdefault(r.destination, {})[date.fromisoformat(r.time)] = (
            float(r.precipitation_sum),
            float(r.snowfall_sum),
            float(r.temperature_2m_max),
        )
    return out


def load_all():
    seasons = calendar_data.seasons()
    gaz, fest = calendar_data.holidays()
    school = calendar_data.school_share()
    series = target.build_all(seasons)
    return seasons, gaz, fest, school, series


def usable(series: dict, n: int = MIN_ANCHORS) -> dict[tuple[str, int], bool]:
    return {k: len(s.anchors) - 1 >= n for k, s in series.items()}


def make_context(seasons, gaz, fest, school, series, scale, weather) -> P.Context:
    daily = {}
    for (dest, _y), s in series.items():
        daily.setdefault(dest, {}).update(s.daily)
    return P.Context(seasons, daily, gaz, fest, school, scale, weather)


def scale_for(series: dict, years: set[int], ok: dict) -> dict[str, float]:
    out = {}
    for dest in P.DESTS:
        vals = [
            v
            for (d, y), s in series.items()
            if d == dest and y in years and ok[(d, y)]
            for v in s.daily.values()
        ]
        out[dest] = float(np.mean(vals)) if vals else 1000.0
    return out


def rows(
    ctx: P.Context, series: dict, keys: list[tuple[str, int]], use_weather: bool = True
) -> pd.DataFrame:
    """One row per (origin anchor, horizon) inside each season in `keys`."""
    out = []
    for dest, year in keys:
        s = series[(dest, year)]
        last = s.last_day
        for a in s.anchors[:-1] if s.anchors[-1].day == last else s.anchors:
            t = a.day
            for h in range(1, P.MAX_H + 1):
                d = t + timedelta(days=h)
                if d not in s.daily:
                    break
                f = P.feature_row(ctx, dest, d, t, weather=None if use_weather else {})
                iv = s.interval[d]
                out.append(
                    {
                        **f,
                        "_dest": dest,
                        "_season": year,
                        "_date": d,
                        "_origin": t,
                        "_y": s.daily[d],
                        "_basis": s.basis[d],
                        "_iv_start": iv[0],
                        "_iv_end": iv[1],
                        "_iv_days": (iv[1] - iv[0]).days + 1,
                        "_scale": ctx.scale[dest],
                        "_snaive": _snaive(ctx, series, dest, d),
                        "_heavy": _heavy(ctx, dest, d),
                    }
                )
    return pd.DataFrame(out)


def _snaive(ctx, series, dest, d) -> float:
    """Seasonal naive: last season's count on the same day of the season."""
    cur = ctx.season_of(dest, d)
    prev = ctx.seasons.get(dest, {}).get(d.year - 1)
    if not cur or not prev:
        return math.nan
    s = series.get((dest, d.year - 1))
    v = s.daily.get(prev[0] + (d - cur[0])) if s else None
    return float(v) if v is not None else math.nan


def _heavy(ctx, dest, d) -> bool:
    w = ctx.weather.get(dest, {})
    a, b = w.get(d), w.get(d - timedelta(days=1))
    return bool((a and a[0] >= P.HEAVY_RAIN_MM) or (b and b[0] >= P.HEAVY_RAIN_MM))


# ----------------------------------------------------------------------------- models


def fit(
    df: pd.DataFrame, objective: str, alpha: float | None = None, features=P.FEATURES
) -> lgb.Booster:
    y = df["_y"] / df["_scale"]
    params = {
        **PARAMS,
        **{k: v for k, v in CHOSEN.items() if k != "rounds"},
        "objective": objective,
    }
    if alpha is not None:
        params["alpha"] = alpha
    # A day inside a long reporting interval is an even share, not a real day value: weight it down.
    w = np.minimum(1.0, 7.0 / df["_iv_days"].to_numpy())
    return lgb.train(
        params,
        lgb.Dataset(df[list(features)], y, weight=w),
        num_boost_round=CHOSEN.get("rounds", ROUNDS),
    )


def fit_set(df: pd.DataFrame, objective: str) -> dict[str, lgb.Booster]:
    return {
        "point": fit(df, objective),
        "q10": fit(df, "quantile", 0.1),
        "q90": fit(df, "quantile", 0.9),
    }


def raw_preds(models: dict, df: pd.DataFrame) -> dict[str, np.ndarray]:
    X = df[list(P.FEATURES)]
    return {k: m.predict(X) * df["_scale"].to_numpy() for k, m in models.items()}


def conformal_q(models: dict, cal: pd.DataFrame) -> float:
    """Split-conformal (CQR) widening in scaled units so the 80% range covers 80% on `cal`."""
    p = raw_preds(models, cal)
    lo = np.minimum(p["q10"], p["q90"]) / cal["_scale"]
    hi = np.maximum(p["q10"], p["q90"]) / cal["_scale"]
    y = cal["_y"] / cal["_scale"]
    e = np.maximum(lo - y, y - hi).to_numpy()
    n = len(e)
    level = min(1.0, math.ceil((n + 1) * (1 - ALPHA)) / n)
    return float(np.quantile(e, level, method="higher"))


def apply(models: dict, df: pd.DataFrame, cq: float, caps: dict) -> pd.DataFrame:
    p = raw_preds(models, df)
    sc = df["_scale"].to_numpy()
    cap = df["_dest"].map(caps).to_numpy()
    lo = np.minimum(p["q10"], p["q90"]) - cq * sc
    hi = np.maximum(p["q10"], p["q90"]) + cq * sc
    pt = np.clip(np.clip(p["point"], lo, hi), 0, cap)
    out = df[
        [
            "_dest",
            "_season",
            "_date",
            "_origin",
            "h",
            "_y",
            "_basis",
            "_iv_start",
            "_iv_end",
            "_iv_days",
            "_snaive",
            "_heavy",
            "dos",
            "days_to_close",
        ]
    ].copy()
    out["model"] = pt
    out["low"] = np.clip(lo, 0, cap)
    out["high"] = np.clip(hi, 0, cap)
    out["ma7"] = np.where(np.isnan(df["lag7"]), df["_snaive"], df["lag7"] * sc)
    out["snaive"] = df["_snaive"]
    return out


def xgb_point(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, str]:
    """XGBoost on the GPU when available (comparison only; LightGBM is deployed)."""
    import xgboost as xgb

    y = train["_y"] / train["_scale"]
    for device in ("cuda", "cpu"):
        try:
            m = xgb.XGBRegressor(
                n_estimators=ROUNDS,
                learning_rate=0.05,
                max_depth=4,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=SEED,
                tree_method="hist",
                device=device,
            )
            m.fit(train[list(P.FEATURES)], y)
            m.set_params(device="cpu")  # predict on CPU: the test frame lives in host memory
            return m.predict(test[list(P.FEATURES)]) * test["_scale"].to_numpy(), device
        except Exception:  # noqa: BLE001  (no CUDA build / no GPU: fall back to CPU)
            continue
    raise RuntimeError("xgboost failed on cuda and cpu")


# ----------------------------------------------------------------------------- metrics


def band_series(dests: pd.Series, vals: np.ndarray, edges: dict) -> list[str]:
    out = []
    for d, v in zip(dests, vals, strict=True):
        e = edges[d]
        out.append(
            "low" if v < e[0] else "moderate" if v < e[1] else "high" if v < e[2] else "very_high"
        )
    return out


def point_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    ok = ~np.isnan(p)
    y, p = y[ok], p[ok]
    m = y >= 100  # MAPE only where at least 100 pilgrims came (nil / near-nil days excluded)
    return {
        "n": int(len(y)),
        "mae": float(np.mean(np.abs(y - p))),
        "mape_pct": float(100 * np.mean(np.abs(y[m] - p[m]) / y[m])) if m.any() else None,
    }


def evaluate(res: pd.DataFrame, edges: dict) -> dict:
    common = res.dropna(subset=["snaive"])
    y = common["_y"].to_numpy()
    out = {
        "rows_scored": int(len(common)),
        "rows_without_last_season": int(len(res) - len(common)),
        "daily": {},
        "by_horizon": {},
        "by_basis": {},
        "intervals": {},
    }
    for k in ("snaive", "ma7", "model", "xgb_gpu", "model_no_weather", *ABLATIONS):
        if k in common:
            out["daily"][k] = point_metrics(y, common[k].to_numpy())
    actual_b = band_series(common["_dest"], y, edges)
    out["band_accuracy"] = {
        k: float(
            np.mean(
                np.array(band_series(common["_dest"], common[k].to_numpy(), edges))
                == np.array(actual_b)
            )
        )
        for k in ("snaive", "ma7", "model")
    }
    inside = (common["_y"] >= common["low"]) & (common["_y"] <= common["high"])
    out["range80"] = {
        "coverage": float(inside.mean()),
        "mean_width": float((common["high"] - common["low"]).mean()),
    }
    for hg, (a, b) in {"1-3": (1, 3), "4-7": (4, 7), "8-14": (8, 14)}.items():
        g = common[(common["h"] >= a) & (common["h"] <= b)]
        out["by_horizon"][hg] = {
            k: point_metrics(g["_y"].to_numpy(), g[k].to_numpy())
            for k in ("snaive", "ma7", "model")
        }
    for basis, g in common.groupby("_basis"):
        out["by_basis"][basis] = {
            k: point_metrics(g["_y"].to_numpy(), g[k].to_numpy())
            for k in ("snaive", "ma7", "model")
        }
    # REAL interval totals: forecasts from an anchor for the whole next interval (<= 14 days).
    iv = common[common["_iv_start"] == common["_origin"] + timedelta(days=1)]
    g = iv.groupby(["_dest", "_season", "_iv_start", "_iv_end", "_iv_days"])
    sums = g[["_y", "snaive", "ma7", "model"]].sum()
    full = g.size().to_numpy() == sums.index.get_level_values("_iv_days").to_numpy()
    sums = sums[full]
    for k in ("snaive", "ma7", "model"):
        err = (sums[k] - sums["_y"]).abs()
        out["intervals"][k] = {
            "n": int(len(sums)),
            "mae": float(err.mean()) if len(sums) else None,
            "mape_pct": float(100 * (err / sums["_y"].clip(lower=1)).mean()) if len(sums) else None,
        }
    return out


def failure_analysis(res: pd.DataFrame) -> dict:
    r = res.dropna(subset=["snaive"]).copy()
    r["err"] = (r["model"] - r["_y"]).abs()
    r["err_snaive"] = (r["snaive"] - r["_y"]).abs()
    buckets = {
        "opening week (day 0-6)": r["dos"] <= 6,
        "days 7-29": (r["dos"] >= 7) & (r["dos"] <= 29),
        "days 30-89": (r["dos"] >= 30) & (r["dos"] <= 89),
        "day 90+": r["dos"] >= 90,
        "last 14 days before closing": r["days_to_close"] <= 13,
        "heavy-rain days (>= 35 mm, day or day before)": r["_heavy"],
        "officially nil days": r["_basis"] == "nil",
    }
    out = {}
    for name, m in buckets.items():
        g = r[m]
        out[name] = {
            "n": int(len(g)),
            "model_mae": float(g["err"].mean()) if len(g) else None,
            "snaive_mae": float(g["err_snaive"].mean()) if len(g) else None,
            "mean_actual": float(g["_y"].mean()) if len(g) else None,
        }
    worst = r.sort_values("err", ascending=False).drop_duplicates(["_dest", "_date"]).head(10)
    out["worst_days"] = [
        {
            "dest": w["_dest"],
            "date": w["_date"].isoformat(),
            "h": int(w["h"]),
            "actual": round(w["_y"]),
            "model": round(w["model"]),
            "snaive": round(w["snaive"]),
            "basis": w["_basis"],
            "day_of_season": int(w["dos"]),
            "heavy_rain": bool(w["_heavy"]),
        }
        for w in worst.to_dict("records")
    ]
    return out


# ----------------------------------------------------------------------------- export


def compact(booster: lgb.Booster) -> list:
    def node(n):
        if "leaf_value" in n:
            return round(float(n["leaf_value"]), 10)
        if n.get("decision_type", "<=") != "<=":
            raise ValueError("only numerical <= splits are exported")
        miss = {"None": 0, "Zero": 1, "NaN": 2}[n.get("missing_type", "None")]
        return [
            int(n["split_feature"]),
            float(n["threshold"]),
            bool(n["default_left"]),
            miss,
            node(n["left_child"]),
            node(n["right_child"]),
        ]

    return [node(t["tree_structure"]) for t in booster.dump_model()["tree_info"]]


def feature_ranges(df: pd.DataFrame) -> dict:
    out = {}
    for f in P.FEATURES:
        v = df[f].dropna()
        out[f] = [float(v.quantile(0.005)), float(v.quantile(0.995))] if len(v) else [0.0, 0.0]
    return out


def build_bundle(models, cq, ctx, series, ok, train_rows, edges, caps, metrics_summary) -> dict:
    dests = {}
    for dest in P.DESTS:
        yrs = {y: [o.isoformat(), c.isoformat()] for y, (o, c) in ctx.seasons[dest].items()}
        ser = {
            d.isoformat(): round(v, 1)
            for (k, y), s in series.items()
            if k == dest and ok[(k, y)]
            for d, v in s.daily.items()
        }
        dests[dest] = {
            "seasons": {str(y): v for y, v in yrs.items()},
            "series": ser,
            "scale": ctx.scale[dest],
            "cap": caps[dest],
            "band_edges": [float(x) for x in edges[dest]],
        }
    return {
        "version": "real_v1",
        "real_data": True,
        "trained_on_seasons": sorted({int(y) for y in train_rows["_season"].unique()}),
        "feature_names": list(P.FEATURES),
        "conformal_q": cq,
        "guard": GUARD,
        "models": {k: compact(m) for k, m in models.items()},
        "destinations": dests,
        "feature_ranges": feature_ranges(train_rows),
        "calendar": {
            "holidays": sorted(d.isoformat() for d in ctx.holidays),
            "festivals": sorted(d.isoformat() for d in ctx.festivals),
            "school_vacation_share": {
                d.isoformat(): round(v, 3) for d, v in sorted(ctx.school.items())
            },
        },
        "summary": metrics_summary,
        "sources": [s.key for s in SOURCES],
        "note": "REAL public data (official figures via UTDB, SEOC/SDC and news). Daily values "
        "inside reporting intervals are ESTIMATED by even spreading; see DATA_CARD.md.",
    }


def export(bundle_path=ARTIFACT_DIR / "bundle.json") -> None:
    PORTAL_MODEL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundle_path, PORTAL_MODEL)
    src = (ARTIFACT_DIR.parents[2] / "realdata" / "crowd" / "predict.py").read_bytes()
    PORTAL_CODE.write_bytes(src)


# ----------------------------------------------------------------------------- main


def run_test(ctx_for, series, ok, test_year: int, objective: str, edges, caps) -> tuple:
    """Twin (<= T-2) -> conformal on T-1; final (<= T-1) -> score T."""
    keys = lambda years: [k for k in series if k[1] in years and ok[k]]  # noqa: E731
    dense = usable(series, DENSE_ANCHORS)
    dense_keys = lambda years: [k for k in series if k[1] in years and dense[k]]  # noqa: E731
    years = sorted({y for (_d, y), u in ok.items() if u})
    ctx = ctx_for({y for y in years if y < test_year})
    twin = rows(ctx, series, keys({y for y in years if y < test_year - 1}))
    cal = rows(ctx, series, dense_keys({test_year - 1}))
    train = rows(ctx, series, keys({y for y in years if y < test_year}))
    test = rows(ctx, series, dense_keys({test_year}))
    cq = conformal_q(fit_set(twin, objective), cal)
    models = fit_set(train, objective)
    res = apply(models, test, cq, caps)
    res["xgb_gpu"], device = xgb_point(train, test)
    nw_train = rows(ctx, series, keys({y for y in years if y < test_year}), use_weather=False)
    nw_test = rows(ctx, series, dense_keys({test_year}), use_weather=False)
    res["model_no_weather"] = np.clip(
        fit(nw_train, objective).predict(nw_test[list(P.FEATURES)]) * nw_test["_scale"].to_numpy(),
        0,
        None,
    )
    for name, drop in ABLATIONS.items():
        feats = [f for f in P.FEATURES if f not in drop]
        m = fit(train, objective, features=feats)
        res[name] = np.clip(m.predict(test[feats]) * test["_scale"].to_numpy(), 0, None)
    return models, cq, train, test, res, device, ctx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export-only", action="store_true")
    a = ap.parse_args()
    if a.export_only:
        export()
        return 0
    seasons, gaz, fest, school, series = load_all()
    weather = load_weather()
    ok = usable(series)
    years = sorted({y for (_d, y), u in ok.items() if u})
    print("usable seasons:", {k: len(s.anchors) - 1 for k, s in series.items()})
    for k, s in series.items():
        for msg in s.dropped:
            print(f"  {k}: {msg}")

    def ctx_for(train_years: set[int]) -> P.Context:
        return make_context(
            seasons, gaz, fest, school, series, scale_for(series, train_years, ok), weather
        )

    # Band edges and caps from real values only (edges: training seasons; caps: peak days).
    def edges_for(train_years):
        out = {}
        for dest in P.DESTS:
            v = [
                x
                for (d, y), s in series.items()
                if d == dest and y in train_years and ok[(d, y)]
                for x in s.daily.values()
                if x > 0
            ]
            out[dest] = list(np.percentile(v, [25, 60, 85])) if v else [1.0, 2.0, 3.0]
        return out

    caps = {}
    for dest in P.DESTS:
        peak = max(max(s.daily.values(), default=0) for (d, _y), s in series.items() if d == dest)
        caps[dest] = float(round(CAP_FACTOR * peak, -2))

    # Selection on the season before the first test season: objective l2 vs l1.
    t0 = years[-2] if years[-1] == 2026 else years[-1]  # latest complete season
    sel_val = t0 - 1
    ctx_sel = ctx_for({y for y in years if y < sel_val})
    tr = rows(ctx_sel, series, [k for k in series if k[1] < sel_val and ok[k]])
    va = rows(ctx_sel, series, [k for k in series if k[1] == sel_val and ok[k]])
    sel = {}
    for obj in ("regression", "regression_l1"):
        for g in GRID:
            CHOSEN.clear()
            CHOSEN.update(g)
            p = fit(tr, obj).predict(va[list(P.FEATURES)]) * va["_scale"].to_numpy()
            key = (
                f"{obj} leaves={g['num_leaves']} min_leaf={g['min_data_in_leaf']} "
                f"rounds={g['rounds']}"
            )
            sel[key] = (float(np.mean(np.abs(va["_y"].to_numpy() - p))), obj, g)
    best = min(sel, key=lambda k: sel[k][0])
    objective = sel[best][1]
    CHOSEN.clear()
    CHOSEN.update(sel[best][2])
    sel = {k: round(v[0], 1) for k, v in sel.items()}
    print("selection (validation MAE on", sel_val, "):", best, sel[best])

    metrics = {
        "label": "REAL public data; daily values partly ESTIMATED (see DATA_CARD.md)",
        "selection": {"validation_season": sel_val, "validation_mae": sel, "chosen": best},
        "seasons": {
            f"{d}_{y}": {
                "anchors": len(s.anchors) - 1,
                "days": len(s.daily),
                "usable": ok[(d, y)],
                "basis_counts": pd.Series(list(s.basis.values())).value_counts().to_dict(),
                "dropped": s.dropped,
            }
            for (d, y), s in series.items()
        },
        "tests": {},
    }
    final = None
    for T in [y for y in (t0, 2026) if y in years]:
        edges = edges_for({y for y in years if y < T})
        models, cq, train, test, res, device, ctx = run_test(
            ctx_for, series, ok, T, objective, edges, caps
        )
        m = evaluate(res, edges)
        m["failure_analysis"] = failure_analysis(res)
        m["conformal_q_scaled"] = cq
        m["xgb_device"] = device
        m["train_seasons"] = sorted({int(y) for y in train["_season"].unique()})
        metrics["tests"][str(T)] = m
        res.to_csv(
            ARTIFACT_DIR / f"test_predictions_{T}.csv", index=False
        ) if ARTIFACT_DIR.exists() else None
        final = (models, cq, ctx, train, edges, T, res)
        print(
            f"test {T}: daily MAE",
            {k: round(v["mae"]) for k, v in m["daily"].items()},
            "coverage",
            round(m["range80"]["coverage"], 3),
            "bands",
            m["band_accuracy"],
        )

    models, cq, ctx, train, edges, T, res = final
    # Deployed model = the final model of the last test (trained on every season before T).
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    res.to_csv(ARTIFACT_DIR / f"test_predictions_{T}.csv", index=False)
    for k, b in models.items():
        b.save_model(str(ARTIFACT_DIR / f"lgbm_{k}.txt"))
    deploy_edges = edges_for(set(years))  # bands for display use every real season
    ctx_dep = make_context(seasons, gaz, fest, school, series, ctx.scale, weather)
    summary = {
        str(t): {
            "daily_mae": {k: round(v["mae"]) for k, v in m["daily"].items()},
            "coverage80": round(m["range80"]["coverage"], 3),
        }
        for t, m in metrics["tests"].items()
    }
    bundle = build_bundle(models, cq, ctx_dep, series, ok, train, deploy_edges, caps, summary)
    (ARTIFACT_DIR / "bundle.json").write_text(
        json.dumps(bundle, separators=(",", ":")), encoding="utf-8", newline="\n"
    )
    metrics["deployed"] = {
        "trained_on": bundle["trained_on_seasons"],
        "objective": objective,
        "conformal_q_scaled": cq,
        "caps": caps,
        "band_edges": deploy_edges,
        "guard": GUARD,
        "params": {**PARAMS, **CHOSEN},
    }
    (ARTIFACT_DIR / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str), encoding="utf-8", newline="\n"
    )
    (ARTIFACT_DIR / "feature_list.json").write_text(
        json.dumps(list(P.FEATURES), indent=2), encoding="utf-8", newline="\n"
    )
    target.to_frame(series).to_csv(
        ARTIFACT_DIR / "daily_target.csv", index=False, lineterminator="\n"
    )
    export()
    print("wrote", ARTIFACT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
