from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml.generator.staff import (
    EMPLOYEE_COLUMNS,
    LATENT_COLUMNS,
    draw_last_raise,
    draw_tenure_years,
    generate_employee,
    generate_initial_staff,
    next_month_day,
)


@pytest.fixture(scope="module")
def staff(cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    return generate_initial_staff(cfg, np.random.default_rng(0))


def test_headcount_and_columns(cfg, staff) -> None:
    emp, latent = staff
    assert len(emp) == 55
    assert list(emp.columns) == EMPLOYEE_COLUMNS
    assert emp["employee_id"].tolist() == [f"E{i:03d}" for i in range(1, 56)]
    assert emp.groupby("department").size().to_dict() == cfg.departments


def test_latent_traits_never_in_employee_table(staff) -> None:
    emp, latent = staff
    assert not set(LATENT_COLUMNS) & set(emp.columns)
    assert list(latent.columns) == ["employee_id", *LATENT_COLUMNS]
    assert latent["employee_id"].tolist() == emp["employee_id"].tolist()


def test_heads_and_managers(staff) -> None:
    emp = staff[0]
    heads = emp[emp["is_department_head"]]
    assert heads.groupby("department").size().eq(1).all()
    assert (heads["manager_id"] == "").all()
    head_of = dict(zip(heads["department"], heads["employee_id"], strict=True))
    others = emp[~emp["is_department_head"]]
    assert (others["manager_id"] == others["department"].map(head_of)).all()


def test_dates_contracts_and_pay(cfg, staff) -> None:
    emp = staff[0]
    start = cfg.property.start
    assert (emp["hire_date"] < start).all()
    assert (emp["last_raise_date"] >= emp["hire_date"]).all()
    assert (emp["last_raise_date"] <= start).all()
    seasonal = emp[emp["contract_type"] == "seasonal"]
    assert set(seasonal["role"]) <= set(cfg.staff.seasonal_share_by_role)
    assert set(seasonal["contract_end_date"]) <= {date(2023, 6, 30), date(2023, 10, 31)}
    assert emp.loc[emp["contract_type"] == "permanent", "contract_end_date"].isna().all()
    for (dept, role), pay in emp.groupby(["department", "role"])["monthly_pay"]:
        assert (pay >= 0.7 * cfg.roles[dept][role].pay_mean - 1).all()


def test_short_tenure_raise_is_hire_date() -> None:
    rng = np.random.default_rng(0)
    assert draw_last_raise(rng, date(2022, 6, 1), date(2023, 1, 1)) == date(2022, 6, 1)
    later = draw_last_raise(rng, date(2019, 1, 1), date(2023, 1, 1))
    assert date(2019, 1, 1) < later < date(2023, 1, 1)


def test_tenure_truncated_and_mean_plausible(cfg) -> None:
    rng = np.random.default_rng(1)
    t = np.array([draw_tenure_years(rng, cfg.staff) for _ in range(20_000)])
    assert t.min() >= cfg.staff.tenure_min_years and t.max() <= cfg.staff.tenure_max_years
    assert 1.3 < t.mean() < 1.8


def test_latent_distributions(cfg) -> None:
    big = pd.concat(
        [generate_initial_staff(cfg, np.random.default_rng(s))[1] for s in range(40)]
    )
    assert big["overtime_propensity"].mean() == pytest.approx(1.0, abs=0.05)
    assert big["baseline_pulse"].between(1, 5).all()
    assert big["baseline_task_score"].between(40, 98).all()
    assert big["latent_frustration"].mean() == pytest.approx(0.0, abs=0.05)


def test_next_month_day() -> None:
    assert next_month_day(date(2023, 1, 1), "06-30") == date(2023, 6, 30)
    assert next_month_day(date(2023, 6, 30), "06-30") == date(2024, 6, 30)


def test_generate_employee_replacement_hire(cfg) -> None:
    rng = np.random.default_rng(3)
    hire = date(2024, 8, 1)
    rows = [
        generate_employee(rng, cfg, emp_id="E100", department="kitchen", role="helper",
                          hire_date=hire, as_of=hire, manager_id="E021")
        for _ in range(200)
    ]
    emp = pd.DataFrame([r for r, _ in rows])
    assert (emp["last_raise_date"] == hire).all()
    assert (emp["manager_id"] == "E021").all()
    ends = set(emp.loc[emp["contract_type"] == "seasonal", "contract_end_date"])
    assert ends == {date(2024, 10, 31), date(2025, 6, 30)}


def test_reproducible(cfg) -> None:
    a = generate_initial_staff(cfg, np.random.default_rng(9))
    b = generate_initial_staff(cfg, np.random.default_rng(9))
    pd.testing.assert_frame_equal(a[0], b[0])
    pd.testing.assert_frame_equal(a[1], b[1])


@pytest.mark.parametrize("forced", ["seasonal", "permanent"])
def test_generate_employee_forced_contract_type(cfg, forced: str) -> None:
    rng = np.random.default_rng(5)
    hire = date(2024, 8, 1)
    for _ in range(50):
        row, _ = generate_employee(rng, cfg, emp_id="E200", department="security", role="guard",
                                   hire_date=hire, as_of=hire, manager_id="E051",
                                   contract_type=forced)
        assert row["contract_type"] == forced
        assert (row["contract_end_date"] is None) == (forced == "permanent")
        if forced == "seasonal":
            assert row["contract_end_date"] in {date(2024, 10, 31), date(2025, 6, 30)}


def test_generate_employee_forced_type_keeps_stream_aligned(cfg) -> None:
    """Forcing the type consumes the same draws, so later draws are unchanged."""
    hire = date(2024, 8, 1)
    kwargs = dict(emp_id="E200", department="kitchen", role="helper", hire_date=hire, as_of=hire)
    a_rng, b_rng = np.random.default_rng(9), np.random.default_rng(9)
    a, _ = generate_employee(a_rng, cfg, **kwargs)
    b, _ = generate_employee(b_rng, cfg, contract_type="permanent", **kwargs)
    assert a["monthly_pay"] == b["monthly_pay"]
    assert a_rng.random() == b_rng.random()


def test_generate_employee_rejects_bad_contract_type(cfg) -> None:
    with pytest.raises(ValueError):
        generate_employee(np.random.default_rng(0), cfg, emp_id="E1", department="kitchen",
                          role="cook", hire_date=date(2024, 1, 1), as_of=date(2024, 1, 1),
                          contract_type="temp")
