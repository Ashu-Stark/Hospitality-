"""Check that every packaged artifact loads and works WITHOUT retraining (Task T10).

For each model in package.SPECS: all required files exist, model.joblib loads, and the stored
dataset hash is compared with the SYNTHETIC data on disk (a mismatch is reported: the artifact
was trained on different data). Then the T9 interfaces run on tiny examples. Used to verify a
fresh clone: python run.py check-artifacts
"""

from __future__ import annotations

import json
import sys

import joblib
import pandas as pd

from ml.eval.package import REQUIRED_FILES, SPECS, dataset_hash
from ml.features.build_pulse_features import PULSE_FEATURES
from ml.features.build_workload_features import WORKLOAD_FEATURES


def check_files() -> list[tuple[str, bool, str]]:
    results = []
    for spec in SPECS:
        missing = [f for f in REQUIRED_FILES if not (spec.directory / f).exists()]
        if missing:
            results.append((f"{spec.name}/{spec.version} files", False, f"missing {missing}"))
            continue
        joblib.load(spec.directory / "model.joblib")
        stored = json.loads((spec.directory / "dataset_hash.json").read_text("utf-8"))
        same = stored["combined_sha256"] == dataset_hash(spec.inputs)["combined_sha256"]
        results.append((f"{spec.name}/{spec.version} loads; dataset hash matches data on disk",
                        same, stored["combined_sha256"][:12]))
    return results


def check_interfaces() -> list[tuple[str, bool, str]]:
    from ml import attrition, forecast

    f = forecast.predict("2029-12-01", "2029-12-03")
    week = attrition.api.latest_week()
    s = attrition.score(week, ["H901"])[0]
    r = attrition.rescore("H901", attrition.protected_weekends_off("H901", 2))
    pulse = joblib.load(SPECS[2].directory / "model.joblib")
    workload = joblib.load(SPECS[3].directory / "model.joblib")
    row = lambda feats: pd.DataFrame([{c: 0 for c in feats}])  # noqa: E731
    row_p = row(PULSE_FEATURES).assign(department="kitchen", role="cook",
                                       contract_type="permanent")
    row_w = row(WORKLOAD_FEATURES).assign(department="kitchen")
    return [
        ("forecast.predict", len(f.days) == 3, f"{[d.mean for d in f.days]}"),
        ("attrition.score", 0 <= s.risk <= 1, f"H901 risk {s.risk} [{s.band}]"),
        ("attrition.rescore", r.after.risk >= 0, f"{r.before.risk} -> {r.after.risk}"),
        ("pulse model predicts", len(pulse.predict(row_p)) == 1, "ok"),
        ("workload model predicts", len(workload.predict(row_w)) == 1, "ok"),
    ]


def main() -> int:
    checks = check_files() + check_interfaces()
    print("Artifact check (SYNTHETIC data, no retraining):")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
