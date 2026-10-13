from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ml.generator.attrition import (
    RESIGNATION,
    SEASONAL_END,
    days_in_week,
    normalise_employees,
    simulate_weekly,
)
from ml.generator.staff import EMPLOYEE_COLUMNS

N_WEEKS = 8
TYPICAL_INTERCEPT = -6.0  # roughly where calibration lands
NO_RESIGNATIONS = -50.0  # sigmoid(-50) ~ 0: nobody resigns
MAX_HAZARD = 50.0  # sigmoid(+50) ~ 1, capped at max_weekly_hazard (0.5)


def _with(cfg, **attrition):
    return cfg.model_copy(update={"attrition": cfg.attrition.model_copy(update=attrition)})


def _short_load(staff_frames, departments=None) -> pd.DataFrame:
    load = staff_frames.dept_week_load
    weeks = sorted(load["week_start"].unique())[:N_WEEKS]
    out = load[load["week_start"].isin(weeks)]
    return out[out["department"].isin(departments)] if departments else out


def _run(cfg, staff_frames, employees=None, departments=None, seed=0,
         intercept=TYPICAL_INTERCEPT):
    emp = staff_frames.employee if employees is None else employees
    return simulate_weekly(
        cfg,
        np.random.default_rng(seed),
        emp,
        staff_frames.employee_latent,
        _short_load(staff_frames, departments),
        intercept,
    )


def test_days_in_week() -> None:
    monday = date(2024, 1, 1)
    assert days_in_week(date(2023, 5, 5), monday) == 7
    assert days_in_week(date(2024, 1, 4), monday) == 4  # Thu..Sun
    assert days_in_week(date(2024, 1, 8), monday) == 0


def test_normalise_round_trips_csv(staff_frames, tmp_path) -> None:
    path = tmp_path / "employee.csv"
    staff_frames.employee.to_csv(path, index=False, date_format="%Y-%m-%d")
    reread = normalise_employees(pd.read_csv(path, keep_default_na=False))
    out = tmp_path / "again.csv"
    reread.to_csv(out, index=False, date_format="%Y-%m-%d")
    assert out.read_bytes() == path.read_bytes()


def test_no_hazard_no_seasonal_gives_full_grid(cfg, staff_frames) -> None:
    quiet = _with(cfg, seasonal_contract_end_is_exit=False)
    r = _run(quiet, staff_frames, intercept=NO_RESIGNATIONS)
    assert len(r.weekly_behaviour) == 55 * N_WEEKS
    assert r.exits.empty and len(r.employees) == 55
    assert r.weekly_behaviour["is_active"].all()
    dyn = r.dept_week_load_dynamic
    assert dyn.groupby("department")["headcount"].first().to_dict() == cfg.departments


def test_static_headcount_reproduces_task3_load(cfg, staff_frames) -> None:
    quiet = _with(cfg, seasonal_contract_end_is_exit=False)
    dyn = _run(quiet, staff_frames, intercept=NO_RESIGNATIONS).dept_week_load_dynamic
    dyn = dyn.sort_values(["department", "week_start"])
    static = _short_load(staff_frames).sort_values(["department", "week_start"])
    assert np.allclose(dyn["load_ratio"].to_numpy(), static["load_ratio"].to_numpy(), atol=1e-4)


def test_seasonal_end_by_hand(cfg, staff_frames) -> None:
    """Security only (E051 head, E052-E055 guards); E053 seasonal ending in week 3."""
    emp = staff_frames.employee[staff_frames.employee["department"] == "security"].copy()
    week1 = date(2023, 1, 2)
    end = week1 + timedelta(days=2 * 7 + 3)  # Thursday of week 3
    emp.loc[emp["employee_id"] == "E053", ["contract_type", "contract_end_date"]] = (
        "seasonal", end,
    )
    emp.loc[emp["employee_id"] != "E053", ["contract_type", "contract_end_date"]] = (
        "permanent", None,
    )
    sim_cfg = _with(cfg, seasonal_renewal_prob=0.0)
    r = _run(sim_cfg, staff_frames, employees=emp, departments=["security"],
             intercept=NO_RESIGNATIONS)

    assert len(r.exits) == 1
    ex = r.exits.iloc[0]
    assert (ex["employee_id"], ex["exit_date"], ex["exit_reason"]) == ("E053", end, SEASONAL_END)
    assert ex["replacement_employee_id"] == "E056"
    new = r.employees.set_index("employee_id").loc["E056"]
    gap = (new["hire_date"] - end).days
    assert 2 <= gap <= 30 and new["role"] == "guard" and new["manager_id"] == "E051"

    # Rows by hand: 4 stayers x 8 weeks + leaver weeks 1-3 + replacement from its hire week.
    hire_week = (new["hire_date"] - week1).days // 7  # 0-based
    expected = 4 * N_WEEKS + 3 + max(N_WEEKS - hire_week, 0)
    beh = r.weekly_behaviour
    assert len(beh) == expected
    leaver = beh[beh["employee_id"] == "E053"]
    assert leaver["is_active"].tolist() == [True, True, False]
    assert r.contract_renewals.empty


def test_seasonal_renewal_extends_contract(cfg, staff_frames) -> None:
    emp = staff_frames.employee[staff_frames.employee["department"] == "security"].copy()
    end = date(2023, 1, 18)
    emp["contract_type"], emp["contract_end_date"] = "permanent", None
    emp.loc[emp["employee_id"] == "E054", ["contract_type", "contract_end_date"]] = (
        "seasonal", end,
    )
    sim_cfg = _with(cfg, seasonal_renewal_prob=1.0)
    r = _run(sim_cfg, staff_frames, employees=emp, departments=["security"],
             intercept=NO_RESIGNATIONS)
    assert r.exits.empty
    ren = r.contract_renewals.iloc[0]
    assert ren["employee_id"] == "E054" and ren["renewal_date"] == end
    assert ren["new_contract_end_date"] in {date(2023, 6, 30), date(2023, 10, 31)}


def test_heavy_hazard_bookkeeping(cfg, staff_frames) -> None:
    """Hazard forced to the 0.5 cap: lots of exits; check every invariant by construction."""
    r = _run(cfg, staff_frames, seed=4, intercept=MAX_HAZARD)
    beh, exits, emps = r.weekly_behaviour, r.exits, r.employees
    assert len(exits) > 55
    assert set(exits["exit_reason"]) <= {RESIGNATION, SEASONAL_END}
    assert not beh.duplicated(["employee_id", "week_start"]).any()

    # New ids continue the sequence without reuse; each exit has exactly one replacement.
    assert emps["employee_id"].tolist() == [f"E{i:03d}" for i in range(1, len(emps) + 1)]
    assert exits["replacement_employee_id"].is_unique
    assert len(emps) == 55 + len(exits)

    exit_of = dict(zip(exits["employee_id"], exits["exit_date"], strict=True))
    hire_of = dict(zip(emps["employee_id"], emps["hire_date"], strict=True))
    first_week = min(beh["week_start"])
    for emp_id, rows in beh.groupby("employee_id"):
        weeks = sorted(rows["week_start"])
        assert all((b - a).days == 7 for a, b in zip(weeks, weeks[1:], strict=False))  # no gaps
        start = max(hire_of[emp_id], first_week)
        assert weeks[0] <= start <= weeks[0] + timedelta(days=6)  # first row = week of start
        if emp_id in exit_of:
            last = rows.sort_values("week_start").iloc[-1]
            assert last["week_start"] <= exit_of[emp_id] <= last["week_start"] + timedelta(days=6)
            assert not last["is_active"] and rows["is_active"].sum() == len(rows) - 1
        else:
            assert rows["is_active"].all()
    for r_ in exits.itertuples():
        gap = (hire_of[r_.replacement_employee_id] - r_.exit_date).days
        assert cfg.attrition.vacancy_days_min <= gap <= cfg.attrition.vacancy_days_max
        assert r_.tenure_days_at_exit == (r_.exit_date - hire_of[r_.employee_id]).days


def test_replaced_head_becomes_manager(cfg, staff_frames) -> None:
    r = _run(cfg, staff_frames, seed=4, intercept=MAX_HAZARD)
    emps = r.employees.set_index("employee_id")
    new = emps.loc[emps.index.isin(r.exits["replacement_employee_id"])]
    for _, row in new.iterrows():
        if row["is_department_head"]:
            assert row["manager_id"] == ""
        else:
            assert emps.loc[row["manager_id"], "is_department_head"]
            assert emps.loc[row["manager_id"], "department"] == row["department"]


def test_latent_rows_fresh_for_replacements(cfg, staff_frames) -> None:
    r = _run(cfg, staff_frames, seed=4, intercept=MAX_HAZARD)
    lat = r.latent.set_index("employee_id")
    assert list(lat.index) == r.employees["employee_id"].tolist()
    pd.testing.assert_frame_equal(
        lat.iloc[:55].reset_index(), staff_frames.employee_latent.reset_index(drop=True)
    )
    for row in r.exits.itertuples():
        assert not lat.loc[row.replacement_employee_id].equals(lat.loc[row.employee_id])


def test_reproducible(cfg, staff_frames) -> None:
    a = _run(cfg, staff_frames, seed=11)
    b = _run(cfg, staff_frames, seed=11)
    for name in ("weekly_behaviour", "exits", "employees", "latent", "dept_week_load_dynamic"):
        pd.testing.assert_frame_equal(getattr(a, name), getattr(b, name))


def test_employee_columns_unchanged(cfg, staff_frames) -> None:
    assert list(_run(cfg, staff_frames).employees.columns) == EMPLOYEE_COLUMNS


@pytest.mark.parametrize("bad", [{"vacancy_days_min": 12}, {"leave_seasonal_block_weeks": [60]}])
def test_attrition_config_rejects_bad_values(cfg, bad) -> None:
    from pydantic import ValidationError

    from ml.generator.config import AttritionConfig

    with pytest.raises(ValidationError):
        AttritionConfig.model_validate({**cfg.attrition.model_dump(), **bad})


def test_replacement_keeps_leaver_contract_type(cfg, staff_frames) -> None:
    """Task 4c: seasonal leavers -> seasonal hires, permanent -> permanent."""
    r = _run(cfg, staff_frames, seed=4, intercept=MAX_HAZARD)
    ctype = r.employees.set_index("employee_id")["contract_type"]
    leaver = r.exits["employee_id"].map(ctype)
    replacement = r.exits["replacement_employee_id"].map(ctype)
    assert (leaver == replacement).all()
    assert (leaver == "seasonal").any() and (leaver == "permanent").any()
    hires = r.employees.set_index("employee_id").loc[r.exits["replacement_employee_id"]]
    seasonal = hires[hires["contract_type"] == "seasonal"]
    assert seasonal["contract_end_date"].notna().all()
    assert (seasonal["contract_end_date"] > seasonal["hire_date"]).all()
    assert hires.loc[hires["contract_type"] == "permanent", "contract_end_date"].isna().all()


def test_seasonal_headcount_constant_without_hazard(cfg, staff_frames) -> None:
    """Only seasonal_end exits: every seasonal leaver is replaced by a seasonal hire."""
    quiet = _with(cfg, seasonal_renewal_prob=0.0)
    s = staff_frames  # full horizon, so seasonal contracts actually end
    r = simulate_weekly(quiet, np.random.default_rng(0), s.employee, s.employee_latent,
                        s.dept_week_load, NO_RESIGNATIONS)
    assert len(r.exits) > 7
    ctype = r.employees.set_index("employee_id")["contract_type"]
    assert (r.exits["replacement_employee_id"].map(ctype) == "seasonal").all()
    assert (ctype == "seasonal").sum() == 7 + len(r.exits)


def test_raises_logged_and_point_in_time(cfg, staff_frames) -> None:
    """With every eligible week a raise, pay rises are logged and never precede eligibility."""
    eager = _with(cfg, raises=cfg.attrition.raises.model_copy(
        update={"weekly_prob_when_eligible": 1.0}))
    r = _run(eager, staff_frames, intercept=NO_RESIGNATIONS)
    pc = r.pay_changes
    assert not pc.empty and list(pc.columns) == ["employee_id", "effective_date", "monthly_pay"]
    start_pay = r.employees.set_index("employee_id")["monthly_pay"]
    first = pc.groupby("employee_id").first()
    assert (first["monthly_pay"] >= first.index.map(start_pay)).all()
    last_raise = r.employees.set_index("employee_id")["last_raise_date"]
    months = (pd.to_datetime(first["effective_date"]) - pd.to_datetime(
        first.index.map(last_raise))).dt.days / 30.44
    assert (months >= cfg.attrition.raises.eligible_after_months).all()


def test_peer_exit_count() -> None:
    from ml.generator.attrition import peer_exit_count

    ws = date(2024, 3, 4)
    exits = [ws - timedelta(weeks=9), ws - timedelta(weeks=8), ws - timedelta(days=1), ws]
    assert peer_exit_count(exits, ws, 8) == 2  # window [ws - 8 weeks, ws)


def test_intercept_lowers_or_raises_exits(cfg, staff_frames) -> None:
    low = _run(cfg, staff_frames, intercept=-9.0)
    high = _run(cfg, staff_frames, intercept=-3.0)
    assert (low.exits["exit_reason"] == RESIGNATION).sum() < (
        high.exits["exit_reason"] == RESIGNATION).sum()
    assert low.intercept == -9.0
