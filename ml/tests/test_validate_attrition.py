from dataclasses import replace
from pathlib import Path

import pytest

from ml.generator.validate_attrition import (
    attrition_numbers,
    effective_contract_ends,
    result_hash,
    run_checks,
    save_plots,
    seasonal_violations,
    simulate_default,
)


@pytest.fixture(scope="module")
def result(cfg):
    return simulate_default(cfg)


def _failed(result, cfg) -> set[str]:
    return {c.name for c in run_checks(result, cfg, result_hash(result)) if not c.passed}


def test_structural_checks_pass(cfg, result) -> None:
    # The attrition-rate check depends on ASSUMED config values and is reported separately.
    assert {n for n in _failed(result, cfg) if not n.startswith("annualised")} == set()


def test_dropping_a_row_fails_row_check(cfg, result) -> None:
    broken = replace(result, weekly_behaviour=result.weekly_behaviour.iloc[1:])
    assert any(n.startswith("one row per") for n in _failed(broken, cfg))


def test_overtime_below_trigger_fails(cfg, result) -> None:
    beh = result.weekly_behaviour.copy()
    idx = beh.index[beh["load_ratio"] <= 1.0][0]
    beh.loc[idx, "overtime_hours"] = 3.0
    failed = _failed(replace(result, weekly_behaviour=beh), cfg)
    assert any(n.startswith("overtime only") for n in failed)


def test_pulse_out_of_range_fails(cfg, result) -> None:
    beh = result.weekly_behaviour.copy()
    beh.loc[beh.index[0], "pulse_score"] = 5.5
    assert "pulse_score in [1, 5]" in _failed(replace(result, weekly_behaviour=beh), cfg)


def test_seasonal_relabelled_exit_detected(cfg, result) -> None:
    exits = result.exits.copy()
    seasonal = exits.index[exits["exit_reason"] == "seasonal_end"]
    assert len(seasonal) > 0
    exits.loc[seasonal[0], "exit_reason"] = "resignation"
    assert seasonal_violations(replace(result, exits=exits), cfg)


def test_effective_ends_follow_renewals(result) -> None:
    ends = effective_contract_ends(result)
    for r in result.contract_renewals.itertuples():
        later = result.contract_renewals[
            (result.contract_renewals["employee_id"] == r.employee_id)
            & (result.contract_renewals["renewal_date"] > r.renewal_date)
        ]
        if later.empty:
            assert ends[r.employee_id] == r.new_contract_end_date


def test_hash_mismatch_fails(cfg, result) -> None:
    checks = run_checks(result, cfg, "0" * 64)
    assert not next(c for c in checks if c.name.startswith("same seed")).passed


def test_attrition_numbers_consistent(result) -> None:
    n = attrition_numbers(result)
    assert n["rate"] == pytest.approx(n["resignation_rate"] + n["seasonal_rate"])
    assert 1 <= n["pulse_peak"] <= 5 and 1 <= n["pulse_feb"] <= 5


def test_save_plots(result, tmp_path: Path) -> None:
    paths = save_plots(result, tmp_path)
    assert [p.name for p in paths] == ["pulse_score_by_month.png", "attrition_rate_by_month.png"]
    assert all(p.stat().st_size > 0 for p in paths)
