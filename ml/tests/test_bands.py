"""T12 rank-based bands, same-model contributions, conformal band, mocks."""

import json

import numpy as np
import pandas as pd
import pytest

from ml.attrition.bands import assign_bands, band_metrics, percentile_band, place, slots


@pytest.fixture(scope="module")
def am(cfg):
    return cfg.attrition_model


def test_slots_use_ceil_without_float_noise(am) -> None:
    assert slots(48, am) == (5, 8)
    assert slots(7, am) == (1, 2)
    assert slots(30, am)[0] == 3  # 0.1 * 30 = 3.0000000000000004 must not become 4


def test_tie_groups_are_never_split(am) -> None:
    # n = 10 -> 1 high slot, 2 watch slots
    risk = pd.Series([0.9, 0.5, 0.5, 0.4, 0.4, 0.4, 0.1, 0.1, 0.1, 0.1])
    b = assign_bands(risk, am)
    assert b["band"].tolist() == ["high", "watch", "watch"] + ["low"] * 7
    assert b["rank"].tolist() == [1, 2, 2, 4, 4, 4, 7, 7, 7, 7]
    assert b["rank_is_tied"].tolist() == [False] + [True] * 9
    # a tie group too big for the high slot drops to watch, and closes high for everyone below
    b2 = assign_bands(pd.Series([0.9, 0.9, 0.2] + [0.1] * 7), am)
    assert b2["band"].tolist()[:3] == ["watch", "watch", "low"]


def test_all_tied_population_is_low(am) -> None:
    b = assign_bands(pd.Series([0.2144] * 7), am)
    assert set(b["band"]) == {"low"} and b["rank_is_tied"].all()


def test_place_does_not_take_a_slot(am) -> None:
    pop = pd.Series(np.linspace(0.30, 0.01, 48))
    top4 = pop.iloc[3]
    hero = place(top4 - 1e-3, pop, am)
    assert (hero.rank, hero.band, hero.group_size) == (5, "high", 48)
    assert place(pop.iloc[2], pop, am).rank_is_tied
    assert place(0.0, pop, am).band == "low"
    assert percentile_band(5, 48, am) == "watch" and percentile_band(4, 48, am) == "high"


def test_band_metrics_lift(am) -> None:
    rng = np.random.default_rng(3)
    rows = []
    for w in range(20):
        score = rng.uniform(size=50)
        label = (rng.uniform(size=50) < score * 0.3).astype(int)
        rows.append(pd.DataFrame({"week": w, "label": label, "s": score}))
    m = band_metrics(pd.concat(rows, ignore_index=True), "s", am)
    assert m["high_lift"] > 1 and 0 < m["leaver_weeks_in_high_or_watch"] <= 1
    assert m["band_share"]["high"] == pytest.approx(0.10)


def test_logistic_contributions_sum_to_calibrated_logodds() -> None:
    from ml.attrition.api import _state
    from ml.attrition.features import ARTIFACT_DIR, DATA_DIR

    bundle, _, features, _ = _state(ARTIFACT_DIR, DATA_DIR)
    info = bundle["segments"]["resignation"]
    assert info["winner"] == "logistic"
    model = info["model"]
    rows = features[(features["contract_type"] == "permanent")].tail(40)
    p = model.calibrated(rows)["logistic"]
    logit = np.log(p / (1 - p))
    total = model.contributions(rows, "logistic").sum(axis=1).to_numpy()
    offset = logit - total  # must be the same constant for every row
    assert np.ptp(offset) < 1e-6


def test_conformal_quantiles_finite_sample() -> None:
    from ml.forecast.train import conformal_quantiles

    lo, hi = conformal_quantiles(np.arange(1, 100), 0.1, 0.9)
    assert (lo, hi) == (10.0, 90.0)  # floor(100 * 0.1) / 99 and ceil(100 * 0.9) / 99 order stats


def test_mocks_mirror_the_result_types(tmp_path) -> None:
    from ml.attrition.api import AttritionScore, HeroInfo, RescoreResult
    from ml.eval.demo import demo_outputs, write_mocks
    from ml.forecast.api import ForecastResult

    paths = {p.stem: p for p in write_mocks(demo_outputs(), tmp_path)}
    load = lambda name: json.loads(paths[name].read_text("utf-8"))  # noqa: E731
    ForecastResult.model_validate(load("forecast_week"))
    scores = [AttritionScore.model_validate(x) for x in load("attrition_scores")]
    RescoreResult.model_validate(load("rescore_sunita"))
    heroes = [HeroInfo.model_validate(x) for x in load("heroes")]
    assert set(load("attrition_scores")[0]) == set(AttritionScore.model_fields)
    assert len(heroes) == 5 and all(s.synthetic for s in scores)
    assert len(load("forecast_week")["days"]) == 7


def test_seasonal_rule_band_thresholds(am) -> None:
    from ml.attrition.bands import rule_band

    hi, watch = am.seasonal_high_max_days, am.seasonal_watch_max_days
    assert rule_band(hi, am) == "high" and rule_band(hi + 1, am) == "watch"
    assert rule_band(watch, am) == "watch" and rule_band(watch + 1, am) == "low"


def test_band_basis_and_driver_support_in_output() -> None:
    from ml import attrition
    from ml.attrition.drivers import SUPPORT_LEVEL

    scores = attrition.score(attrition.api.latest_week())
    for s in scores:
        expected = "contract_date_rule" if s.segment == "contract_end" else "model_rank"
        assert s.band_basis == expected
        for d in s.drivers:
            assert d.support_level == SUPPORT_LEVEL[d.category]
    assert SUPPORT_LEVEL["clustered_leave_burnout"] == "weakly_supported"
    assert SUPPORT_LEVEL["manager_relationship"] == "unsupported"
