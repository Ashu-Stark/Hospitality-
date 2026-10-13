"""The served default hotel: the FICTIONAL Himsagar Ridge Resort, Mussoorie (himsagar).

24 rooms, 19 rostered staff (HS02..HS20; HS01 = hotel manager, not rostered), SYNTHETIC data from
ml/data/hotels/himsagar, roster overrides from backend/hotels/himsagar.yaml (security night-only,
front office morning + evening, maintenance evening on call). The other test files pin the
original dataset (conftest.py); this file always passes hotel="himsagar" explicitly.
"""

from __future__ import annotations

import uuid
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from backend.config import (
    DEFAULT_HOTEL,
    RosterConfig,
    hotel_data,
    hotel_key,
    load_backend_config,
    make_settings,
)
from backend.main import create_app
from backend.mongo import get_database
from backend.roster import stress
from backend.roster.problem import DAYS, build_problem
from backend.roster.solver import solve

STAFF = [f"HS{n:02d}" for n in range(2, 21)]


@pytest.fixture(scope="module")
def hs() -> TestClient:
    settings = make_settings(f"hoi_ops_test_{uuid.uuid4().hex[:12]}", mock=False,
                             mongodb_uri="mongomock://", hotel="himsagar")
    with TestClient(create_app(settings)) as c:
        yield c
    get_database(settings).client.drop_database(settings.database_name)


def test_hotel_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOI_HOTEL_DATA", raising=False)
    assert hotel_key() == DEFAULT_HOTEL == "himsagar"
    for alias in ("original", "default", "ml/data", "ORIGINAL"):
        assert hotel_key(alias) == "original"
    monkeypatch.setenv("HOI_HOTEL_DATA", "original")
    assert make_settings(mongodb_uri="mongomock://").hotel == "original"
    h = hotel_data("himsagar")
    assert h.rooms == 24 and h.data_dir.as_posix().endswith("ml/data/hotels/himsagar")
    assert hotel_data("original").rooms == 45
    with pytest.raises(FileNotFoundError):
        hotel_data("no_such_hotel")


def test_roster_overrides_documented_rules() -> None:
    r = load_backend_config(hotel="himsagar").roster
    assert r.department_shifts["security"] == ["night"]
    assert r.department_shifts["front_office"] == ["morning", "evening"]
    assert r.min_on("maintenance", "evening") == 0 and r.min_on("maintenance", "morning") == 1
    assert r.required_skill == {"front_office": "fo_system"} and r.hotel == "himsagar"
    o = load_backend_config(hotel="original").roster
    assert o.department_shifts["security"] == ["morning", "evening", "night"]
    assert o.min_headcount_by_shift == {} and "hotel" not in o.rules_dump()
    bad = r.model_dump() | {"min_headcount_by_shift": {"security": {"morning": 0}}}
    with pytest.raises(ValueError):
        RosterConfig.model_validate(bad)


def test_seed_forecast_and_scores(hs: TestClient) -> None:
    assert hs.post("/demo/reset").json()["employee_snapshot_rows"] == 19
    days = hs.get("/forecast", params={"from": "2029-12-24", "to": "2029-12-30"}).json()["days"]
    assert len(days) == 7 and all(0 <= d["mean"] <= 1 for d in days)
    scores = hs.post("/attrition/score", json={}).json()
    assert sorted(s["employee_id"] for s in scores) == STAFF


def test_demo_week_roster_is_valid(hs: TestClient) -> None:
    hs.post("/demo/reset")
    r = hs.post("/roster/generate", json={"use_cache": True, "deterministic": True}).json()
    assert r["status"] in ("cached", "optimal", "feasible") and r["hard_violations"] == []
    staff = {s["employee_id"]: s for s in hs.app.state.db["employee_snapshot"].find({}, {"_id": 0})}
    by_day_shift = Counter()
    fo_holder = set()
    for a in r["assignments"]:
        dept = staff[a["employee_id"]]["department"]
        by_day_shift[(dept, a["date"], a["shift"])] += 1
        if dept == "security":
            assert a["shift"] == "night"
        if dept == "front_office":
            assert a["shift"] in ("morning", "evening")
            if "fo_system" in staff[a["employee_id"]]["skills"]:
                fo_holder.add((a["date"], a["shift"]))
    dates = sorted({a["date"] for a in r["assignments"]})
    assert len(dates) == DAYS
    for d in dates:
        two = ("morning", "evening")
        for dept, shifts in (("housekeeping", two), ("kitchen", two), ("fnb_service", two),
                             ("front_office", two), ("maintenance", ("morning",)),
                             ("security", ("night",))):
            for sh in shifts:
                assert by_day_shift[(dept, d, sh)] >= 1, (dept, d, sh)
        assert (d, "morning") in fo_holder and (d, "evening") in fo_holder


def test_closed_loop_on_the_hotel(hs: TestClient) -> None:
    hs.post("/demo/reset")
    out = hs.post("/loop/run").json()
    assert out["flagged"] and set(out["flagged"]) <= set(STAFF)
    assert all(t["hard_violations"] == 0 for t in out["totals"].values())
    assert len(out["interventions"]) == 2 * len(out["flagged"])
    again = hs.post("/loop/run").json()  # deterministic, cached rosters
    assert [p["risk_change"] for p in again["people"]] == [p["risk_change"] for p in out["people"]]
    m = hs.get("/metrics/overview").json()
    assert m["flagged_count"] == len(out["flagged"]) and m["synthetic"]


def test_stress_scenarios_never_break_hard_rules() -> None:
    report = stress.run(n=12, seed=7, hotel="himsagar")
    assert report["hard_violations_total"] == 0
    assert report["solved"] + report["infeasible"] == 12
    assert report["infeasible_with_causes"] == report["infeasible"]


def test_optional_shift_still_needs_a_skill_holder_when_staffed() -> None:
    """A minimum-0 shift on a skill department: if anyone works it, a holder must be on it."""
    cfg = load_backend_config(hotel="himsagar").roster
    cfg = cfg.model_copy(update={"min_headcount_by_shift": {"front_office": {"evening": 0}}})
    rows = [{"employee_id": e, "department": "front_office", "skills": skills, "monthly_pay": 18000,
             "leave_days": 0, "is_demo_hero": False}
            for e, skills in (("F1", '["fo_system"]'), ("F2", '["fo_system"]'), ("F3", "[]"))]
    p = build_problem(cfg.demo_week, rows, [0.9] * DAYS, cfg, carry={})
    p.staff = [s for s in p.staff if s.department == "front_office"]
    p.demand = {k: v for k, v in p.demand.items() if k[0] == "front_office"}
    o = solve(p)
    assert o.assignments and o.hard_violations == []
    work = Counter((a.day, a.shift) for a in o.assignments)
    holders = {(a.day, a.shift) for a in o.assignments if a.employee_id in ("F1", "F2")}
    for (d, sh), n in work.items():
        assert n == 0 or (d, sh) in holders


def test_rest_rule_holds_across_the_week_boundary() -> None:
    """Rolling rosters: a Sunday evening (ends 23:00) cannot precede a Monday morning (7 h rest)."""
    from backend.roster.check import Assignment, hard_violations

    cfg = load_backend_config(hotel="himsagar").roster
    rows = [{"employee_id": e, "department": "kitchen", "skills": "[]", "monthly_pay": 20000,
             "leave_days": 0, "is_demo_hero": False} for e in ("K1", "K2", "K3")]
    last = {"K1": "evening", "K2": "evening"}
    p = build_problem(cfg.demo_week, rows, [0.9] * DAYS, cfg, carry={}, last_shift=last)
    p.staff = [s for s in p.staff if s.department == "kitchen"]
    p.demand = {k: v for k, v in p.demand.items() if k[0] == "kitchen"}
    o = solve(p)
    assert o.assignments and o.hard_violations == []
    monday_morning = {a.employee_id for a in o.assignments if a.day == 0 and a.shift == "morning"}
    assert monday_morning == {"K3"}
    assert hard_violations(p, [Assignment("K1", 0, "morning")])  # the checker catches it too
    plain = build_problem(cfg.demo_week, rows, [0.9] * DAYS, cfg, carry={})
    assert plain.fingerprint() != p.fingerprint()
