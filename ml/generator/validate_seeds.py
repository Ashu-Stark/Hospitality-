"""Multi-seed SIGNAL check: pool the difficulty probes across several generator seeds.

Run from ml/:  python run.py validate-seeds            (seeds 42 43 44)
               python run.py validate-seeds 48 49 50   (fresh-seed confirmation)

For each seed the WHOLE pipeline is regenerated in memory (occupancy, staff, attrition with its
intercept calibrated to target_annual_attrition) with the config in config.yaml; nothing is
written. Each seed's expanding-window probe predictions (PERMANENT staff, 90-day gap before
each test year) are converted to within-(seed, year) percentile ranks and pooled, giving one
ROC-AUC over ~150 leavers. The checks are the same as python run.py validate's
(validate_signal.probe_checks) but on the pool.

These bands are generator-difficulty targets chosen by this project, not real-world benchmarks;
the planted drivers make every number a demonstration of the mechanism, never real accuracy.
Exits 1 if a pooled check fails.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import pandas as pd

from ml.generator.calibrate import DEFAULT_CALIBRATION_PATH, calibrate_intercept, load_prior
from ml.generator.config import GeneratorConfig, load_config
from ml.generator.run_occupancy import generate_daily
from ml.generator.run_staff import generate_staff
from ml.generator.validate_occupancy import print_table
from ml.generator.validate_signal import (
    SignalNumbers,
    no_driver_check,
    probe_checks,
    signal_numbers,
    summarise_probes,
)

DEFAULT_SEEDS = (42, 43, 44)


@dataclass(frozen=True)
class SeedRun:
    seed: int
    numbers: SignalNumbers


def run_seed(base: GeneratorConfig, seed: int) -> SeedRun:
    cfg = base.model_copy(update={"seed": seed})
    staff = generate_staff(cfg, generate_daily(cfg)[2])
    cal = calibrate_intercept(cfg, staff.employee, staff.employee_latent, staff.dept_week_load,
                              prior=load_prior(DEFAULT_CALIBRATION_PATH))
    return SeedRun(seed, signal_numbers(cal.result, cfg))


def pooled_predictions(runs: list[SeedRun]) -> pd.DataFrame:
    return pd.concat([r.numbers.predictions.assign(seed=r.seed) for r in runs],
                     ignore_index=True)


def pooled_no_driver_share(runs: list[SeedRun]) -> float:
    exits = sum(r.numbers.exits_considered for r in runs)
    no_driver = sum(r.numbers.no_driver_share * r.numbers.exits_considered for r in runs)
    return no_driver / exits if exits else 0.0


def seed_table(runs: list[SeedRun]) -> pd.DataFrame:
    rows = []
    for r in runs:
        p = r.numbers.probes
        rows.append({
            "seed": r.seed,
            "attrition": round(r.numbers.attrition, 3),
            "leavers": p.leavers,
            "rule_b": round(p.rule.auc_rank_pooled, 3),
            "rule_a": round(p.rule.auc_mean_years, 3),
            "xgboost_b": round(p.scorers["xgboost"].auc_rank_pooled, 3),
            "logistic_b": round(p.scorers["logistic"].auc_rank_pooled, 3),
            "best": p.best_model,
            "best_a": round(p.best.auc_mean_years, 3),
            "gap_b": round(p.gap, 3),
            "no_driver": round(r.numbers.no_driver_share, 3),
            "hi_driver_stayers": round(r.numbers.high_driver_stayers, 3),
        })
    return pd.DataFrame(rows)


def main(seeds: tuple[int, ...] = DEFAULT_SEEDS) -> int:
    base = load_config()
    runs = [run_seed(base, s) for s in seeds]
    preds = pooled_predictions(runs)
    pooled = summarise_probes(preds, ["seed", "test_year"])
    scope = f"seeds {min(seeds)}-{max(seeds)}"
    checks = [*probe_checks(pooled, scope), no_driver_check(pooled_no_driver_share(runs), scope)]
    print(f"Multi-seed SIGNAL check (SYNTHETIC data), seeds {', '.join(map(str, seeds))}: "
          f"{pooled.rows} permanent-staff test rows, {pooled.leavers} leavers, base rate "
          f"{pooled.base_rate:.3f}. (b) = ranked pooled ROC-AUC (pass/fail), (a) = mean of "
          f"per-year ROC-AUCs.\n")
    print_table(checks)
    print("\nPooled, all scorers:")
    for name, s in pooled.scorers.items():
        print(f"  {name:14s} (b) {s.auc_rank_pooled:.3f}  (a) {s.auc_mean_years:.3f}  "
              f"PR-AUC(b) {s.pr_auc_rank_pooled:.3f}")
    print(f"  best model: {pooled.best_model}, gap over rule {pooled.gap:+.3f}")
    print("\nPer seed:")
    print(seed_table(runs).to_string(index=False))
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main(tuple(int(a) for a in sys.argv[1:]) or DEFAULT_SEEDS))
