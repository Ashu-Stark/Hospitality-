import numpy as np
import pandas as pd
import pytest

from ml.attrition.drivers import (
    DRIVER_GROUPS,
    UNSUPPORTED,
    _feature_of,
    actions_for,
    category_contributions,
    load_playbook,
    plain_reason,
    shap_values,
    top_categories,
)
from ml.attrition.features import MODEL_FEATURES, MODEL_NUMERIC
from ml.attrition.models import XGBoostScorer


@pytest.fixture(scope="module")
def tiny(require_gpu) -> tuple[XGBoostScorer, pd.DataFrame]:
    rng = np.random.default_rng(1)
    n = 600
    df = pd.DataFrame({c: rng.normal(size=n) for c in MODEL_NUMERIC})
    df["department"] = rng.choice(["kitchen", "housekeeping"], n)
    df["role"] = rng.choice(["cook", "attendant"], n)
    df["contract_type"] = rng.choice(["permanent", "seasonal"], n)
    y = (df["overtime_window_mean"] + rng.normal(scale=0.5, size=n) > 1).astype(int).to_numpy()
    return XGBoostScorer(seed=0).fit(df[MODEL_FEATURES], y), df


def test_every_feature_has_a_group_or_context(tiny) -> None:
    scorer, _ = tiny
    for col in scorer.columns:
        _feature_of(col)  # raises if unmapped
    assert DRIVER_GROUPS[UNSUPPORTED] == [] and len(DRIVER_GROUPS) == 7


def test_shap_sums_to_log_odds(tiny) -> None:
    scorer, df = tiny
    shap = shap_values(scorer, df)
    import xgboost as xgb

    raw = scorer.model.predict_proba(scorer.design(df))[:, 1]  # exported trees, numpy
    dm = xgb.DMatrix(scorer.design(df).to_numpy(dtype=np.float32), feature_names=scorer.columns)
    bias = scorer.model.gpu_booster().predict(dm, pred_contribs=True)[:, -1]
    np.testing.assert_allclose(shap.sum(axis=1) + bias, np.log(raw / (1 - raw)), atol=1e-4)
    contrib = category_contributions(shap)
    assert contrib["overtime_overload"].abs().mean() == contrib.abs().mean().max()


def test_top_categories_filters_and_orders() -> None:
    c = pd.Series({"overtime_overload": 0.5, "pay_gap": 0.05, "low_engagement": 0.8,
                   "stalled_progression": -1.0, UNSUPPORTED: 9.0})
    assert top_categories(c, min_logodds=0.1) == ["low_engagement", "overtime_overload"]


def test_playbook_covers_every_driver() -> None:
    pb = load_playbook()["drivers"]
    assert set(pb) == set(DRIVER_GROUPS)
    for name, d in pb.items():
        assert len(d["interventions"]) == 2
        for a in d["interventions"]:
            assert {"action", "owner", "check_after_weeks", "expected_effect"} <= set(a)
            assert a["expected_effect"].startswith("ASSUMPTION")
        assert d["supported"] == (name != UNSUPPORTED)
        assert d["support_level"] in {"supported", "weakly_supported", "unsupported"}
    acts = actions_for(["pay_gap"], load_playbook())
    assert len(acts) == 2 and acts[0]["driver"] == "pay_gap"


def test_plain_reason_reads_values() -> None:
    row = pd.Series({"overtime_window_mean": 13.14, "weeks_since_weekend_off": 5})
    assert plain_reason("overtime_overload", row).startswith("Overtime overload: averaging 13.1 h")
