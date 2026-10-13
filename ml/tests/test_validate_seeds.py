import numpy as np
import pandas as pd
import pytest

from ml.generator.validate_seeds import (
    SeedRun,
    pooled_no_driver_share,
    pooled_predictions,
    run_seed,
    seed_table,
)
from ml.generator.validate_signal import (
    RULE,
    ProbeSummary,
    ScorerResult,
    SignalNumbers,
    summarise_probes,
)


def _preds(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    label = (rng.random(300) < 0.2).astype(float)
    return pd.DataFrame({
        "test_year": 2025, "employee_id": [f"E{i}" for i in range(300)], "label": label,
        RULE: label * 0.5 + rng.normal(size=300), "lightgbm": label * 2 + rng.normal(size=300),
        "logistic": label * 1.5 + rng.normal(size=300),
    })


def _numbers(seed: int, no_driver: float, exits: int) -> SignalNumbers:
    preds = _preds(seed)
    return SignalNumbers(
        attrition=0.4, predictions=preds, probes=summarise_probes(preds, ["test_year"]),
        no_driver_share=no_driver, exits_considered=exits, high_driver_employees=5,
        high_driver_stayers=0.5, censored_rows=0, driver_share_of_exits={},
    )


def test_pooled_predictions_tag_seed_and_count_leavers_per_seed() -> None:
    runs = [SeedRun(1, _numbers(1, 0.1, 100)), SeedRun(2, _numbers(2, 0.1, 100))]
    preds = pooled_predictions(runs)
    assert set(preds["seed"]) == {1, 2} and len(preds) == 600
    s = summarise_probes(preds, ["seed", "test_year"])
    # the same employee id in two seeds is two different people
    assert s.leavers == int(preds.loc[preds["label"] == 1, ["seed", "employee_id"]]
                            .drop_duplicates().shape[0])
    assert s.best.auc_rank_pooled > s.rule.auc_rank_pooled


def test_pooled_no_driver_share_is_exit_weighted() -> None:
    runs = [SeedRun(1, _numbers(1, 0.10, 100)), SeedRun(2, _numbers(2, 0.20, 300))]
    assert pooled_no_driver_share(runs) == pytest.approx((10 + 60) / 400)
    table = seed_table(runs)
    assert list(table["seed"]) == [1, 2] and {"rule_b", "best", "gap_b"} <= set(table.columns)


def test_scorer_result_types() -> None:
    s = ScorerResult(0.7, 0.2, 0.69)
    p = ProbeSummary({RULE: ScorerResult(0.6, 0.1, 0.6), "lightgbm": s, "logistic": s},
                     "lightgbm", 10, 100, 0.1)
    assert p.gap == pytest.approx(0.1)


@pytest.mark.slow
def test_run_seed_end_to_end(cfg) -> None:
    run = run_seed(cfg, cfg.seed)
    assert run.seed == cfg.seed and not run.numbers.predictions.empty
    assert run.numbers.probes.leavers > 0
