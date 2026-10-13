import numpy as np
import pandas as pd
import pytest

from ml.generator.skills import (
    _add_holder,
    assign_department_skills,
    coverage_shortfalls,
    generate_employee_skills,
    role_tier,
)
from ml.generator.staff import generate_initial_staff


def test_default_coverage_holds(cfg, staff_frames) -> None:
    assert coverage_shortfalls(staff_frames.employee, staff_frames.employee_skill, cfg) == []


@pytest.mark.parametrize("seed", range(25))
def test_coverage_holds_for_many_seeds(cfg, seed: int) -> None:
    emp, _ = generate_initial_staff(cfg, np.random.default_rng(seed))
    skills = generate_employee_skills(emp, cfg, np.random.default_rng(seed + 100))
    assert coverage_shortfalls(emp, skills, cfg) == []
    assert skills["level"].between(1, 3).all()
    assert not skills.duplicated(["employee_id", "skill"]).any()


def test_fo_system_has_three_holders(staff_frames) -> None:
    sk = staff_frames.employee_skill
    assert (sk["skill"] == "fo_system").sum() >= 3


def test_heads_hold_more_skills_on_average(staff_frames) -> None:
    emp, sk = staff_frames.employee, staff_frames.employee_skill
    n = sk.groupby("employee_id").size()
    heads = emp.loc[emp["is_department_head"], "employee_id"]
    assert (n[heads] >= 2).all()
    assert n[heads].mean() > n.drop(heads).mean()


def test_role_tier(cfg) -> None:
    assert role_tier(cfg, "kitchen", "head_chef") == "head"
    assert role_tier(cfg, "kitchen", "cook") == "mid"
    assert role_tier(cfg, "kitchen", "helper") == "entry"
    assert role_tier(cfg, "front_office", "concierge") == "entry"


def test_repair_swaps_when_everyone_is_full() -> None:
    # Everyone already holds 3 skills, so 'd' can only be added by swapping out a skill
    # that has more holders than it needs (each of a, b, c has 3, needs 2).
    members = ["A", "B", "C"]
    holdings = {e: {"a": 1, "b": 1, "c": 1} for e in members}
    tiers = dict.fromkeys(members, "mid")
    _add_holder(np.random.default_rng(0), holdings, members, "d", tiers)
    held = pd.Series([s for e in members for s in holdings[e]]).value_counts()
    assert held["d"] == 1
    assert (held[["a", "b", "c"]] >= 2).all()
    assert all(len(h) == 3 for h in holdings.values())


def test_assign_department_skills_small_department() -> None:
    members = ["A", "B"]
    holdings = assign_department_skills(
        np.random.default_rng(0), members, {"A": "head", "B": "entry"}, ["a", "b", "c"]
    )
    held = pd.Series([s for e in members for s in holdings[e]]).value_counts()
    assert (held.reindex(["a", "b", "c"]) >= 2).all()


def test_coverage_shortfalls_reports_gaps(cfg, staff_frames) -> None:
    sk = staff_frames.employee_skill
    broken = sk[sk["skill"] != "fo_system"]
    problems = coverage_shortfalls(staff_frames.employee, broken, cfg)
    assert any("fo_system has 0 holders" in p for p in problems)
