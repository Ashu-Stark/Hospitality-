"""Operational scenario tests on the FICTIONAL Himsagar Ridge Resort (SYNTHETIC data), offline on mongomock.

Run from the repo root:  .venv\\Scripts\\python.exe -m pytest -q scripts/tests
(The full numbers come from scripts/scenario_report.py; these tests assert the invariants on smaller runs.)
The day simulation patches the platform's clock in this process, so run this folder on its own.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hoi_scenarios as hs  # noqa: E402

hs.configure_offline_env()
logging.disable(logging.WARNING)
HS = {f"HS{n:02d}" for n in range(2, 21)}


@pytest.fixture(scope="module")
def ops():
    return hs.ops_client()


@pytest.fixture(scope="module")
def demo(ops):
    return hs.roster_demo_week(ops)


@pytest.fixture(scope="module")
def loop(ops):
    return hs.ops_loop(ops)


@pytest.fixture(scope="module")
def day(ops, demo, loop):
    return hs.DaySim(ops, seed=11, roster=demo["roster"], bands=loop["bands_by_employee"]).run()


def test_demo_week_roster(demo):
    assert demo["hard_violations"] == 0 and demo["status"] in ("cached", "optimal", "feasible")
    assert demo["coverage_pct"] >= 90 and demo["shifts"] > 100
    assert {a["employee_id"] for a in demo["roster"]["assignments"]} <= HS


@pytest.mark.parametrize("mode", ["random", "data"])
def test_stress_never_publishes_a_rule_break(mode):
    st = hs.roster_stress(12, seed=3, carry_mode=mode)
    assert st["hard_violations_total"] == 0
    assert st["solved"] + st["infeasible"] == 12
    assert st["infeasible_with_causes"] == st["infeasible"]  # every impossible week says why
    assert st["solve_seconds"]["max"] < 15


def test_four_rolling_weeks_carry_runs_and_rest():
    roll = hs.roster_rolling(4)
    assert [w["status"] for w in roll["weeks"]] and all(w["status"] in ("optimal", "feasible") for w in roll["weeks"])
    assert len(roll["weeks"]) == 4 and all(w["hard_violations"] == 0 for w in roll["weeks"])
    assert roll["max_consecutive_days_stitched"] <= roll["limit"]
    assert roll["rest_violations_across_boundaries"] == 0


def test_attrition_and_closed_loop(loop):
    assert loop["scored"] == 19 and set(loop["bands_by_employee"]) == HS
    assert loop["flagged"] and set(loop["flagged"]) <= HS
    assert loop["interventions"] == 2 * len(loop["flagged"])
    assert all(t["hard_violations"] == 0 for t in loop["totals"].values())


def test_day_dispatch_invariants(day, loop):
    assert day["jobs_total"] >= 50
    assert day["off_shift_or_wrong_department_offers"] == 0  # nobody gets a job off shift or outside their department
    assert day["every_job_assigned_or_escalated"]
    assert day["final_status"].get("done", 0) >= 0.9 * day["jobs_total"]
    flagged = [e for e, b in loop["bands_by_employee"].items() if b == "high"]
    g = day["retention_guard"]
    if g["offers_to_flagged"]:
        assert set(g["guard_applied_on_offers"]) == {-15}  # the retention guard lowers flagged staff's ranking
    assert g["flagged"] == flagged
    perf = day["performance"]
    assert perf["k_min_rule_holds"] and perf["min_jobs"] == 5
    assert all((s is None) == (n < 5) for s, n in perf["scores"].values())


def test_day_rooms_guests_inventory(day):
    rooms = day["rooms"]
    assert rooms["checked_out"] == 24 and rooms["made_ready"] == 24  # every room: checkout -> clean -> inspect -> ready
    assert rooms["inspections"].get("pass", 0) >= 24
    assert rooms["check_ins"] >= 18
    c = day["concierge"]
    assert c.get("source_rules", 0) > 0 and not c.get("source_llm")  # rule-based path, no AI calls
    assert day["events"].get("late_requests", 0) == 5
    assert day["guest_services"]["late_checkouts_pending"] == 0
    assert day["guest_services"]["feedback_count"] >= 5
    inv = day["inventory"]
    assert inv["ledger_errors"] == [] and inv["daily_issue"]["units"] > 0
    assert inv["stock_value_after_inr"] < inv["stock_value_before_inr"]


def test_voice_onboarding_creates_the_hotel(ops):
    out = hs.onboarding_demo(ops)
    assert out["created"] and out["property_saved"] and out["rooms"] == 24 and out["location"] == "Mussoorie"
