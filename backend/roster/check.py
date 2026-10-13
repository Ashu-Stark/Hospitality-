"""Independent hard-constraint checker and the roster summary (B2).

hard_violations() re-derives every HARD rule from the assignments alone (it does not trust the
solver), so the 100-scenario test can prove zero violations. summarize() gives coverage, cost,
per-person fairness and the soft goals that were not met. All data is SYNTHETIC.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from backend.roster.problem import DAYS, Problem, forbidden_pairs

WEEKS_PER_MONTH = 52 / 12


@dataclass(frozen=True)
class Assignment:
    employee_id: str
    day: int  # 0..6 (Mon..Sun)
    shift: str


def _work(problem: Problem, assignments: list[Assignment]) -> dict[str, dict[int, str]]:
    """employee -> {day: shift} (a second shift on the same day overwrites; see duplicates)."""
    out: dict[str, dict[int, str]] = {s.employee_id: {} for s in problem.staff}
    for a in assignments:
        out.setdefault(a.employee_id, {})[a.day] = a.shift
    return out


def hard_violations(problem: Problem, assignments: list[Assignment]) -> list[str]:
    cfg, v = problem.cfg, []
    staff = {s.employee_id: s for s in problem.staff}
    work = _work(problem, assignments)
    bad_pairs = set(forbidden_pairs(cfg))
    per_day = Counter((a.employee_id, a.day) for a in assignments)
    v += [f"{e}: {n} shifts on day {d}" for (e, d), n in per_day.items() if n > 1]
    for e, real in work.items():
        s = staff.get(e)
        if s is None:
            v.append(f"{e}: not in the staff list")
            continue
        for d, sh in real.items():
            if d in s.leave_days:
                v.append(f"{e}: works on approved leave (day {d})")
            if sh not in problem.shifts_of(s.department):
                v.append(f"{e}: shift {sh} not used by {s.department}")
            if d + 1 in real and (sh, real[d + 1]) in bad_pairs:
                v.append(f"{e}: less than {cfg.min_rest_hours} h rest between day {d} and {d + 1}")
        if len(real) > DAYS - cfg.min_days_off:
            v.append(f"{e}: no weekly off ({len(real)} days)")
        run = s.carry_days
        for d in range(DAYS):
            run = run + 1 if d in real else 0
            if run > cfg.max_consecutive_days:
                v.append(f"{e}: {run} consecutive days by day {d}")
                break
    for (dept, d, sh) in problem.demand:
        on = [e for e, days in work.items() if days.get(d) == sh
              and e in staff and staff[e].department == dept]
        if len(on) < cfg.min_headcount:
            v.append(f"{dept} day {d} {sh}: {len(on)} staff < minimum {cfg.min_headcount}")
        skill = cfg.required_skill.get(dept)
        if skill and not any(skill in staff[e].skills for e in on):
            v.append(f"{dept} day {d} {sh}: no {skill} holder")
    return v


def hourly_rate(monthly_pay: float, standard_weekly_hours: float) -> float:
    return monthly_pay / (WEEKS_PER_MONTH * standard_weekly_hours)


def summarize(problem: Problem, assignments: list[Assignment]) -> dict:
    cfg = problem.cfg
    hours_of = {name: spec.hours for name, spec in cfg.shifts.items()}
    staff = {s.employee_id: s for s in problem.staff}
    work = _work(problem, assignments)
    # coverage
    coverage, short = [], []
    for dept in cfg.department_shifts:
        req = sum(h for (dp, _, _), h in problem.demand.items() if dp == dept)
        sched, n_short, h_short = 0.0, 0, 0.0
        for (dp, d, sh), need in problem.demand.items():
            if dp != dept:
                continue
            got = hours_of[sh] * sum(1 for e, days in work.items()
                                     if days.get(d) == sh and staff[e].department == dept)
            sched += got
            if got + 1e-9 < need:
                n_short += 1
                h_short += need - got
                short.append({"goal": "understaffed", "department": dept, "day": d,
                              "shift": sh, "hours_short": round(need - got, 1)})
        coverage.append({"department": dept, "required_hours": round(req, 1),
                         "scheduled_hours": round(sched, 1),
                         "coverage": round(min(sched / req, 1.0), 4) if req else 1.0,
                         "understaffed_shifts": n_short, "understaffed_hours": round(h_short, 1)})
    # cost, overtime, fairness
    people, overtime_goals, regular_cost, ot_cost, ot_hours = [], [], 0.0, 0.0, 0.0
    by_dept: dict[str, list[str]] = defaultdict(list)
    for s in problem.staff:
        by_dept[s.department].append(s.employee_id)
    stats = {}
    for e, days in work.items():
        hours = sum(hours_of[sh] for sh in days.values())
        ot = max(0.0, hours - problem.standard_weekly_hours)
        rate = hourly_rate(staff[e].monthly_pay, problem.standard_weekly_hours)
        regular_cost += rate * (hours - ot)
        ot_cost += rate * ot * cfg.overtime_premium
        ot_hours += ot
        weekend = sum(1 for d in days if d in cfg.weekend_days)
        stats[e] = {"hours": hours, "overtime_hours": ot, "weekend_shifts": weekend,
                    "night_shifts": sum(1 for sh in days.values() if sh == "night"),
                    "full_weekend_off": all(d not in days for d in cfg.weekend_days),
                    "days_worked": len(days)}
        if ot > 0:
            overtime_goals.append({"goal": "overtime", "employee_id": e, "hours": ot})
    spread_goals = []
    for dept, members in by_dept.items():
        for key, goal in (("weekend_shifts", "weekend_spread"), ("night_shifts", "night_spread")):
            if key == "night_shifts" and "night" not in cfg.department_shifts[dept]:
                continue
            vals = [stats[e][key] for e in members]
            avg = sum(vals) / len(vals)
            for e in members:
                stats[e][f"dept_avg_{key}"] = round(avg, 2)
            if max(vals) - min(vals) > 1:
                spread_goals.append({"goal": goal, "department": dept,
                                     "min": min(vals), "max": max(vals)})
    for e, st in stats.items():
        gap = abs(st["weekend_shifts"] - st.get("dept_avg_weekend_shifts", st["weekend_shifts"]))
        gap += abs(st["night_shifts"] - st.get("dept_avg_night_shifts", st["night_shifts"]))
        people.append({"employee_id": e, "department": staff[e].department,
                       "is_demo_hero": staff[e].is_demo_hero, "protected": e in problem.protected,
                       **st, "fairness_score": round(1 / (1 + gap), 3)})
    protected_goals = [{"goal": "protected_weekend_off", "employee_id": e}
                       for e in sorted(problem.protected) if e in stats
                       and not stats[e]["full_weekend_off"]]
    return {
        "coverage": coverage,
        "cost": {"regular_cost_inr": round(regular_cost), "overtime_hours": round(ot_hours, 1),
                 "overtime_cost_inr": round(ot_cost),
                 "total_cost_inr": round(regular_cost + ot_cost),
                 "understaffed_shifts": sum(c["understaffed_shifts"] for c in coverage),
                 "understaffed_hours": round(sum(c["understaffed_hours"] for c in coverage), 1)},
        "people": sorted(people, key=lambda p: p["employee_id"]),
        "violated_soft_goals": short + overtime_goals + spread_goals + protected_goals,
    }
