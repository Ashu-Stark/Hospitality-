import pandas as pd
import pytest

from ml.features.build_features import CENSORED, LABEL, LABEL_WEEKS, build_features
from ml.features.split import describe, time_split


@pytest.fixture(scope="module")
def splits(attrition_result):
    r = attrition_result
    return time_split(build_features(r.employees, r.weekly_behaviour, r.exits,
                                     r.contract_renewals, r.pay_changes))


def test_no_week_overlap(splits) -> None:
    weeks = {name: set(part["week_start"]) for name, part in splits.items()}
    assert not weeks["train"] & weeks["val"]
    assert not weeks["train"] & weeks["test"]
    assert not weeks["val"] & weeks["test"]


def test_time_ordered_with_embargo(splits) -> None:
    gap = pd.Timedelta(weeks=LABEL_WEEKS)
    assert splits.train["week_start"].max() + gap < splits.val["week_start"].min()
    assert splits.val["week_start"].max() + gap < splits.test["week_start"].min()


def test_no_employee_week_in_two_splits(splits) -> None:
    keys = [set(zip(p["employee_id"], p["week_start"], strict=True)) for _, p in splits.items()]
    assert not (keys[0] & keys[1] or keys[0] & keys[2] or keys[1] & keys[2])


def test_proportions_roughly_60_20_20(splits) -> None:
    n = {name: part["week_start"].nunique() for name, part in splits.items()}
    total = n["train"] + n["val"] + n["test"] + 2 * LABEL_WEEKS
    assert abs(n["test"] / total - 0.2) < 0.03
    assert abs((n["train"] + LABEL_WEEKS) / total - 0.6) < 0.03


def test_describe(splits) -> None:
    d = describe(splits)
    assert list(d["split"]) == ["train", "val", "test"]
    assert d["rows"].sum() == sum(len(p) for _, p in splits.items())
    assert (d["positives"] == [int(p[LABEL].sum()) for _, p in splits.items()]).all()


def test_split_like_reuses_reference_windows(splits, attrition_result) -> None:
    from ml.features.build_pulse_features import build_pulse_features
    from ml.features.split import split_like

    r = attrition_result
    pulse = split_like(
        build_pulse_features(r.employees, r.weekly_behaviour, r.contract_renewals), splits
    )
    for (_, ref), (_, part) in zip(splits.items(), pulse.items(), strict=True):
        assert part["week_start"].min() >= ref["week_start"].min()
        assert part["week_start"].max() <= ref["week_start"].max()
        assert part["week_start"].max() == ref["week_start"].max()
    weeks = [set(p["week_start"]) for _, p in pulse.items()]
    assert not (weeks[0] & weeks[1] or weeks[0] & weeks[2] or weeks[1] & weeks[2])


def test_split_like_workload_department_weeks(splits, attrition_result, generated) -> None:
    from ml.features.build_workload_features import build_workload_features
    from ml.features.split import split_like

    r = attrition_result
    wl = split_like(build_workload_features(r.dept_week_load_dynamic, generated[0]), splits)
    weeks = [set(p["week_start"]) for _, p in wl.items()]
    assert not (weeks[0] & weeks[1] or weeks[0] & weeks[2] or weeks[1] & weeks[2])
    for _, part in wl.items():
        assert part["department"].nunique() == 6
        assert len(part) == 6 * part["week_start"].nunique()  # one row per department-week


def test_censored_rows_excluded(splits, attrition_result) -> None:
    r = attrition_result
    feats = build_features(r.employees, r.weekly_behaviour, r.exits, r.contract_renewals,
                           r.pay_changes)
    assert feats[CENSORED].any()
    for _, part in splits.items():
        assert not part[CENSORED].any() and part[LABEL].notna().all()
    last_used = max(p["week_start"].max() for _, p in splits.items())
    assert last_used < feats.loc[feats[CENSORED], "week_start"].min()

