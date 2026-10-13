from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.generator.validate_occupancy import (
    busiest_other_month,
    frame_hash,
    run_checks,
    save_plots,
    seasonal_naive_mape,
    sold_out_share,
)


def test_sold_out_share_counts_only_full_days_in_months() -> None:
    df = pd.DataFrame(
        {"month": [5, 5, 5, 6, 7, 7], "rooms_sold": [45, 44, 45, 10, 45, 45]}
    )
    assert sold_out_share(df, 45, (5, 6)) == pytest.approx(0.5)
    assert sold_out_share(df, 45, (7,)) == pytest.approx(1.0)


def test_sold_out_check_fails_when_peak_saturated(cfg, generated) -> None:
    saturated = generated[2].copy()
    peak = saturated["month"].isin([5, 6])
    saturated.loc[peak, "rooms_sold"] = cfg.property.rooms
    checks = {c.name: c for c in run_checks(saturated, cfg, frame_hash(saturated))}
    sold_out = next(c for name, c in checks.items() if name.startswith("sold-out share"))
    assert not sold_out.passed and sold_out.detail == "100.0%"


def _check(checks: list, prefix: str):
    return next(c for c in checks if c.name.startswith(prefix))


def test_busiest_other_month_excludes_peak() -> None:
    df = pd.DataFrame(
        {"month": [5, 6, 10, 10, 12], "occupancy_pct": [0.95, 0.9, 0.6, 0.8, 0.75]}
    )
    assert busiest_other_month(df, (5, 6)) == (12, pytest.approx(0.75))


def test_peak_upper_bound_check_fails_when_too_high(cfg, generated) -> None:
    daily = generated[2].copy()
    daily.loc[daily["month"].isin([5, 6]), "occupancy_pct"] = 0.95
    checks = run_checks(daily, cfg, frame_hash(daily))
    assert not _check(checks, "May-Jun mean occupancy <=").passed


def test_peak_is_highest_month_check_fails_when_rival_busier(cfg, generated) -> None:
    daily = generated[2].copy()
    daily.loc[daily["month"] == 12, "occupancy_pct"] = 0.99
    checks = run_checks(daily, cfg, frame_hash(daily))
    highest = _check(checks, "May-Jun is the highest month")
    assert not highest.passed and "month 12 0.990" in highest.detail


def test_new_peak_checks_pass_on_default_data(cfg, generated) -> None:
    daily = generated[2]
    checks = run_checks(daily, cfg, frame_hash(daily))
    assert _check(checks, "May-Jun mean occupancy <=").passed
    assert _check(checks, "May-Jun is the highest month").passed


def test_seasonal_naive_mape_perfect_and_known() -> None:
    dates = pd.date_range("2023-01-01", "2025-12-31", freq="D")
    weekly = np.where(dates.dayofweek >= 4, 0.6, 0.5)
    df = pd.DataFrame({"date": dates, "occupancy_pct": weekly})
    assert seasonal_naive_mape(df, 2025) == pytest.approx(0.0)
    # Year 3 scaled by 1.25 -> |1.25y - y| / 1.25y = 0.2 on 364 of 365 days; Dec 31 looks
    # back 364 days to Jan 1 of the same (scaled) year, so its error is 0.
    df2 = df.assign(occupancy_pct=np.where(dates.year == 2025, weekly * 1.25, weekly))
    assert seasonal_naive_mape(df2, 2025) == pytest.approx(0.2 * 364 / 365)


def test_frame_hash_changes_with_values() -> None:
    a = pd.DataFrame({"x": [1, 2]})
    assert frame_hash(a) == frame_hash(a.copy())
    assert frame_hash(a) != frame_hash(pd.DataFrame({"x": [1, 3]}))


def test_checks_pass_on_default_data(cfg, generated) -> None:
    daily = generated[2]
    checks = run_checks(daily, cfg, frame_hash(daily))
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]


def test_save_plots(generated, tmp_path: Path) -> None:
    paths = save_plots(generated[2], tmp_path)
    assert len(paths) == 3 and all(p.stat().st_size > 0 for p in paths)
