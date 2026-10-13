"""Roster solver (B2): OR-Tools CP-SAT with a greedy fallback and a cached demo-week roster.

HARD (never traded off): approved leave, at most one shift per day, minimum rest between shifts
on consecutive days, at least min_days_off per week, max_consecutive_days (counting the days
carried in from the previous week), min_headcount per department-shift-day, a required-skill
holder on every shift of departments listed in roster.required_skill (front_office: fo_system).
SOFT (integer weights in config): understaffed hours, overtime above standard_weekly_hours, the
spread (max - min) of weekend shifts and of night shifts inside each department, and a bonus
for every protected employee who gets a full weekend (Sat + Sun) off.

solve() NEVER publishes a roster that breaks a hard rule:
  - CP-SAT optimal / feasible -> the roster.
  - CP-SAT proves the week INFEASIBLE -> status "infeasible", no roster, and the causes: a relaxed
    re-solve (minimum headcount and the required skill become slack) lists EVERY department /
    day / shift that cannot be staffed, with the staff available after leave and carried-in
    days.
  - CP-SAT times out without any solution -> the cached roster for the same problem fingerprint,
    else the greedy heuristic, published ONLY if the independent checker finds zero hard
    violations; otherwise status "infeasible" with the checker's findings.
Statuses: optimal, feasible, cached, heuristic, infeasible. All data is SYNTHETIC.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from ortools.sat.python import cp_model

from backend.roster.check import Assignment, hard_violations, summarize
from backend.roster.problem import DAYS, Problem, forbidden_pairs

CACHE_DIR = Path(__file__).resolve().parent / "cache"


@dataclass
class Outcome:
    method: str  # cp_sat / greedy / cached
    status: str  # optimal / feasible / cached / heuristic / infeasible / unknown
    solve_seconds: float
    objective: float | None
    assignments: list[Assignment]
    hard_violations: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    causes: list[str] = field(default_factory=list)  # why a week is infeasible


def _vars(problem: Problem, model: cp_model.CpModel) -> dict[tuple[str, int, str], cp_model.IntVar]:
    x = {}
    for s in problem.staff:
        for d in range(DAYS):
            if d in s.leave_days:
                continue  # HARD: approved leave (no variable = cannot work)
            for sh in problem.shifts_of(s.department):
                x[(s.employee_id, d, sh)] = model.new_bool_var(f"x_{s.employee_id}_{d}_{sh}")
    return x


def build_model(problem: Problem, relax: bool = False) -> tuple[cp_model.CpModel, dict, dict]:
    """The CP-SAT model. relax=True turns minimum headcount and the required skill into slack
    variables and minimises only the slack (used to explain an infeasible week)."""
    cfg, model = problem.cfg, cp_model.CpModel()
    slack: dict[tuple[str, int, str, str], cp_model.IntVar] = {}
    x = _vars(problem, model)
    hours = {name: spec.hours for name, spec in cfg.shifts.items()}
    bad = forbidden_pairs(cfg)
    work = {}
    penalties = []
    for s in problem.staff:
        e, shifts = s.employee_id, problem.shifts_of(s.department)
        for d in range(DAYS):
            day_vars = [x[(e, d, sh)] for sh in shifts if (e, d, sh) in x]
            w = model.new_bool_var(f"w_{e}_{d}")
            model.add(sum(day_vars) == w)  # HARD: at most one shift a day (w is 0/1)
            work[(e, d)] = w
            if d + 1 < DAYS:
                for a, b in bad:  # HARD: minimum rest between consecutive days
                    if (e, d, a) in x and (e, d + 1, b) in x:
                        model.add(x[(e, d, a)] + x[(e, d + 1, b)] <= 1)
        days = [work[(e, d)] for d in range(DAYS)]
        model.add(sum(days) <= DAYS - cfg.min_days_off)  # HARD: weekly off
        m = cfg.max_consecutive_days  # HARD: consecutive days, incl. the carried-in run
        for start in range(DAYS - m):
            model.add(sum(days[start:start + m + 1]) <= m)
        lead = m - s.carry_days + 1  # days into the week before the run would exceed m
        if lead <= DAYS:
            model.add(sum(days[:max(lead, 1)]) <= max(lead - 1, 0))
        weekly_hours = sum(hours[sh] * x[(e, d, sh)] for d in range(DAYS) for sh in shifts
                           if (e, d, sh) in x)
        ot = model.new_int_var(0, 24 * DAYS, f"ot_{e}")
        model.add(ot >= weekly_hours - int(problem.standard_weekly_hours))
        penalties.append(cfg.weights.overtime_hour * ot)
        if e in problem.protected:  # SOFT bonus: full weekend off
            off = model.new_bool_var(f"weekend_off_{e}")
            for d in cfg.weekend_days:
                model.add(off <= 1 - work[(e, d)])
            penalties.append(-cfg.weights.protected_weekend_bonus * off)
    for (dept, d, sh), need in problem.demand.items():
        on = [x[(s.employee_id, d, sh)] for s in problem.staff
              if s.department == dept and (s.employee_id, d, sh) in x]
        gap = 0
        if relax:
            gap = slack[(dept, d, sh, "headcount")] = model.new_int_var(
                0, cfg.min_headcount, f"gap_{dept}_{d}_{sh}")
        model.add(sum(on) + gap >= cfg.min_headcount)  # HARD: minimum headcount
        skill = cfg.required_skill.get(dept)
        if skill:  # HARD: a required-skill holder on every shift
            sgap = 0
            if relax:
                sgap = slack[(dept, d, sh, skill)] = model.new_int_var(
                    0, 1, f"sgap_{dept}_{d}_{sh}")
            model.add(sum(x[(s.employee_id, d, sh)] for s in problem.staff
                          if s.department == dept and skill in s.skills
                          and (s.employee_id, d, sh) in x) + sgap >= 1)
        short = model.new_int_var(0, int(np.ceil(need)) + 1, f"short_{dept}_{d}_{sh}")
        model.add(short >= int(np.ceil(need)) - hours[sh] * sum(on))
        penalties.append(cfg.weights.understaffed_hour * short)
    for dept, shifts in cfg.department_shifts.items():
        members = [s.employee_id for s in problem.staff if s.department == dept]
        if len(members) < 2:
            continue
        counts = {"weekend": [sum(work[(e, d)] for d in cfg.weekend_days) for e in members]}
        if "night" in shifts:
            counts["night"] = [sum(x[(e, d, "night")] for d in range(DAYS) if (e, d, "night") in x)
                               for e in members]
        for key, vals in counts.items():
            hi = model.new_int_var(0, DAYS, f"hi_{key}_{dept}")
            lo = model.new_int_var(0, DAYS, f"lo_{key}_{dept}")
            for v in vals:
                model.add(hi >= v)
                model.add(lo <= v)
            weight = cfg.weights.weekend_spread if key == "weekend" else cfg.weights.night_spread
            penalties.append(weight * (hi - lo))
    model.minimize(sum(slack.values()) if relax else sum(penalties))
    return model, x, slack


def _solver(problem: Problem, deterministic: bool = False) -> cp_model.CpSolver:
    """Default: parallel search with a wall-clock limit (fast, but which of several equally good
    rosters comes back can vary). deterministic=True: CP-SAT's interleaved deterministic search
    with a work-unit limit, so the same problem always gives the same roster."""
    solver, cfg = cp_model.CpSolver(), problem.cfg
    solver.parameters.random_seed = cfg.seed
    if deterministic:
        d = cfg.deterministic
        solver.parameters.num_workers = d.num_workers
        solver.parameters.interleave_search = d.interleave_search
        solver.parameters.max_deterministic_time = d.max_deterministic_time
        solver.parameters.max_time_in_seconds = d.safety_seconds
    else:
        solver.parameters.max_time_in_seconds = cfg.time_limit_seconds
        solver.parameters.num_workers = cfg.num_workers
    return solver


def available_staff(problem: Problem, dept: str, day: int) -> int:
    """Staff of a department who could work on `day`: not on leave and not forced off by the
    run carried in from the previous week (a full run must end with a Monday off)."""
    m = problem.cfg.max_consecutive_days
    return sum(1 for s in problem.staff if s.department == dept and day not in s.leave_days
               and not (day == 0 and s.carry_days >= m))


def infeasibility_causes(problem: Problem) -> list[str]:
    """Every department / day / shift that cannot be staffed (relaxed re-solve)."""
    model, _, slack = build_model(problem, relax=True)
    solver = _solver(problem)
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ["no roster satisfies leave, rest, weekly-off and consecutive-day rules even with "
                "unstaffed shifts allowed"]
    short: dict[tuple[str, int], list[str]] = {}
    for (dept, d, sh, kind), var in slack.items():
        if solver.value(var):
            short.setdefault((dept, d), []).append(sh if kind == "headcount"
                                                    else f"{sh} (no {kind} holder)")
    causes = []
    for (dept, d), shifts in sorted(short.items(), key=lambda k: (k[0][1], k[0][0])):
        n_need = len(problem.shifts_of(dept))
        day = problem.days[d].strftime("%A %Y-%m-%d")
        causes.append(f"{dept}, {day}: {n_need} shifts need staff (min "
                      f"{problem.cfg.min_headcount} each), {available_staff(problem, dept, d)} "
                      f"available after leave and carried-in consecutive days; cannot staff: "
                      f"{', '.join(shifts)} (rest and weekly-off rules also bind)")
    return causes or ["infeasible for a reason other than staffing (check leave and carry-in)"]


def solve_cp_sat(problem: Problem, deterministic: bool = False) -> Outcome:
    model, x, _ = build_model(problem)
    solver = _solver(problem, deterministic)
    start = time.perf_counter()
    status = solver.solve(model)
    seconds = time.perf_counter() - start
    name = solver.status_name(status).lower()
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Outcome("cp_sat", name, seconds, None, [])
    assignments = [Assignment(e, d, sh) for (e, d, sh), v in x.items() if solver.value(v)]
    return Outcome("cp_sat", name, seconds, solver.objective_value, assignments)


def greedy(problem: Problem) -> Outcome:
    """Day by day, shift by shift: fill each department-shift with the available staff who have
    worked least, respecting leave, one shift a day, rest, weekly off and consecutive days."""
    cfg, start = problem.cfg, time.perf_counter()
    rng = np.random.default_rng(cfg.seed)
    hours = {name: spec.hours for name, spec in cfg.shifts.items()}
    bad = set(forbidden_pairs(cfg))
    done: dict[str, dict[int, str]] = {s.employee_id: {} for s in problem.staff}
    run = {s.employee_id: s.carry_days for s in problem.staff}
    out: list[Assignment] = []
    for d in range(DAYS):
        for (dept, day, sh), need in sorted(problem.demand.items(), key=lambda k: -k[1]):
            if day != d:
                continue
            target = max(cfg.min_headcount, int(np.ceil(need / hours[sh])))
            def ok(s, sh=sh, d=d, dept=dept):  # noqa: ANN001, ANN202
                e = s.employee_id
                return (s.department == dept and d not in s.leave_days and d not in done[e]
                        and len(done[e]) < DAYS - cfg.min_days_off
                        and run[e] < cfg.max_consecutive_days
                        and (d == 0 or (done[e].get(d - 1), sh) not in bad))
            pool = [s for s in problem.staff if ok(s)]
            rng.shuffle(pool)
            pool.sort(key=lambda s: len(done[s.employee_id]))
            skill = cfg.required_skill.get(dept)
            if skill:
                pool.sort(key=lambda s: skill not in s.skills)  # a holder first
            for s in pool[:target]:
                done[s.employee_id][d] = sh
                out.append(Assignment(s.employee_id, d, sh))
        for e in run:
            run[e] = run[e] + 1 if d in done[e] else 0
    return Outcome("greedy", "heuristic", time.perf_counter() - start, None, out)


def cache_path(problem: Problem) -> Path:
    """One file per exact problem (week + inputs + config), e.g. baseline and protected."""
    return CACHE_DIR / f"roster_{problem.week_start}_{problem.fingerprint()[:12]}.json"


def save_cache(problem: Problem, outcome: Outcome) -> Path:
    path = cache_path(problem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fingerprint": problem.fingerprint(), "status": outcome.status,
                                "assignments": [asdict(a) for a in outcome.assignments]},
                               indent=1) + "\n", encoding="utf-8")
    return path


def load_cache(problem: Problem) -> Outcome | None:
    path = cache_path(problem)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["fingerprint"] != problem.fingerprint():
        return None
    return Outcome("cached", "cached", 0.0, None,
                   [Assignment(**a) for a in data["assignments"]])


INFEASIBLE = "infeasible"


def _infeasible(outcome: Outcome, causes: list[str]) -> Outcome:
    return Outcome(outcome.method, INFEASIBLE, outcome.solve_seconds, None, [], causes=causes)


def solve(problem: Problem, use_cache: bool = False, deterministic: bool = False) -> Outcome:
    """Never returns a roster with a hard violation (see the module docstring)."""
    outcome = load_cache(problem) if use_cache else None
    if outcome is None:
        outcome = solve_cp_sat(problem, deterministic)
    if outcome.status == INFEASIBLE:  # proven by CP-SAT: explain it, publish nothing
        outcome = _infeasible(outcome, infeasibility_causes(problem))
    elif not outcome.assignments:  # timed out without any solution
        outcome = load_cache(problem) or greedy(problem)
        violations = hard_violations(problem, outcome.assignments)
        if violations:
            outcome = _infeasible(outcome, [
                f"no feasible roster found within {problem.cfg.time_limit_seconds:g} s and the "
                f"greedy fallback broke {len(violations)} hard rule(s); not published"]
                + violations)
    if outcome.assignments:
        outcome.hard_violations = hard_violations(problem, outcome.assignments)
        if outcome.hard_violations:  # unreachable by construction; refuse loudly, never publish
            raise RuntimeError(f"roster with hard violations: {outcome.hard_violations}")
    outcome.summary = summarize(problem, outcome.assignments)
    return outcome
