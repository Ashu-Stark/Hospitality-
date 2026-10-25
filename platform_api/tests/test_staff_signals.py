"""Staff signals for the staff-leaving estimate (services/staff_signals.py): roster history, jobs, HR record (owner / HR
only), leave marks (no reasons), the consented weekly 1-tap answer. Offline on mongomock; SYNTHETIC test values; ids only."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from conftest import auth

from hoi_platform import mongo
from hoi_platform.services import dispatch, staff_signals, worklog

TID = "org_demo"
EMP = "HS05"  # housekeeping attendant in the demo hotel


def _last_week() -> date:
    today = datetime.now(worklog.local_tz()).date()
    return today - timedelta(days=today.weekday() + 7)


def _local(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=worklog.local_tz()).astimezone(UTC)


@pytest.fixture
def week():
    """Last complete week: HS05 on morning shifts all 7 days, one job finished late, one declined offer. Cleaned after."""
    ws = _last_week()
    snap = mongo.col("roster_snapshots").find_one({"tenant_id": TID}, {"_id": 0})
    days = [ws + timedelta(days=i) for i in range(7)]
    dispatch.publish_roster(
        TID, ws.isoformat(), [{"employee_id": EMP, "date": d.isoformat(), "shift": "morning", "hours": 9} for d in days]
    )
    d1 = days[1]
    jobs = [
        {  # accepted after 6 s, done within target, but 30 min after the morning shift ended (15:00)
            "id": "sigtest_1",
            "tenant_id": TID,
            "title": "Clean room 104",
            "department": "housekeeping",
            "status": "done",
            "urgency": "medium",
            "assigned_to": EMP,
            "created_at": _local(d1, 14, 50),
            "accepted_at": _local(d1, 14, 51),
            "done_at": _local(d1, 15, 30),
            "attempts": [
                {
                    "employee_id": EMP,
                    "offered_at": _local(d1, 14, 50),
                    "at": _local(
                        d1,
                        14,
                        50,
                    )
                    + timedelta(seconds=6),
                    "outcome": "accepted",
                }
            ],
        },
        {  # declined by HS05
            "id": "sigtest_2",
            "tenant_id": TID,
            "title": "Towels 202",
            "department": "housekeeping",
            "status": "done",
            "urgency": "low",
            "assigned_to": "HS04",
            "created_at": _local(d1, 10),
            "accepted_at": _local(d1, 10, 1),
            "done_at": _local(d1, 10, 20),
            "attempts": [
                {"employee_id": EMP, "offered_at": _local(d1, 10), "at": _local(d1, 10) + timedelta(seconds=9), "outcome": "declined"},
                {"employee_id": "HS04", "offered_at": _local(d1, 10), "at": _local(d1, 10, 1), "outcome": "accepted"},
            ],
        },
    ]
    mongo.col("jobs").insert_many([dict(j) for j in jobs])
    yield ws
    mongo.col("jobs").delete_many({"id": {"$in": [j["id"] for j in jobs]}})
    for name in ("roster_history", "staff_hr", "staff_leave", "pulse_consent", "pulse_answers"):
        mongo.col(name).delete_many({"tenant_id": TID})
    if snap:
        mongo.col("roster_snapshots").replace_one({"tenant_id": TID}, {**snap, "tenant_id": TID}, upsert=True)


def _rec(feed: dict, emp: str, ws: date) -> dict:
    return next(r for r in feed["records"] if r["employee_id"] == emp and r["week_start"] == ws.isoformat())


def test_publish_keeps_the_roster_week(week):
    h = mongo.col("roster_history").find_one({"tenant_id": TID, "week_start": week.isoformat()})
    assert h and len(h["assignments"]) == 7


def test_weekly_facts_from_roster_and_jobs(client, owner, week):
    feed = client.get("/people/signals?weeks=2", headers=owner).json()
    assert feed["week_start"] == week.isoformat() and feed["synthetic"] is True
    r = _rec(feed, EMP, week)
    assert r["roster_published"] and r["worked_days"] == list(range(7))
    assert r["shift_hours"] == 63 and r["night_shifts"] == 0 and r["short_rest"] == 0
    assert r["jobs_done"] == 1 and r["jobs_on_time"] == 1
    assert r["jobs_offered"] == 2 and r["jobs_declined"] == 1 and r["jobs_timed_out"] == 0
    assert r["median_response_seconds"] == 6.0
    assert r["late_finish_minutes"] == 30.0
    assert r["team_jobs_done"] == 2
    # everyone in a published roster week gets a record (an empty roster row = all days off)
    other = _rec(feed, "HS09", week)
    assert other["roster_published"] and other["worked_days"] == []


def test_hr_record_is_owner_and_hr_only_and_pay_stays_out_of_the_audit(client, owner, hr, week):
    body = {"joining_date": "2024-03-01", "pay_band": "below", "monthly_pay": 13500, "last_raise_date": "2025-04-01"}
    assert client.put(f"/people/hr/{EMP}", json=body, headers=hr).status_code == 200
    head = auth(client, "demo.housekeeping")
    assert client.put(f"/people/hr/{EMP}", json=body, headers=head).status_code == 403
    assert client.get(f"/people/hr/{EMP}", headers=auth(client, EMP)).status_code == 403
    assert client.put(f"/people/hr/{EMP}", json={"gender": "x"}, headers=owner).status_code == 422  # no personal fields
    rec = client.get(f"/people/hr/{EMP}", headers=owner).json()
    assert rec["pay_band"] == "below" and rec["monthly_pay"] == 13500
    log = " ".join(a["detail"] for a in client.get("/workspace/audit", headers=owner).json())
    assert "13500" not in log and "pay_band" in log
    feed = client.get("/people/signals?weeks=1", headers=owner).json()
    p = next(x for x in feed["profiles"] if x["employee_id"] == EMP)
    assert p["pay_band"] == "below" and p["joining_date"] == "2024-03-01"
    # department heads: own department, pay withheld
    feed = client.get("/people/signals?weeks=1", headers=head).json()
    assert {x["department"] for x in feed["profiles"]} == {"housekeeping"}
    p = next(x for x in feed["profiles"] if x["employee_id"] == EMP)
    assert p["pay_withheld"] is True and "pay_band" not in p and "monthly_pay" not in p
    assert client.get("/people/signals", headers=auth(client, EMP)).status_code == 403


def test_leave_marks_have_no_reason_and_respect_departments(client, week):
    head = auth(client, "demo.housekeeping")
    d = (week + timedelta(days=5)).isoformat()
    r = client.post("/people/leave", json={"employee_id": EMP, "date": d, "kind": "leave"}, headers=head)
    assert r.status_code == 201, r.text
    assert client.post("/people/leave", json={"employee_id": EMP, "date": d, "reason": "fever"}, headers=head).status_code == 422
    assert client.post("/people/leave", json={"employee_id": "HS09", "date": d}, headers=head).status_code == 403
    marks = client.get(f"/people/leave?date_from={week}&date_to={d}", headers=head).json()
    assert marks == [{"employee_id": EMP, "date": d, "kind": "leave"}]
    feed = client.get("/people/signals?weeks=1", headers=head).json()
    assert feed["leave_marks_used"] and _rec(feed, EMP, week)["leave_days"] == [5]
    assert client.delete(f"/people/leave/{EMP}/{d}", headers=head).json()["removed"] is True


def test_weekly_answer_needs_consent_and_opting_out_deletes(client, owner, week):
    w = auth(client, EMP)
    st = client.get("/me/pulse", headers=w).json()
    assert st["consent"] is False and st["asked"] is False and st["options"] == ["good", "ok", "hard"]
    assert client.post("/me/pulse", json={"answer": "hard"}, headers=w).status_code == 422
    assert client.put("/me/pulse/consent", json={"consent": True}, headers=w).json()["consent"] is True
    assert client.post("/me/pulse", json={"answer": "meh"}, headers=w).status_code == 422
    assert client.post("/me/pulse", json={"answer": "hard"}, headers=w).json()["answer"] == "hard"
    feed = client.get("/people/signals?weeks=1&include_current=true", headers=owner).json()
    this_week = date.fromisoformat(feed["week_start"])
    assert _rec(feed, EMP, this_week)["pulse"] == "hard"
    head = client.get("/people/signals?weeks=1&include_current=true", headers=auth(client, "demo.housekeeping")).json()
    assert all(r["pulse"] is None for r in head["records"])  # department heads never see individual answers
    st = client.put("/me/pulse/consent", json={"consent": False}, headers=w).json()
    assert st["consent"] is False and st["answer"] is None
    assert mongo.col("pulse_answers").count_documents({"tenant_id": TID, "employee_id": EMP}) == 0


def test_feed_is_what_the_model_reads(client, owner, week):
    """Contract: the feed validates as ml.attrition.live_signals.LiveSignals (skipped where ml is not installed)."""
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    live = pytest.importorskip("ml.attrition.live_signals")
    feed = client.get("/people/signals?weeks=4", headers=owner).json()
    parsed = live.LiveSignals.model_validate(feed)
    assert any(r.employee_id == EMP and r.roster_published for r in parsed.records)


def test_short_rest_is_counted(week):
    ws = week
    rows = [
        {"employee_id": "HS04", "date": ws.isoformat(), "shift": "evening", "hours": 9},
        {"employee_id": "HS04", "date": (ws + timedelta(days=1)).isoformat(), "shift": "morning", "hours": 9},
    ]
    staff_signals.keep_roster_week(TID, ws.isoformat(), rows)  # evening ends 23:00, morning starts 06:00: 7 h rest
    feed = staff_signals.weekly_signals(TID, weeks=1)
    assert _rec(feed, "HS04", ws)["short_rest"] == 1
