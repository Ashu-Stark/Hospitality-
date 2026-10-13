import numpy as np
import pandas as pd
import pytest

from ml.generator.occupancy import OCCUPANCY_COLUMNS, ar1_noise, simulate_occupancy


def test_bounds(cfg, generated) -> None:
    d = generated[2]
    rooms = cfg.property.rooms
    n_days = (cfg.property.end - cfg.property.start).days + 1
    assert len(d) == n_days and not d.isna().any().any()
    assert d["occupancy_pct"].between(0, 1).all()
    assert d["occupancy_pct"].min() >= cfg.occupancy.min - 0.5 / rooms
    assert d["rooms_sold"].between(0, rooms).all()
    assert d["booking_pace_7d"].between(0, rooms).all()
    assert (d["adr"] > 0).all()


def test_derived_columns_consistent(cfg, generated) -> None:
    d = generated[2]
    assert np.allclose(d["occupancy_pct"], d["rooms_sold"] / cfg.property.rooms)
    assert np.allclose(d["room_revenue"], d["rooms_sold"] * d["adr"])


def test_no_latent_columns_leak(generated) -> None:
    d = generated[2]
    assert set(OCCUPANCY_COLUMNS) <= set(d.columns)
    latent = {"expected_occupancy", "occupancy_raw", "ar1_noise", "noise"}
    assert not latent & set(d.columns)
    assert not [c for c in d.columns if c.startswith("lag_") or "_lag" in c]


def test_reproducible(cfg, generated) -> None:
    cal, w, _ = generated
    a = simulate_occupancy(cal, w, cfg, np.random.default_rng(3))
    b = simulate_occupancy(cal, w, cfg, np.random.default_rng(3))
    c = simulate_occupancy(cal, w, cfg, np.random.default_rng(4))
    pd.testing.assert_frame_equal(a, b)
    assert not a["rooms_sold"].equals(c["rooms_sold"])


def test_weekend_and_season_effects(generated) -> None:
    d = generated[2]
    occ = d["occupancy_pct"]
    assert occ[d["is_weekend"]].mean() > occ[~d["is_weekend"]].mean()
    assert occ[d["month"].isin([5, 6])].mean() > occ[d["month"] == 2].mean()


def test_road_closure_lowers_occupancy(generated) -> None:
    d = generated[2]
    monsoon = d["month"].isin([7, 8, 9])
    occ, closed = d["occupancy_pct"], d["road_closure_flag"]
    assert occ[monsoon & closed].mean() < occ[monsoon & ~closed].mean()


def test_ar1_noise_autocorrelation() -> None:
    e = ar1_noise(50_000, 0.6, 0.04, np.random.default_rng(1))
    assert np.corrcoef(e[:-1], e[1:])[0, 1] == pytest.approx(0.6, abs=0.02)
    assert e.std() == pytest.approx(0.04 / np.sqrt(1 - 0.36), rel=0.03)
