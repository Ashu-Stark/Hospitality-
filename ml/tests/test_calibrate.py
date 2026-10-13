from pathlib import Path

import pytest

from ml.generator.calibrate import (
    Prior,
    calibrate_intercept,
    config_fingerprint,
    load_prior,
    save_calibration,
)
from ml.generator.validate_attrition import result_hash

# Slow: calibration searches / full pipeline runs. Run with python run.py test --all.
pytestmark = pytest.mark.slow

N_WEEKS = 26


@pytest.fixture(scope="module")
def short(cfg, staff_frames):
    """Half a year of weeks and a small search budget, so calibration tests stay fast."""
    load = staff_frames.dept_week_load
    weeks = sorted(load["week_start"].unique())[:N_WEEKS]
    small = cfg.attrition.calibration.model_copy(
        update={"max_iterations": 6, "refine_steps": 0, "tolerance": 0.05})
    c = cfg.model_copy(update={"attrition": cfg.attrition.model_copy(
        update={"calibration": small})})
    s = staff_frames
    return c, (s.employee, s.employee_latent, load[load["week_start"].isin(weeks)])


@pytest.fixture(scope="module")
def full(short):
    cfg, inputs = short
    return calibrate_intercept(cfg, *inputs)


def test_full_search_without_prior(full) -> None:
    assert full.mode == "full"
    assert 1 <= full.iterations <= 6
    assert full.intercept == full.result.intercept


def _prior(cal) -> Prior:
    return Prior(cal.intercept, cal.achieved_rate, cal.target_rate, cal.fingerprint)


def test_matching_prior_is_reused_in_one_simulation(short, full) -> None:
    cfg, inputs = short
    again = calibrate_intercept(cfg, *inputs, prior=_prior(full))
    assert again.mode == "reused" and again.iterations == 1
    assert again.intercept == full.intercept
    assert result_hash(again.result) == result_hash(full.result)


def test_changed_config_searches_near_prior(short, full) -> None:
    cfg, inputs = short
    h = cfg.attrition.hazard.model_copy(update={"coef_overtime_per_hour": 0.31})
    tweaked = cfg.model_copy(update={"attrition": cfg.attrition.model_copy(update={"hazard": h})})
    assert config_fingerprint(tweaked) != config_fingerprint(cfg)
    cal = calibrate_intercept(tweaked, *inputs, prior=_prior(full))
    assert cal.mode in {"local", "full"} and cal.iterations > 1


def test_changed_target_searches_full_range(short, full) -> None:
    cfg, inputs = short
    other = cfg.model_copy(update={"target_annual_attrition": 0.30})
    cal = calibrate_intercept(other, *inputs, prior=_prior(full))
    assert cal.mode == "full" and cal.target_rate == 0.30


def test_prior_with_wrong_rate_is_not_reused(short, full) -> None:
    """Same fingerprint but a different saved rate (e.g. code changed): search again."""
    cfg, inputs = short
    stale = Prior(full.intercept, full.achieved_rate + 0.123, full.target_rate, full.fingerprint)
    assert calibrate_intercept(cfg, *inputs, prior=stale).mode != "reused"


def test_save_and_load_round_trip(full, tmp_path: Path) -> None:
    path = save_calibration(full, tmp_path / "cal.json")
    prior = load_prior(tmp_path / "missing.json", path)
    assert prior == Prior(round(full.intercept, 6), round(full.achieved_rate, 6),
                          full.target_rate, full.fingerprint)
    assert load_prior(tmp_path / "missing.json") is None


def test_fingerprint_is_stable(cfg) -> None:
    assert config_fingerprint(cfg) == config_fingerprint(cfg.model_copy())


def test_fingerprint_ignores_unrelated_sections() -> None:
    from ml.generator.config import load_config

    cfg = load_config()
    am = cfg.attrition_model.model_copy(update={"band_high_share": 0.2})
    fc = cfg.forecast.model_copy(update={"alert_high_occupancy": 0.95})
    unrelated = cfg.model_copy(update={"attrition_model": am, "forecast": fc})
    assert config_fingerprint(unrelated) == config_fingerprint(cfg)
    seeded = cfg.model_copy(update={"seed": cfg.seed + 1})
    assert config_fingerprint(seeded) != config_fingerprint(cfg)
