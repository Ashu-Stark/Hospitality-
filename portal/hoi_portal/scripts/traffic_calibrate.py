r"""Fit small corrections to the traffic prediction from stored live observations (`traffic_observations`).

    cd portal
    ..\.venv\Scripts\python.exe -m hoi_portal.scripts.traffic_calibrate            # fit and save
    ..\.venv\Scripts\python.exe -m hoi_portal.scripts.traffic_calibrate --dry-run  # report only

The prediction starts expert-weighted (traffic.yaml). For each destination with at least
calibration.min_observations observations, this fits one correction per time-of-day bucket: the ridge-shrunk mean
residual  bias = sum(observed - predicted) / (n_bucket + ridge_lambda), clamped to +/- max_bias, which is the
ridge-regression solution for a per-bucket intercept. Pure Python (no numpy / scikit-learn on the deployed portal).
Fewer observations -> "not enough observations yet" and no correction. Reads MONGODB_URI from the environment or the
root .env (never printed).
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from .besttime_refresh import load_env


def fit(observations: list[dict], cfg: dict) -> dict:
    """{destination_id: {"n": int, "bias": [per bucket], "mae_before": x, "mae_after": y} | {"n": int, "enough": False}}."""
    cal = cfg["calibration"]
    by_dest: dict[str, list[dict]] = defaultdict(list)
    for o in observations:
        if o.get("observed_index") is not None and o.get("predicted_index") is not None:
            by_dest[o["destination_id"]].append(o)
    out = {}
    for dest, obs in sorted(by_dest.items()):
        n = len(obs)
        if n < cal["min_observations"]:
            out[dest] = {"n": n, "enough": False}
            continue
        biases = []
        for s, e in cal["buckets"]:
            res = [o["observed_index"] - o["predicted_index"] for o in obs if s <= o["hour"] < e]
            b = sum(res) / (len(res) + cal["ridge_lambda"]) if res else 0.0
            biases.append(round(max(-cal["max_bias"], min(cal["max_bias"], b)), 2))

        def bias_at(h: int, biases=biases) -> float:
            return next((v for (s, e), v in zip(cal["buckets"], biases) if s <= h < e), 0.0)

        before = sum(abs(o["observed_index"] - o["predicted_index"]) for o in obs) / n
        after = sum(abs(o["observed_index"] - max(0, min(100, o["predicted_index"] + bias_at(o["hour"])))) for o in obs) / n
        out[dest] = {"n": n, "enough": True, "bias": biases, "mae_before": round(before, 1), "mae_after": round(after, 1)}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fit traffic prediction corrections from live observations.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-env-file", action="store_true")
    a = ap.parse_args(argv)
    if not a.no_env_file:
        load_env()
    from .. import config, mongo
    from ..services import traffic

    config.reload()
    mongo.reset()
    cfg = traffic.CFG
    obs = list(
        mongo.db().traffic_observations.find({}, {"_id": 0, "destination_id": 1, "hour": 1, "observed_index": 1, "predicted_index": 1})
    )
    res = fit(obs, cfg)
    need = cfg["calibration"]["min_observations"]
    if not res:
        print(f"not enough observations yet: 0 stored (need {need} per destination).")
        return 0
    saved = 0
    for dest, r in res.items():
        if not r["enough"]:
            print(f"{dest}: not enough observations yet ({r['n']}/{need}); no correction.")
            continue
        print(f"{dest}: n={r['n']} bias per bucket {r['bias']} | mean abs error {r['mae_before']} -> {r['mae_after']}")
        if not a.dry_run:
            doc = {
                "destination_id": dest,
                "n": r["n"],
                "bias": r["bias"],
                "buckets": cfg["calibration"]["buckets"],
                "fitted_at": mongo.now(),
                "mae_before": r["mae_before"],
                "mae_after": r["mae_after"],
                "model_version": cfg["version"],
            }
            mongo.db().traffic_calibration.update_one({"destination_id": dest}, {"$set": doc}, upsert=True)
            saved += 1
    traffic.invalidate_calibration()
    print(f"saved corrections for {saved} destination(s)" + (" (dry run: nothing saved)" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
