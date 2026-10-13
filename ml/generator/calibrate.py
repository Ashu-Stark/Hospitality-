"""Calibrate the resignation-hazard intercept to target_annual_attrition (SYNTHETIC data).

Every trial re-runs the full weekly simulation from the SAME attrition random stream, so the
annual attrition rate is a deterministic function of the intercept. It is not perfectly
monotone (an exit reshuffles later random draws), so a bisection is followed, if it misses the
tolerance, by a local grid scan around the best intercept.

Speed and reproducibility: the last calibration is saved in data/attrition_calibration.json
with a fingerprint of the attrition-relevant config sections. If the fingerprint matches and
the saved intercept reproduces the saved rate exactly, it is reused (one simulation), so the
same config always gives the same intercept and byte-identical outputs. If the config changed
but the target did not, the search starts in a bracket around the saved intercept. With no
saved calibration, or a different target, the full range from config.yaml
(attrition.calibration) is searched.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ml.generator.attrition import AttritionResult, annual_attrition_rate, simulate_weekly
from ml.generator.config import GeneratorConfig
from ml.generator.rng import stream_rngs

CALIBRATION_FILE = "attrition_calibration.json"
DEFAULT_CALIBRATION_PATH = Path(__file__).resolve().parents[1] / "data" / CALIBRATION_FILE
RATE_DECIMALS = 6  # saved / compared precision of the achieved rate


@dataclass(frozen=True)
class Prior:
    """A previously saved calibration."""

    intercept: float
    achieved_rate: float
    target_rate: float
    fingerprint: str


@dataclass(frozen=True)
class Calibration:
    intercept: float
    achieved_rate: float
    target_rate: float
    iterations: int  # simulations run
    mode: str  # "reused", "local" or "full"
    fingerprint: str
    result: AttritionResult  # the simulation run at the chosen intercept


# Config sections the attrition simulation never reads (T12): editing them must not make a saved
# calibration stale. signals / skills use their own random streams after the simulation;
# forecast and attrition_model are downstream models; label_horizon_days only labels the result.
NOT_ATTRITION_RELEVANT = frozenset({"signals", "skills", "forecast", "attrition_model",
                                    "label_horizon_days"})


def config_fingerprint(cfg: GeneratorConfig) -> str:
    """Hash of the attrition-relevant config sections only (everything that can change the
    simulated exits: seed, property, occupancy / weather chain, roles, staff, workload,
    attrition, target rate)."""
    relevant = cfg.model_dump_json(exclude=set(NOT_ATTRITION_RELEVANT))
    return hashlib.sha256(relevant.encode("utf-8")).hexdigest()[:16]


def load_prior(*paths: Path) -> Prior | None:
    """The first readable saved calibration among `paths` (None if there is none)."""
    for path in paths:
        if path.exists():
            rec = json.loads(path.read_text(encoding="utf-8"))
            return Prior(rec["intercept"], rec["achieved_annual_attrition"],
                         rec["target_annual_attrition"], rec.get("config_fingerprint", ""))
    return None


def save_calibration(cal: Calibration, path: Path) -> Path:
    path.write_text(json.dumps({
        "intercept": round(cal.intercept, 6),
        "achieved_annual_attrition": round(cal.achieved_rate, RATE_DECIMALS),
        "target_annual_attrition": cal.target_rate,
        "simulations_run": cal.iterations,
        "search_mode": cal.mode,
        "config_fingerprint": cal.fingerprint,
    }, indent=2) + "\n", encoding="utf-8")
    return path


def simulate_at(
    cfg: GeneratorConfig,
    intercept: float,
    employee: pd.DataFrame,
    latent: pd.DataFrame,
    load: pd.DataFrame,
) -> AttritionResult:
    """One full simulation from a fresh copy of the attrition stream."""
    (rng,) = stream_rngs(cfg.seed, "attrition")
    return simulate_weekly(cfg, rng, employee, latent, load, intercept)


Trial = tuple[float, float, AttritionResult]  # (intercept, rate, result)


def _search(
    cfg: GeneratorConfig, run: Callable[[float], Trial], lo: float, hi: float
) -> tuple[Trial, int]:
    """Bisection in [lo, hi], then a local grid scan if the tolerance was missed."""
    c = cfg.attrition.calibration
    target = cfg.target_annual_attrition
    best: Trial | None = None
    sims = 0
    for _ in range(c.max_iterations):
        trial = run((lo + hi) / 2)
        sims += 1
        if best is None or abs(trial[1] - target) < abs(best[1] - target):
            best = trial
        if abs(trial[1] - target) <= c.tolerance:
            break
        lo, hi = (trial[0], hi) if trial[1] < target else (lo, trial[0])
    assert best is not None
    if abs(best[1] - target) > c.tolerance and c.refine_steps > 0:
        centre = best[0]
        for x in np.linspace(centre - c.refine_half_width, centre + c.refine_half_width,
                             c.refine_steps):
            trial = run(float(x))
            sims += 1
            if abs(trial[1] - target) < abs(best[1] - target):
                best = trial
    return best, sims


def calibrate_intercept(
    cfg: GeneratorConfig,
    employee: pd.DataFrame,
    latent: pd.DataFrame,
    load: pd.DataFrame,
    prior: Prior | None = None,
) -> Calibration:
    """Intercept whose annual attrition is closest to target_annual_attrition."""
    c = cfg.attrition.calibration
    target = cfg.target_annual_attrition
    fingerprint = config_fingerprint(cfg)

    def run(intercept: float) -> Trial:
        result = simulate_at(cfg, intercept, employee, latent, load)
        return intercept, annual_attrition_rate(result), result

    def done(trial: Trial, sims: int, mode: str) -> Calibration:
        return Calibration(trial[0], trial[1], target, sims, mode, fingerprint, trial[2])

    if prior is not None and prior.target_rate == target:
        if prior.fingerprint == fingerprint:
            trial = run(prior.intercept)
            if round(trial[1], RATE_DECIMALS) == round(prior.achieved_rate, RATE_DECIMALS):
                return done(trial, 1, "reused")
        lo_trial = run(prior.intercept - c.refine_half_width)
        hi_trial = run(prior.intercept + c.refine_half_width)
        if lo_trial[1] <= target <= hi_trial[1]:
            best, sims = _search(cfg, run, lo_trial[0], hi_trial[0])
            return done(best, sims + 2, "local")
    best, sims = _search(cfg, run, c.intercept_low, c.intercept_high)
    return done(best, sims, "full")
