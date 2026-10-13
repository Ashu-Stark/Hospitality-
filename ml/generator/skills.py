"""SYNTHETIC employee skills with a coverage guarantee per department.

Each employee holds 1-3 skills from their own department's list; heads hold at least 2.
In every department with at least 2 people, each skill has at least
skill_min_holders(skill) holders (3 for fo_system, 2 otherwise), capped at department size.

Replacement hires (bug fix after T12b): they previously got NO skills, so by 2029 only 9 of 55
active staff held any and no active front-office employee held fo_system.
extend_skills_to_replacements() gives every replacement hire skills with the same draw (1-3 by
role tier, heads >= 2) from its own random stream, then tops the new hire up with any department
skill whose holders among the staff ACTIVE on the hire date fell below the minimum. Existing
employees keep their skills, so the original rows stay byte-identical.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.generator.config import (
    MAX_SKILLS_PER_EMPLOYEE,
    GeneratorConfig,
    is_head_role,
    skill_min_holders,
)

SKILL_COLUMNS = ["employee_id", "skill", "level"]

# ASSUMED: skill level (1-3) probabilities by role tier.
LEVEL_PROBS = {"head": [0.1, 0.3, 0.6], "mid": [0.2, 0.5, 0.3], "entry": [0.5, 0.4, 0.1]}

Holdings = dict[str, dict[str, int]]  # employee_id -> {skill: level}


def role_tier(cfg: GeneratorConfig, department: str, role: str) -> str:
    """'head', 'entry' (lowest-paid role in the department) or 'mid'."""
    if is_head_role(role):
        return "head"
    roles = cfg.roles[department]
    lowest = min(roles, key=lambda r: roles[r].pay_mean)
    return "entry" if role == lowest else "mid"


def n_skills(rng: np.random.Generator, tier: str, n_available: int) -> int:
    """head: 2-3, mid: 2, entry: 1-2; capped at what the department offers."""
    low, high = {"head": (2, 3), "mid": (2, 2), "entry": (1, 2)}[tier]
    return min(int(rng.integers(low, high + 1)), n_available)


def draw_level(rng: np.random.Generator, tier: str) -> int:
    return int(rng.choice([1, 2, 3], p=LEVEL_PROBS[tier]))


def required_holders(skill: str, dept_size: int) -> int:
    return min(skill_min_holders(skill), dept_size) if dept_size >= 2 else 0


def holders(holdings: Holdings, members: list[str], skill: str) -> int:
    return sum(skill in holdings[e] for e in members)


def _add_holder(
    rng: np.random.Generator,
    holdings: Holdings,
    members: list[str],
    skill: str,
    tiers: dict[str, str],
) -> None:
    """Give `skill` to one member: prefer someone with room, else swap out a spare skill."""
    lacking = [e for e in members if skill not in holdings[e]]
    with_room = [e for e in lacking if len(holdings[e]) < MAX_SKILLS_PER_EMPLOYEE]
    if with_room:
        fewest = min(len(holdings[e]) for e in with_room)
        emp = str(rng.choice([e for e in with_room if len(holdings[e]) == fewest]))
    else:
        size = len(members)
        swappable = [
            (e, s)
            for e in lacking
            for s in holdings[e]
            if holders(holdings, members, s) > required_holders(s, size)
        ]
        if not swappable:
            raise RuntimeError(f"cannot reach coverage for {skill}")
        emp, spare = swappable[int(rng.integers(len(swappable)))]
        del holdings[emp][spare]
    holdings[emp][skill] = draw_level(rng, tiers[emp])


def assign_department_skills(
    rng: np.random.Generator, members: list[str], tiers: dict[str, str], skills: list[str]
) -> Holdings:
    """Random initial skills per member, then top up until coverage holds."""
    holdings: Holdings = {}
    for emp in members:
        k = n_skills(rng, tiers[emp], len(skills))
        chosen = rng.choice(skills, size=k, replace=False)
        holdings[emp] = {str(s): draw_level(rng, tiers[emp]) for s in chosen}
    for skill in skills:
        while holders(holdings, members, skill) < required_holders(skill, len(members)):
            _add_holder(rng, holdings, members, skill, tiers)
    return holdings


def generate_employee_skills(
    employees: pd.DataFrame, cfg: GeneratorConfig, rng: np.random.Generator
) -> pd.DataFrame:
    """employee_skill table: employee_id, skill, level (1-3)."""
    rows = []
    for dept, skills in cfg.skills.items():
        staff = employees[employees["department"] == dept]
        members = staff["employee_id"].tolist()
        tiers = {e: role_tier(cfg, dept, r) for e, r in zip(members, staff["role"], strict=True)}
        holdings = assign_department_skills(rng, members, tiers, skills)
        for emp in members:
            # Keep config order so output is stable and readable.
            rows += [(emp, s, holdings[emp][s]) for s in skills if s in holdings[emp]]
    return pd.DataFrame(rows, columns=SKILL_COLUMNS)


def coverage_shortfalls(
    employees: pd.DataFrame, employee_skill: pd.DataFrame, cfg: GeneratorConfig
) -> list[str]:
    """Human-readable list of coverage rule violations (empty if all hold)."""
    problems = []
    dept_of = employees.set_index("employee_id")["department"]
    heads = set(employees.loc[employees["is_department_head"], "employee_id"])
    counts = employee_skill.groupby("employee_id").size()
    for emp in employees["employee_id"]:
        n = int(counts.get(emp, 0))
        if not 1 <= n <= MAX_SKILLS_PER_EMPLOYEE:
            problems.append(f"{emp} holds {n} skills")
        if emp in heads and n < 2:
            problems.append(f"head {emp} holds {n} skills")
    for r in employee_skill.itertuples():
        if r.skill not in cfg.skills[dept_of[r.employee_id]]:
            problems.append(f"{r.employee_id} holds non-department skill {r.skill}")
    for dept, skills in cfg.skills.items():
        size = int((employees["department"] == dept).sum())
        members = set(employees.loc[employees["department"] == dept, "employee_id"])
        held = employee_skill[employee_skill["employee_id"].isin(members)]
        for s in skills:
            have, need = int((held["skill"] == s).sum()), required_holders(s, size)
            if have < need:
                problems.append(f"{dept}: {s} has {have} holders, needs {need}")
    return problems


def _active_members(employees: pd.DataFrame, exit_of: dict[str, pd.Timestamp], dept: str,
                    on: pd.Timestamp) -> list[str]:
    """Department members hired on or before `on` who have not exited by `on`."""
    rows = employees[(employees["department"] == dept)
                     & (pd.to_datetime(employees["hire_date"]) <= on)]
    return [e for e in rows["employee_id"] if e not in exit_of or exit_of[e] > on]


def _hire_skills(rng: np.random.Generator, tier: str, skills: list[str], deficits: list[str]
                 ) -> dict[str, int]:
    """Random draw for one hire, then add the department's deficit skills (swapping spares)."""
    k = n_skills(rng, tier, len(skills))
    own = {str(s): draw_level(rng, tier) for s in rng.choice(skills, size=k, replace=False)}
    for skill in deficits:
        if skill in own:
            continue
        if len(own) >= MAX_SKILLS_PER_EMPLOYEE:
            spare = [s for s in own if s not in deficits]
            if not spare:
                break  # more deficits than one person can hold; the next hire continues
            del own[spare[int(rng.integers(len(spare)))]]
        own[skill] = draw_level(rng, tier)
    return own


def extend_skills_to_replacements(
    employees: pd.DataFrame, initial_skills: pd.DataFrame, exits: pd.DataFrame,
    cfg: GeneratorConfig, rng: np.random.Generator,
) -> pd.DataFrame:
    """initial_skills plus rows for every employee in `employees` that has none (the replacement
    hires), processed in hire order so coverage is checked against the staff active then."""
    exit_of = dict(zip(exits["employee_id"], pd.to_datetime(exits["exit_date"]), strict=True))
    holdings: Holdings = {}
    for r in initial_skills.itertuples(index=False):
        holdings.setdefault(r.employee_id, {})[r.skill] = int(r.level)
    new = employees[~employees["employee_id"].isin(holdings)].assign(
        hire_ts=lambda d: pd.to_datetime(d["hire_date"])).sort_values(["hire_ts", "employee_id"])
    rows = []
    for hire in new.itertuples(index=False):
        dept, skills = hire.department, cfg.skills[hire.department]
        members = _active_members(employees, exit_of, dept, hire.hire_ts)
        others = [e for e in members if e != hire.employee_id and e in holdings]
        size = len(others) + 1
        deficits = [s for s in skills
                    if holders(holdings, others, s) < required_holders(s, size)]
        own = _hire_skills(rng, role_tier(cfg, dept, hire.role), skills, deficits)
        holdings[hire.employee_id] = own
        rows += [(hire.employee_id, s, own[s]) for s in skills if s in own]
    return pd.concat([initial_skills, pd.DataFrame(rows, columns=SKILL_COLUMNS)],
                     ignore_index=True)


def active_coverage(employees: pd.DataFrame, employee_skill: pd.DataFrame, exits: pd.DataFrame,
                    cfg: GeneratorConfig, on: pd.Timestamp) -> pd.DataFrame:
    """Per department on a date: active staff, staff with any skill, fo_system holders and the
    skills below their minimum holder count."""
    exit_of = dict(zip(exits["employee_id"], pd.to_datetime(exits["exit_date"]), strict=True))
    held = employee_skill.groupby("employee_id")["skill"].agg(set).to_dict()
    out = []
    for dept, skills in cfg.skills.items():
        members = _active_members(employees, exit_of, dept, on)
        short = [s for s in skills if sum(s in held.get(e, set()) for e in members)
                 < required_holders(s, len(members))]
        out.append({"department": dept, "active": len(members),
                    "with_any_skill": sum(bool(held.get(e)) for e in members),
                    "fo_system_holders": sum("fo_system" in held.get(e, set()) for e in members),
                    "skills_below_minimum": ", ".join(short)})
    return pd.DataFrame(out)
