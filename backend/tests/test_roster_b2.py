"""B2: roster solver, independent checker, endpoints and the 100-scenario stress test."""

from dataclasses import replace

import pytest

from backend.config import load_backend_config
from backend.db import snapshot_frame
from backend.roster.check import Assignment, hard_violations
from backend.roster.problem import DAYS, build_problem, forbidden_pairs, place_leave
from backend.roster.solver import greedy, load_cache, solve, solve_cp_sat


@pytest.fixture(scope="module")
def cfg():
    return load_backend_config().roster


@pytest.fixture(scope="module")
def problem(cfg):
    rows = snapshot_frame().to_dict("records")
    return build_problem(cfg.demo_week, rows, [0.75] * DAYS, cfg)


def test_rest_rule_forbids_short_turnarounds(cfg) -> None:
    pairs = set(forbidden_pairs(cfg))
    assert ("evening", "morning") in pairs and ("night", "morning") in pairs
    assert ("morning", "morning") not in pairs


def test_leave_placement_is_seeded_and_consecutive() -> None:
    a, b = place_leave("E071", 3, 42), place_leave("E071", 3, 42)
    assert a == b and len(a) == 3 and max(a) - min(a) == 2
    assert place_leave("E071", 0, 42) == frozenset()


def test_checker_catches_each_hard_rule(problem) -> None:
    fo = next(s for s in problem.staff if s.department == "front_office")
    on_leave = replace(fo, leave_days=frozenset({0}))
    p = replace(problem, staff=[on_leave if s is fo else s for s in problem.staff])
    bad = [Assignment(fo.employee_id, 0, "morning"),  # on leave
           Assignment(fo.employee_id, 1, "evening"), Assignment(fo.employee_id, 2, "morning"),
           Assignment(fo.employee_id, 1, "night")]  # two shifts on day 1
    v = " | ".join(hard_violations(p, bad))
    for text in ("approved leave", "shifts on day 1", "rest", "staff < minimum", "no fo_system"):
        assert text in v, text


def test_cp_sat_real_week_has_no_hard_violations(problem) -> None:
    o = solve(problem)
    assert o.method == "cp_sat" and o.status in {"optimal", "feasible"}
    assert o.hard_violations == []
    assert o.solve_seconds <= problem.cfg.time_limit_seconds + 2
    people = {p["employee_id"]: p for p in o.summary["people"]}
    assert all(0 < p["fairness_score"] <= 1 for p in people.values())


def test_protected_bonus_gives_weekend_off(problem) -> None:
    flagged = frozenset({"H901"})
    o = solve(replace(problem, protected=flagged))
    me = next(p for p in o.summary["people"] if p["employee_id"] == "H901")
    assert me["protected"] and me["full_weekend_off"]


def test_greedy_output_is_checked(problem) -> None:
    g = greedy(problem)
    assert g.method == "greedy" and g.assignments
    assert isinstance(hard_violations(problem, g.assignments), list)


def test_infeasible_week_lists_every_short_slot(problem) -> None:
    sec = [s for s in problem.staff if s.department == "security"]
    rested = {s.employee_id for s in sec[:3]}  # 3 of 5 must rest on Monday
    staff = [replace(s, carry_days=problem.cfg.max_consecutive_days)
             if s.employee_id in rested else s for s in problem.staff]
    o = solve(replace(problem, staff=staff))
    assert o.status == "infeasible" and o.assignments == [] and o.hard_violations == []
    assert any(c.startswith("security, Monday") and "2 available" in c for c in o.causes), o.causes


def test_greedy_with_violations_is_never_published(problem, monkeypatch) -> None:
    import backend.roster.solver as solver

    timeout = solver.Outcome("cp_sat", "unknown", problem.cfg.time_limit_seconds, None, [])
    monkeypatch.setattr(solver, "solve_cp_sat", lambda p, deterministic=False: timeout)
    monkeypatch.setattr(solver, "load_cache", lambda p: None)
    bad = solver.Outcome("greedy", "heuristic", 0.0, None,
                         [Assignment(problem.staff[0].employee_id, 0, "morning")])
    monkeypatch.setattr(solver, "greedy", lambda p: bad)
    o = solver.solve(problem)
    assert o.status == "infeasible" and o.assignments == []
    assert "greedy fallback broke" in o.causes[0]


def test_deterministic_solve_is_reproducible(problem) -> None:
    a = solve_cp_sat(problem, deterministic=True)
    b = solve_cp_sat(problem, deterministic=True)
    assert a.status == "optimal" and a.objective == b.objective
    assert sorted(map(str, a.assignments)) == sorted(map(str, b.assignments))


def test_cache_only_matches_the_same_problem(problem, tmp_path, monkeypatch) -> None:
    import backend.roster.solver as solver

    monkeypatch.setattr(solver, "CACHE_DIR", tmp_path)
    o = solve_cp_sat(problem)
    solver.save_cache(problem, o)
    assert load_cache(problem) is not None
    assert load_cache(replace(problem, protected=frozenset({"H901"}))) is None


def test_roster_endpoints(client) -> None:
    r = client.post("/roster/generate", json={"use_cache": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hard_violations"] == [] and body["synthetic"]
    assert body["method"] in {"cached", "cp_sat"} and len(body["assignments"]) > 0
    got = client.get(f"/roster/{body['id']}").json()
    assert got["id"] == body["id"] and len(got["assignments"]) == len(body["assignments"])
    assert client.get("/roster/9999").status_code == 404
    assert client.post("/roster/generate", json={"protected_ids": ["NOPE"]}).status_code == 422


@pytest.mark.slow
def test_100_random_scenarios_have_zero_hard_violations() -> None:
    from backend.roster.stress import run

    report = run(100)
    assert report["hard_violations_total"] == 0, report
    assert report["solved"] + report["infeasible"] == 100
    assert report["infeasible_with_causes"] == report["infeasible"]
    for r in report["results"]:
        assert r["published"] != (r["status"] == "infeasible")
