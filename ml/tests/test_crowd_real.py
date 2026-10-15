"""ml/realdata/crowd: target construction, tree export, guardrails, train/serve parity.

Tiny in-memory fixtures (no download, no GPU). The bundle tests use the committed artifact
(ml/artifacts/crowd_forecast/real_v1/bundle.json) and are skipped if it has not been built.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from ml.realdata.crowd import predict as P
from ml.realdata.crowd import target
from ml.realdata.crowd import train as T
from ml.realdata.crowd.sources import ARTIFACT_DIR, PORTAL_CODE, PORTAL_MODEL

BUNDLE = ARTIFACT_DIR / "bundle.json"
needs_bundle = pytest.mark.skipif(
    not BUNDLE.exists(), reason="run python -m ml.realdata.crowd.train"
)


# ---- target construction --------------------------------------------------------------


def _write_inputs(tmp: Path, rows: list[dict], annual_total: float | None = 1000.0) -> None:
    cols = [
        "season",
        "dham",
        "as_of_date",
        "kind",
        "count",
        "source_url",
        "publisher",
        "published_date",
        "quote",
        "verified_raw",
        "notes",
        "use",
    ]
    df = pd.DataFrame([{c: r.get(c, "") for c in cols} for r in rows], columns=cols)
    df.to_csv(tmp / "checkpoints.csv", index=False)
    ann = (
        []
        if annual_total is None
        else [
            {
                "utdb_destination": "Kedarnath",
                "portal_id": "kedarnath",
                "year": 2030,
                "indian": annual_total,
                "foreign": 0,
                "total": annual_total,
                "source_key": "x",
            }
        ]
    )
    pd.DataFrame(
        ann,
        columns=[
            "utdb_destination",
            "portal_id",
            "year",
            "indian",
            "foreign",
            "total",
            "source_key",
        ],
    ).to_csv(tmp / "utdb_annual.csv", index=False)


def _ck(d: str, kind: str, count: float | None, verified: str = "yes") -> dict:
    return {
        "season": 2030,
        "dham": "kedarnath",
        "as_of_date": d,
        "kind": kind,
        "count": count,
        "verified_raw": verified,
        "use": 1,
        "source_url": "u",
    }


def _season(tmp: Path) -> target.SeasonSeries:
    ck = target.load_checkpoints(tmp)
    annual = pd.read_csv(tmp / "utdb_annual.csv")
    return target.build_season(
        "kedarnath", 2030, date(2030, 5, 1), date(2030, 5, 10), ck, annual, data_dir=tmp
    )


def test_target_spreads_interval_totals_and_keeps_real_sums(tmp_path: Path) -> None:
    _write_inputs(
        tmp_path,
        [
            _ck("2030-05-04", "cumulative", 400),
            _ck("2030-05-02", "daily", 250),
            _ck("2030-05-06", "nil", None),
        ],
    )
    s = _season(tmp_path)
    assert s.daily[date(2030, 5, 2)] == 250 and s.basis[date(2030, 5, 2)] == "reported"
    assert s.daily[date(2030, 5, 1)] == pytest.approx(50) and s.basis[date(2030, 5, 1)] == "spread"
    assert sum(v for d, v in s.daily.items() if d <= date(2030, 5, 4)) == pytest.approx(400)
    assert s.daily[date(2030, 5, 6)] == 0 and s.basis[date(2030, 5, 6)] == "nil"
    assert sum(s.daily.values()) == pytest.approx(1000)  # season total = official annual figure


def test_target_drops_non_monotonic_and_unverified(tmp_path: Path) -> None:
    _write_inputs(
        tmp_path,
        [
            _ck("2030-05-03", "cumulative", 600),
            _ck("2030-05-05", "cumulative", 500),
            _ck("2030-05-04", "cumulative", 999999, verified="no"),
        ],
    )
    s = _season(tmp_path)
    assert [a.cum for a in s.anchors] == [0, 500, 1000]  # 600 dropped (later 500 is lower)
    assert any("inconsistent" in m for m in s.dropped)
    assert all(v >= 0 for v in s.daily.values())


# ---- tree export ----------------------------------------------------------------------


def test_compact_trees_match_lightgbm_including_missing_values() -> None:
    rng = np.random.default_rng(42)
    X = rng.normal(size=(400, len(P.FEATURES)))
    X[rng.random(X.shape) < 0.2] = np.nan
    y = np.nan_to_num(X[:, 0]) * 2 + np.nan_to_num(X[:, 5]) + rng.normal(size=400) * 0.1
    for obj, extra in (("regression", {}), ("quantile", {"alpha": 0.9})):
        b = lgb.train(
            {"objective": obj, "verbose": -1, "num_leaves": 7, "seed": 1, **extra},
            lgb.Dataset(X, y),
            num_boost_round=30,
        )
        trees = T.compact(b)
        ours = [P.tree_predict(trees, list(r)) for r in X[:60]]
        assert np.allclose(ours, b.predict(X[:60]), atol=1e-6)


# ---- the real bundle ------------------------------------------------------------------


@pytest.fixture(scope="module")
def bundle() -> P.Bundle:
    return P.Bundle.load(BUNDLE)


def _open_day(b: P.Bundle, dest: str = "kedarnath") -> tuple[date, date]:
    last = b.last_observed(dest)
    return last, last + timedelta(days=3)


@needs_bundle
def test_bundle_loads_and_portal_copy_is_identical(bundle: P.Bundle) -> None:
    assert bundle.raw["real_data"] is True and set(bundle.dests) == set(P.DESTS)
    assert PORTAL_MODEL.read_bytes() == BUNDLE.read_bytes()
    assert PORTAL_CODE.read_bytes() == Path(P.__file__).read_bytes()


@needs_bundle
def test_closed_season_returns_closed(bundle: P.Bundle) -> None:
    year = max(int(y) for y in bundle.dests["kedarnath"]["seasons"])
    op = date.fromisoformat(bundle.dests["kedarnath"]["seasons"][str(year)][0])
    r = P.predict(bundle, "kedarnath", op - timedelta(days=2), as_of=op - timedelta(days=10))
    assert r["status"] == "closed" and r["pilgrims"] == 0 and r["band"] is None
    assert P.forecast_day(bundle, "kedarnath", date(year, 1, 15))["status"] == "closed"
    assert P.forecast_day(bundle, "kedarnath", date(2099, 6, 1))["status"] == "unknown_season"


@needs_bundle
def test_prediction_in_range_with_confidence(bundle: P.Bundle) -> None:
    for dest in P.DESTS:
        last = bundle.last_observed(dest)
        for h in (1, 7, 14):
            r = P.predict(bundle, dest, last + timedelta(days=h), as_of=last)
            if r["status"] == "closed":
                continue
            assert r["status"] in {"ok", "abstain"}
            assert 0 <= r["low"] <= r["pilgrims"] <= r["high"] <= bundle.dests[dest]["cap"]
            assert r["confidence"] in {"high", "medium", "low", "none"}


@needs_bundle
def test_input_validation(bundle: P.Bundle) -> None:
    last, day = _open_day(bundle)
    with pytest.raises(ValueError):
        P.predict(bundle, "atlantis", day, as_of=last)
    with pytest.raises(ValueError):
        P.predict(bundle, "kedarnath", "2025-13-40", as_of=last)
    with pytest.raises(ValueError):
        P.predict(bundle, "kedarnath", last + timedelta(days=30), as_of=last)
    with pytest.raises(ValueError):
        P.predict(bundle, "kedarnath", day, as_of=last, recent={last.isoformat(): -5})
    r = P.predict(
        bundle, "kedarnath", day, as_of=last, weather={day.isoformat(): (9999, 0, 10), "bad": "x"}
    )
    assert any("ignored" in n for n in r.get("notes", [])) or r["status"] == "closed"


def _in_season_case(b: P.Bundle) -> tuple[str, date, date] | None:
    for dest in P.DESTS:
        for y, (op, cl) in sorted(b.ctx.seasons[dest].items()):
            prev = b.ctx.seasons[dest].get(y - 1)
            if prev and (cl - op).days > 60 and op + timedelta(days=40) in b.ctx.series[dest]:
                return dest, op + timedelta(days=40), op + timedelta(days=41)
    return None


@needs_bundle
def test_fallback_to_seasonal_baseline_when_counts_missing(bundle: P.Bundle) -> None:
    case = _in_season_case(bundle)
    if case is None:
        pytest.skip("no season with a previous season in the bundle")
    dest, as_of, day = case
    nb = P._with_recent(bundle, dest, {})
    nb.ctx.series[dest] = {
        d: v for d, v in nb.ctx.series[dest].items() if d < as_of - timedelta(days=20)
    }
    r = P.predict(nb, dest, day, as_of=as_of)
    assert r["basis"] == "seasonal_baseline" and r["confidence"] == "low"
    assert "recent counts missing" in r["notes"]


@needs_bundle
def test_drift_and_clipping(bundle: P.Bundle) -> None:
    case = _in_season_case(bundle)
    if case is None:
        pytest.skip("no season with a previous season in the bundle")
    dest, as_of, day = case
    cap = bundle.dests[dest]["cap"]
    huge = {(as_of - timedelta(days=i)).isoformat(): 2 * cap for i in range(7)}
    r = P.predict(bundle, dest, day, as_of=as_of, recent=huge)
    assert r["basis"] == "seasonal_baseline" and any(
        "outside training range" in n for n in r["notes"]
    )
    assert r["high"] <= cap
    key, idx = P.band_of(bundle, dest, 10 * cap)
    assert (key, idx) == ("very_high", 100)
    assert P.band_of(bundle, dest, -5) == ("low", 0)


@needs_bundle
def test_abstains_when_range_too_wide(bundle: P.Bundle) -> None:
    last, day = _open_day(bundle)
    nb = P._with_recent(bundle, "kedarnath", {})
    nb.guard = {**bundle.guard, "abstain_width": -1.0}
    r = P.predict(nb, "kedarnath", day, as_of=last)
    assert r["status"] in {"abstain", "closed"} or r["basis"] == "seasonal_baseline"
    if r["status"] == "abstain":
        assert r["band"] is None


@needs_bundle
def test_train_serve_parity_on_saved_predictions() -> None:
    """The bundle (pure Python) reproduces the LightGBM booster on real feature rows."""
    b = lgb.Booster(model_file=str(ARTIFACT_DIR / "lgbm_point.txt"))
    bundle = P.Bundle.load(BUNDLE)
    rng = np.random.default_rng(0)
    rows = [
        [float(v) if not math.isnan(v) else math.nan for v in rng.normal(size=len(P.FEATURES))]
        for _ in range(20)
    ]
    assert np.allclose(
        [P.tree_predict(bundle.models["point"], r) for r in rows],
        b.predict(np.array(rows)),
        atol=1e-6,
    )
