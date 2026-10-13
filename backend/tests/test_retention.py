"""Retention check-ins on the FICTIONAL Himsagar hotel (SYNTHETIC data): low / moderate -> talk
with 2-3 plain talking points and a logged talk (task done + intervention kind talk, idempotent);
high -> find cover on the job portal (the portal search itself lives in the platform API)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend import retention
from backend.config import make_settings
from backend.main import create_app
from backend.mongo import get_database

WEEK = "2029-12-24"


@pytest.fixture(scope="module")
def hs() -> TestClient:
    settings = make_settings(f"hoi_ops_test_{uuid.uuid4().hex[:12]}", mock=False,
                             mongodb_uri="mongomock://", hotel="himsagar")
    with TestClient(create_app(settings)) as c:
        yield c
    get_database(settings).client.drop_database(settings.database_name)


@pytest.fixture(scope="module")
def plans(hs: TestClient) -> dict[str, dict]:
    r = hs.get("/retention/plan", params={"week_start": WEEK})
    assert r.status_code == 200, r.text
    return {p["employee_id"]: p for p in r.json()}


def test_every_scored_person_gets_a_plan(plans: dict[str, dict]) -> None:
    assert sorted(plans) == [f"HS{n:02d}" for n in range(2, 21)]
    for p in plans.values():
        assert 2 <= len(p["talking_points"]) <= 3 and p["synthetic"]
        assert p["next_step"] == ("find_cover" if p["level"] == "high" else "talk")
        assert not any(c in " ".join(p["talking_points"]) for c in ("_", "log-odds", "%"))


def test_low_level_means_talk(plans: dict[str, dict]) -> None:
    p = plans["HS02"]
    assert p["level"] == "low" and p["level_label"] == "Low"
    assert p["next_step_label"] == "Talk to them"
    assert p["talking_points"][0] == retention.TALKING_POINTS["overtime_overload"]


def test_moderate_level_means_talk(plans: dict[str, dict]) -> None:
    p = plans["HS08"]  # model band "watch"
    assert p["level"] == "moderate" and p["next_step"] == "talk"


def test_high_level_means_find_cover_and_points_follow_reasons(plans: dict[str, dict]) -> None:
    p = plans["HS05"]
    assert p["level"] == "high" and p["next_step"] == "find_cover"
    assert p["talking_points"] == [retention.TALKING_POINTS[c] for c in p["reasons"]][:3]


def test_seasonal_contract_end_gets_the_season_point(plans: dict[str, dict]) -> None:
    p = plans["HS06"]
    assert p["talking_points"][0] == retention.TALKING_POINTS["season_end_exit"]


def test_log_talk_reuses_tasks_and_interventions_and_is_idempotent(hs: TestClient,
                                                                   plans: dict[str, dict]) -> None:
    point = plans["HS08"]["talking_points"][0]
    body = {"employee_id": "HS08", "week_start": WEEK, "points": [point, "made up point"]}
    first = hs.post("/retention/talks", json=body)
    assert first.status_code == 200, first.text
    t = first.json()
    assert t["logged"] and t["points"] == [point]  # only suggested points are stored
    again = hs.post("/retention/talks", json=body).json()
    assert not again["logged"] and again["intervention_id"] == t["intervention_id"]
    assert again["task_id"] == t["task_id"]
    rows = hs.get("/interventions", params={"employee_id": "HS08"}).json()
    assert len(rows) == 1 and rows[0]["task_status"] == "done"
    assert rows[0]["action"] == retention.TALK_ACTION
    task = next(x for x in hs.get("/tasks").json() if x["id"] == t["task_id"])
    assert task["status"] == "done" and task["employee_id"] == "HS08"
    plan = hs.get("/retention/plan", params={"week_start": WEEK, "employee_id": "HS08"}).json()
    assert plan[0]["talked"] and plan[0]["talked_at"]
    assert not hs.get("/retention/plan", params={"week_start": WEEK,
                                                 "employee_id": "HS02"}).json()[0]["talked"]


def test_log_talk_rejects_bad_input(hs: TestClient) -> None:
    assert hs.post("/retention/talks", json={"employee_id": "HS08; drop"}).status_code == 422
    r = hs.post("/retention/talks", json={"employee_id": "HS99", "week_start": WEEK})
    assert r.status_code in (404, 422)
    too_many = {"employee_id": "HS08", "points": ["a", "b", "c", "d"]}
    assert hs.post("/retention/talks", json=too_many).status_code == 422
