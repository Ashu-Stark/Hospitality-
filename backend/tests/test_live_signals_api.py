"""POST /attrition/score with the hotel's live weekly facts (platform GET /people/signals shape)
on the FICTIONAL Himsagar hotel. Live people are scored from live records only (data_source
live); the rest fall back to the SYNTHETIC demo tables, labelled demo_synthetic. Every record
here is a SYNTHETIC test value; staff are ids only."""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import make_settings
from backend.main import create_app
from backend.mongo import get_database

HOTEL = Path(__file__).resolve().parents[2] / "ml" / "data" / "hotels" / "himsagar" / "hotel.json"
W0 = date(2026, 8, 3)
LIVE_IDS = ["HS04", "HS05", "HS09"]


@pytest.fixture(scope="module")
def hs() -> TestClient:
    settings = make_settings(f"hoi_ops_test_{uuid.uuid4().hex[:12]}", mock=False,
                             mongodb_uri="mongomock://", hotel="himsagar")
    with TestClient(create_app(settings)) as c:
        c.app.state.weather = None
        yield c
    get_database(settings).client.drop_database(settings.database_name)


def _feed(weeks: int, ids: list[str] = LIVE_IDS) -> dict:
    staff = {s["employee_id"]: s for s in json.loads(HOTEL.read_text("utf-8"))["staff"]}
    profiles = [{"employee_id": e, "department": staff[e]["department"],
                 "role_title": staff[e]["role_title"], "contract_type": staff[e]["contract_type"],
                 "joining_date": "2024-04-01", "pay_band": "at", "last_raise_date": "2025-10-01"}
                for e in ids]
    records = [{"employee_id": e, "week_start": (W0 + timedelta(weeks=k)).isoformat(),
                "roster_published": True, "worked_days": [0, 1, 2, 3, 4, 5], "shift_hours": 54,
                "jobs_done": 5, "jobs_on_time": 4, "jobs_offered": 6, "jobs_declined": 1,
                "median_response_seconds": 9, "recognition_points": 40, "pulse": "ok"}
               for e in ids for k in range(weeks)]
    return {"profiles": profiles, "records": records, "leave_marks_used": True,
            "festival_dates": []}


def test_live_people_are_scored_from_live_records(hs: TestClient) -> None:
    r = hs.post("/attrition/score", json={"live_signals": _feed(6)})
    assert r.status_code == 200, r.text
    by = {s["employee_id"]: s for s in r.json()}
    for e in LIVE_IDS:
        s = by[e]
        assert s["data_source"] == "live" and s["weeks_of_history"] == 6
        assert s["week_start"] == (W0 + timedelta(weeks=5)).isoformat()
        assert {"shifts", "jobs", "thank-yous", "weekly answers"} <= set(s["data_sources"])
        assert s["confidence"] in ("low", "medium")
        assert "context" in s and s["context"]["thank_you_points_4w"] == 160
    # everyone else: the SYNTHETIC demo week, said so per person
    demo = [s for s in by.values() if s["employee_id"] not in LIVE_IDS]
    assert demo and all(s["data_source"] == "demo_synthetic" for s in demo)
    assert all(any(c["name"] == "live_data" for c in s["checks"]) for s in demo)
    assert all(s["data_sources"] == ["synthetic demo data"] for s in demo)


def test_short_history_is_low_confidence(hs: TestClient) -> None:
    r = hs.post("/attrition/score", json={"live_signals": _feed(2), "employee_ids": ["HS05"],
                                          "fallback_to_demo": False})
    assert r.status_code == 200, r.text
    (s,) = r.json()
    assert s["data_source"] == "live" and s["confidence"] == "low"
    assert any(c["name"] == "short_history" for c in s["checks"])


def test_no_live_records_falls_back_to_demo_and_says_so(hs: TestClient) -> None:
    r = hs.post("/attrition/score", json={"live_signals": {"profiles": [], "records": []}})
    assert r.status_code == 200, r.text
    assert all(s["data_source"] == "demo_synthetic" for s in r.json())
    assert all(any(c["name"] == "live_data" for c in s["checks"]) for s in r.json())
    r = hs.post("/attrition/score", json={"live_signals": {"profiles": [], "records": []},
                                          "fallback_to_demo": False})
    assert r.status_code == 422


def test_without_live_signals_nothing_changes(hs: TestClient) -> None:
    r = hs.post("/attrition/score", json={})
    assert r.status_code == 200
    assert all(s["data_source"] == "demo_synthetic" and s["weeks_of_history"] is None
               for s in r.json())
    assert not any(c["name"] == "live_data" for s in r.json() for c in s["checks"])


def test_logged_check_ins_are_counted(hs: TestClient) -> None:
    r = hs.post("/retention/talks", json={"employee_id": "HS05", "week_start": "2029-12-24"})
    assert r.status_code == 200, r.text
    feed = _feed(4)
    this_week = date.today() - timedelta(days=date.today().weekday())
    feed["records"].append({"employee_id": "HS05", "week_start": this_week.isoformat(),
                            "roster_published": True, "worked_days": [0, 1], "shift_hours": 18})
    s = next(x for x in hs.post("/attrition/score", json={"live_signals": feed}).json()
             if x["employee_id"] == "HS05")
    assert s["context"]["checkins_logged"] == 1 and "check-ins" in s["data_sources"]
