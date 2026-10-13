"""Package every trained model (Task T10): artifacts/<name>/<version>/ gets model.joblib (written
by its trainer), metrics.json, feature_list.json, dataset_hash.json and model_card.md.

The dataset hash is the SHA-256 of every SYNTHETIC input file the model was trained on, plus a
combined hash, so anyone can tell whether an artifact matches the data on disk
(check_artifacts.py compares them). Never trains; run after the trainers (python run.py eval).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ml.features.build_pulse_features import PULSE_FEATURES
from ml.features.build_workload_features import WORKLOAD_FEATURES
from ml.generator.config import load_config

ML_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ML_ROOT / "data"
ARTIFACTS = ML_ROOT / "artifacts"
METRICS_DIR = ML_ROOT / "docs" / "metrics"
REQUIRED_FILES = ("model.joblib", "metrics.json", "feature_list.json", "dataset_hash.json",
                  "model_card.md")
ATTRITION_SPLIT_INPUTS = ("employee_v2.csv", "weekly_behaviour.csv", "exits.csv",
                          "contract_renewals.csv", "pay_changes.csv")
HONESTY = ("**Planted-drivers honesty note.** All data is SYNTHETIC, produced by the seeded "
           "generator in ml/generator with ASSUMED parameters. The relationships the model finds "
           "were PLANTED by that generator, so every metric here shows the pipeline recovering "
           "a known mechanism. None of it is evidence of accuracy on real hotel data.")


@dataclass(frozen=True)
class ModelSpec:
    name: str
    version: str
    inputs: tuple[str, ...]
    intended_use: str
    data: str
    limitations: tuple[str, ...]
    metrics_table: Callable[[dict], list[str]]

    @property
    def directory(self) -> Path:
        return ARTIFACTS / self.name / self.version


def file_hash(path: Path) -> str:
    """SHA-256 with line endings normalised to LF, so Windows (CRLF) and Unix checkouts of the
    same committed file hash the same."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def dataset_hash(inputs: tuple[str, ...], data_dir: Path = DATA_DIR) -> dict:
    files = {name: file_hash(data_dir / name) for name in inputs}
    combined = hashlib.sha256("".join(f"{k}:{v}\n" for k, v in sorted(files.items())).encode())
    return {"synthetic": True, "seed": load_config().seed, "files": files,
            "combined_sha256": combined.hexdigest()}


def _forecast_rows(m: dict) -> list[str]:
    rows = ["| horizon | model MAPE | seasonal-naive MAPE | used | 80% band coverage "
            "(split-conformal) | T6 quantile-band coverage |", "|---|---|---|---|---|---|"]
    rows += [f"| {v['horizon_days']} d | {v['model_mape']:.1%} | {v['baseline_mape']:.1%} | "
             f"{v['used']} | {v['band_coverage']:.1%} | "
             f"{v.get('quantile_regression_band_coverage', float('nan')):.1%} |"
             for v in m.values()]
    return rows


COVERAGE_TARGET = (0.75, 0.85)  # T12 acceptance range for the nominal 80% band


def _forecast_extra(m: dict, _artifact: Path) -> list[str]:
    lo, hi = COVERAGE_TARGET
    misses = [f"{v['horizon_days']} d ({v['band_coverage']:.1%})" for v in m.values()
              if not lo <= v["band_coverage"] <= hi]
    verdict = (f"Outside the {lo:.0%}-{hi:.0%} target: {', '.join(misses)}; reported as is, not "
               "tuned." if misses else f"Every horizon is inside the {lo:.0%}-{hi:.0%} target.")
    return ["## Uncertainty band", "",
            "Split-conformal (T12): a twin of the forecaster trained only on targets before the "
            "calibration window (2024) is scored on that window; the (n + 1)-corrected 10th / 90th "
            "percentiles of its residuals are added to the point forecast. The point forecast "
            "itself is unchanged from T6. The twin has less history than the deployed model, so "
            "the band is likely a little conservative.", "", verdict, ""]


def _attrition_rows(m: dict) -> list[str]:
    rows = ["| segment | scorer | ROC-AUC | PR-AUC | precision | recall | base rate |",
            "|---|---|---|---|---|---|---|"]
    for seg, s in m.items():
        for name, t in s["test"].items():
            mark = " (winner)" if name == s["winner"] else ""
            rows.append(f"| {seg} | {name}{mark} | {t['roc_auc']:.3f} | {t['pr_auc']:.3f} | "
                        f"{t['precision']:.3f} | {t['recall']:.3f} | {t['base_rate']:.3f} |")
    return rows


def _attrition_extra(m: dict, artifact: Path) -> list[str]:
    drivers_path = artifact / "drivers.json"
    d = json.loads(drivers_path.read_text("utf-8")) if drivers_path.exists() else {}
    lines = ["## Risk bands (T12, seasonal rule since T12b)", "",
             "PERMANENT staff (band_basis model_rank): within each scoring week, active non-hero "
             "permanent staff are ranked by calibrated risk. high = the first ceil(10% x n) slots, "
             "watch = "
             "the next ceil(15% x n), low = the rest (shares ASSUMED, config.yaml). Staff with "
             "identical risk form a tie group that is never split: it takes a band only if it fits "
             "wholly in the remaining slots, otherwise the next lower band. The probability is "
             "still shown beside the band.", "",
             "SEASONAL staff (band_basis contract_date_rule): days to contract end <= 30 = high, "
             "31-60 = watch, else low (thresholds ASSUMED, config.yaml). A seasonal exit is a "
             "KNOWN date, not a prediction. About 96% of seasonal model risks were tied each week "
             "(the contract-date rule gives everyone whose contract ends more than 90 days out "
             "the same risk), so ranking them carried no information. This rule was chosen AFTER "
             "seeing those ties, not to place any hero.", "",
             "Why ceil-count for permanent staff: ceil-count was first chosen because the seasonal "
             "group has about 7 people, where a percentile rule (rank / n <= 10%) can never "
             "create a high band. The rule was chosen AFTER demo hero "
             "Sunita's rank had been seen. She sits ON the high / watch boundary (rank 5 of 48, "
             "risk 0.0905, between ranks 4 and 6), so her band is a ranking result, not a "
             "confident prediction.", "",
             "| hero | group | risk | model rank | band (used) | basis | percentile-rule band |",
             "|---|---|---|---|---|---|---|"]
    for h in d.get("hero_bands_last_week", {}).values():
        tie = " (tied)" if h["rank_is_tied"] else ""
        lines.append(f"| {h['name']} | {h['segment']} | {h['risk']:.4f} | {h['rank']} / "
                     f"{h['group_size']}{tie} | {h['band_used']} | {h['band_basis']} | "
                     f"{h['band_percentile_rule'] or 'n/a'} |")
    lines += ["", "Backtest (pooled test weeks 2027-2029), bands recomputed every week:", "",
              "| segment | scorer | precision in high | lift over base rate | leaver-weeks in "
              "high + watch | tied share per week |", "|---|---|---|---|---|---|"]
    for seg, s in m.items():
        for name, b in s.get("rank_bands_test", {}).items():
            mark = " (winner)" if name == s["winner"] else ""
            lines.append(f"| {seg} | {name}{mark} | {b['high_precision']:.3f} | "
                         f"{b['high_lift']}x (base {b['base_rate']:.3f}) | "
                         f"{b['leaver_weeks_in_high_or_watch']:.1%} | "
                         f"{b['tied_share_per_week_mean']:.2f} |")
    rule = m.get("contract_end", {}).get("contract_date_rule_bands_test")
    if rule:
        lines.append(f"| contract_end | contract-date RULE band (used since T12b) | "
                     f"{rule['high_precision']:.3f} | {rule['high_lift']}x (base "
                     f"{rule['base_rate']:.3f}) | {rule['leaver_weeks_in_high_or_watch']:.1%} | "
                     "n/a |")
    lines += ["", "Under model ranks, the big seasonal tie group overflowed the high and watch "
              "slots, so no seasonal employee was ever high or watch (the 0.0 row above); that "
              "is why seasonal staff now use the contract-date rule.", "",
              "## Explanation method (T12)", "",
              "Drivers come from the SAME model that produces the risk (the segment's calibrated "
              "winner): contributions in calibrated log-odds relative to the training mean. For "
              "the logistic winner that is Platt slope x coefficient x (standardised value - "
              "training mean), summed per driver category; for the contract-date rule it is the "
              "days-to-contract-end term. LightGBM TreeSHAP is kept only as a comparison "
              "(drivers.json).", "",
              "Driver support in the SYNTHETIC generator: overtime overload, stalled progression, "
              "low engagement, season-end exit and pay gap are planted. Clustered-leave burnout is "
              "WEAKLY SUPPORTED: the hazard has a weeks-without-leave term but no pre-festival "
              "leave term. Manager relationship is UNSUPPORTED (no signal at all).", "",
              "Demo checks (T12b): the earlier check \"Sunita has overtime overload AND "
              "clustered-leave burnout\" was REMOVED. It came from the hero script, written before "
              "we knew the generator never creates a pre-festival leave driver. It is replaced by "
              "two checks:", ""]
    for c in d.get("demo_checks", []):
        lines.append(f"- {'PASS' if c['passed'] else 'FAIL (reported, not tuned)'}: "
                     f"{c['check']}: {c['detail']}")
    return lines + [""]


EXTRA_SECTIONS = {"occupancy_forecast": _forecast_extra, "attrition": _attrition_extra}


def _regression_rows(m: dict) -> list[str]:
    rows = ["| model | test MAE | test RMSE | test R2 |", "|---|---|---|---|"]
    for key in ("baseline", "model"):
        t = m[key]["test"]
        rows.append(f"| {m[key]['model']} | {t['mae']:.4f} | {t['rmse']:.4f} | {t['r2']:.4f} |")
    return rows


SPECS = (
    ModelSpec(
        "occupancy_forecast", "v1",
        ("occupancy_daily.csv", "event_calendar.csv", "weather_daily.csv"),
        "Daily occupancy forecast 1, 7 and 30 days ahead with an 80% band and high / low demand "
        "alerts, for roster planning in a small hill hotel. Interface: forecast.predict.",
        "Daily SYNTHETIC occupancy, calendar and weather; train targets 2023-2024, test 2025 "
        "(split by time). One direct LightGBM model per horizon plus two quantile models.",
        ("The band is calibrated on one year (2024) of residuals; coverage can drift in a year "
         "unlike the calibration year.",
         "High-demand alerts (>= 0.90 forecast) are weak: low precision and recall in 2025.",
         "Only one synthetic property; the seasonality is the generator's assumption."),
        _forecast_rows),
    ModelSpec(
        "attrition", "v1",
        ("employee_v2.csv", "weekly_behaviour.csv", "weekly_signals.csv", "exits.csv",
         "contract_renewals.csv", "pay_changes.csv"),
        "Weekly 90-day exit risk per employee with a band (low / watch / high), the top-3 driver "
        "categories and playbook actions, to start a conversation, never to make a decision "
        "about a person. Interfaces: attrition.score, attrition.rescore (a SIMULATION).",
        "SYNTHETIC employee-weeks 2023-2029. Separate evaluations: resignation (permanent "
        "staff) and contract-end exit (seasonal staff). Expanding-window backtest, test years "
        "2027-2029, 90-day label gap; Platt calibration and threshold on the year before each "
        "test year. Heroes (demo employees) are never in training.",
        ("Few leavers (a few dozen in the pooled test years); rows are correlated "
         "employee-weeks, so the metrics are noisy.",
         "Logistic wins for resignations because the planted hazard IS logistic; that is a "
         "property of the synthetic data, not evidence for logistic on real data.",
         "Seasonal calibration is set by one validation year and over-predicts in the top bin.",
         "Logistic contributions are relative to the training mean, so a one-hot category the "
         "employee is NOT in moves the log-odds too; such context features are never shown as "
         "drivers. Manager relationship is UNSUPPORTED (no signal in the data).",
         "Clustered-leave burnout is WEAKLY SUPPORTED: pre-festival leave was never planted "
         "in the hazard, so only weeks without leave pushes that category up.",
         "Seasonal bands come from the contract date, not the model: they flag who is about to "
         "reach a known end date, not who might resign.",
         "Bands are ranks: someone always fills the high slots, even in a calm week."),
        _attrition_rows),
    ModelSpec(
        "pulse", "v1", ATTRITION_SPLIT_INPUTS,
        "Next week's pulse score (1-5) per employee, as an early engagement warning.",
        "SYNTHETIC weekly pulse; time split 60/20/20 by week with a label embargo.",
        ("Gain over the naive 'copy this week' baseline is small (see table).",
         "Pulse is generated from latent traits the model never sees; real surveys are noisier."),
        _regression_rows),
    ModelSpec(
        "workload", "v1",
        ("dept_week_load_dynamic.csv", "event_calendar.csv", *ATTRITION_SPLIT_INPUTS),
        "Next week's department load ratio (required / available hours), for staffing.",
        "SYNTHETIC department-weeks; same week windows as the attrition reference split.",
        ("Workload standards are calibrated placeholders (ASSUMED) pending the HM student.",
         "Only ~8 departments: few rows per week."),
        _regression_rows),
)
FEATURES = {"pulse": PULSE_FEATURES, "workload": WORKLOAD_FEATURES}


def regression_metrics(name: str, metrics_dir: Path = METRICS_DIR) -> dict:
    read = lambda f: json.loads((metrics_dir / f).read_text("utf-8"))  # noqa: E731
    model = read(f"{name}_model.json")
    model.pop("feature_importance_gain", None)
    return {"synthetic": True, "baseline": read(f"{name}_naive.json"), "model": model}


def model_card(spec: ModelSpec, metrics: dict, hashes: dict) -> str:
    extra = EXTRA_SECTIONS.get(spec.name)
    lines = [f"# Model card: {spec.name} {spec.version} (SYNTHETIC data)", "",
             "## Intended use", "", spec.intended_use, "", "## Data", "", spec.data, "",
             f"Dataset hash (combined SHA-256 of {len(hashes['files'])} input files, seed "
             f"{hashes['seed']}): `{hashes['combined_sha256'][:16]}...` (dataset_hash.json).", "",
             "## Metrics vs baseline (test)", "", *spec.metrics_table(metrics), "",
             *(extra(metrics, spec.directory) if extra else []),
             "## Limitations", "", *[f"- {x}" for x in spec.limitations], "", HONESTY, ""]
    return "\n".join(lines)


def package(spec: ModelSpec, data_dir: Path = DATA_DIR) -> list[Path]:
    out = spec.directory
    if not (out / "model.joblib").exists():
        raise FileNotFoundError(f"{out / 'model.joblib'} missing: run the trainer first")
    written = []
    if spec.name in FEATURES:  # trainers of the older models write metrics to docs/metrics
        (out / "metrics.json").write_text(json.dumps(regression_metrics(spec.name), indent=2)
                                          + "\n", encoding="utf-8")
        (out / "feature_list.json").write_text(json.dumps(FEATURES[spec.name], indent=2) + "\n",
                                               encoding="utf-8")
        written += [out / "metrics.json", out / "feature_list.json"]
    hashes = dataset_hash(spec.inputs, data_dir)
    (out / "dataset_hash.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    metrics = json.loads((out / "metrics.json").read_text("utf-8"))
    (out / "model_card.md").write_text(model_card(spec, metrics, hashes), encoding="utf-8")
    return written + [out / "dataset_hash.json", out / "model_card.md"]


def main() -> int:
    print("Packaging SYNTHETIC-data models:")
    for spec in SPECS:
        for p in package(spec):
            print(f"  wrote {p.relative_to(ML_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
