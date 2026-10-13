"""Work log (GET /dispatch/worklog, GET /me/worklog): one day's jobs with minutes and photo ids. Offline, SYNTHETIC data.

Jobs go through the API (offer, accept, optional photos, start, done); their stamps are then moved to fixed times on a
fixed day so the minutes are exact.
"""

from datetime import datetime, timedelta

import pytest
from conftest import auth, jpeg

from hoi_platform import mongo, ratelimit
from hoi_platform.services import worklog

DAY = "2030-03-04"
URL = "/dispatch/worklog"


def _at(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(2030, 3, 4, h, m, tzinfo=worklog.local_tz())


@pytest.fixture(autouse=True)
def _fresh(client, owner):
    ratelimit.reset()
    client.post("/dispatch/reset", headers=owner)
    yield
    client.post("/dispatch/reset", headers=owner)


def _job(client, owner, emp, dept, title, photo=None, finish=True):
    client.put("/dispatch/context", json={"working": {emp: dept}, "bands": {}}, headers=owner)
    job = client.post("/dispatch/jobs", json={"title": title, "department": dept, "urgency": "medium"}, headers=owner).json()
    jid = job["id"]
    assert job["offer_to"] == emp, job
    assert client.post(f"/dispatch/jobs/{jid}/accept", json={"employee_id": emp}, headers=owner).status_code == 200
    assert client.post(f"/dispatch/jobs/{jid}/start", json={"employee_id": emp}, headers=owner).status_code == 200
    if photo:
        files = {"file": ("p.jpg", jpeg(), "image/jpeg")}
        r = client.post(f"/dispatch/jobs/{jid}/photos", data={"kind": photo, "employee_id": emp}, files=files, headers=owner)
        assert r.status_code == 201, r.text
    if finish:
        assert client.post(f"/dispatch/jobs/{jid}/complete", json={"employee_id": emp}, headers=owner).status_code == 200
    return jid


def _retime(jid, created, offered, accepted, started, done=None):
    doc = mongo.col("jobs").find_one({"id": jid})
    att = doc["attempts"]
    att[-1].update(offered_at=_at(offered), at=_at(accepted).isoformat())
    fields = {"created_at": _at(created), "accepted_at": _at(accepted), "started_at": _at(started), "attempts": att}
    fields["done_at"] = _at(done) if done else None
    mongo.col("jobs").update_one({"id": jid}, {"$set": fields})


def test_minutes_photos_and_people(client, owner):
    a = _job(client, owner, "HS05", "housekeeping", "Fresh towels")  # a job with no photo rule: an optional after photo
    _retime(a, "10:00", "10:01", "10:03", "10:12", "10:30")
    b = _job(client, owner, "HS05", "housekeeping", "Extra pillow", photo="after")
    _retime(b, "11:00", "11:00", "11:01", "11:05", "11:15")
    c = _job(client, owner, "HS18", "maintenance", "Fix the tap", finish=False)
    _retime(c, "12:00", "12:00", "12:10", "12:20")

    out = client.get(f"{URL}?date={DAY}", headers=owner).json()
    assert out["synthetic"] is True and out["date"] == DAY
    rows = {r["id"]: r for r in out["jobs"]}
    assert rows[a]["minutes"] == {"wait": 3.0, "response": 2.0, "work": 18.0, "total": 30.0}
    assert rows[b]["minutes"] == {"wait": 1.0, "response": 1.0, "work": 10.0, "total": 15.0}
    assert rows[c]["minutes"] == {"wait": 10.0, "response": 10.0, "work": None, "total": None}
    assert rows[a]["photos"] == {"before": None, "after": None}
    assert rows[b]["photos"]["after"] and rows[b]["photos"]["before"] is None
    assert rows[a]["started_at"].startswith(f"{DAY}T10:12") and rows[a]["started_at"].endswith("+05:30")
    assert set(rows[a]) >= {"title", "kind", "room", "department", "assigned_to", "status", "created_at", "accepted_at", "done_at"}

    s = out["summary"]
    assert (s["jobs"], s["jobs_done"], s["total_work_minutes"], s["avg_work_minutes"], s["jobs_with_photos"]) == (3, 2, 28.0, 14.0, 1)
    assert s["longest_wait_minutes"] == 10.0 and s["longest_wait_job"] == c
    people = {p["employee_id"]: p for p in out["people"]}
    assert people["HS05"] == {
        "employee_id": "HS05",
        "department": "housekeeping",
        "jobs": 2,
        "jobs_done": 2,
        "total_work_minutes": 28.0,
        "median_work_minutes": 14.0,
        "jobs_with_photos": 1,
    }
    assert people["HS18"]["jobs_done"] == 0 and people["HS18"]["median_work_minutes"] is None

    one = client.get(f"{URL}?date={DAY}&employee_id=HS18", headers=owner).json()
    assert [r["id"] for r in one["jobs"]] == [c]
    hk = client.get(f"{URL}?date={DAY}&department=housekeeping", headers=owner).json()
    assert {r["id"] for r in hk["jobs"]} == {a, b}


def test_day_boundary_is_hotel_local(client, owner):
    a = _job(client, owner, "HS05", "housekeeping", "Late towels")
    _retime(a, "10:00", "10:00", "10:01", "10:02", "10:05")
    nxt = (datetime.fromisoformat(DAY) + timedelta(days=1)).date().isoformat()
    assert client.get(f"{URL}?date={nxt}", headers=owner).json()["jobs"] == []


def test_empty_day(client, owner):
    out = client.get(f"{URL}?date=2031-01-01", headers=owner).json()
    assert out["jobs"] == [] and out["people"] == []
    assert out["summary"] == {
        "jobs": 0,
        "jobs_done": 0,
        "total_work_minutes": 0,
        "avg_work_minutes": None,
        "median_work_minutes": None,
        "jobs_with_photos": 0,
        "longest_wait_minutes": None,
        "longest_wait_job": None,
    }


def test_roles_and_dept_head_scope(client, owner, worker, hr):
    a = _job(client, owner, "HS05", "housekeeping", "Towels")
    _retime(a, "09:00", "09:00", "09:01", "09:02", "09:10")
    m = _job(client, owner, "HS18", "maintenance", "Fix the heater", photo="after")
    _retime(m, "09:00", "09:00", "09:01", "09:02", "09:20")

    assert client.get(f"{URL}?date={DAY}", headers=worker).status_code == 403
    assert client.get(f"{URL}?date={DAY}", headers=hr).status_code == 200
    head = auth(client, "demo.housekeeping")
    out = client.get(f"{URL}?date={DAY}", headers=head).json()
    assert out["department"] == "housekeeping" and [r["id"] for r in out["jobs"]] == [a]
    assert client.get(f"{URL}?date={DAY}&department=maintenance", headers=head).status_code == 403
    assert client.get(f"{URL}?date=2030-02-30", headers=owner).status_code == 422
    assert client.get(f"{URL}?date=yesterday", headers=owner).status_code == 422


def test_worker_sees_only_own_day(client, owner, worker):
    a = _job(client, owner, "HS05", "housekeeping", "Towels")
    _retime(a, "09:00", "09:00", "09:01", "09:02", "09:10")
    m = _job(client, owner, "HS18", "maintenance", "Fix the heater", photo="after")
    _retime(m, "09:00", "09:00", "09:01", "09:02", "09:20")
    out = client.get(f"/me/worklog?date={DAY}", headers=worker).json()
    assert [r["id"] for r in out["jobs"]] == [a] and [p["employee_id"] for p in out["people"]] == ["HS05"]
    assert client.get(f"/me/worklog?date={DAY}", headers=owner).status_code == 403


def test_optional_photo_on_job_without_photo_rule(client, owner, worker):
    """A towel run needs no photo, but staff may still add one (before when accepted, after while working)."""
    client.put("/dispatch/context", json={"working": {"HS05": "housekeeping"}, "bands": {}}, headers=owner)
    job = client.post("/dispatch/jobs", json={"title": "Towels", "department": "housekeeping", "urgency": "low"}, headers=owner).json()
    assert job["photos_required"]["before"] is False and job["photos_required"]["after"] is False
    jid = job["id"]
    files = {"file": ("p.jpg", jpeg(), "image/jpeg")}
    assert client.post(f"/dispatch/jobs/{jid}/accept", json={}, headers=worker).status_code == 200
    assert client.post(f"/dispatch/jobs/{jid}/photos", data={"kind": "before"}, files=files, headers=worker).status_code == 201
    assert client.post(f"/dispatch/jobs/{jid}/start", json={}, headers=worker).status_code == 200
    assert client.post(f"/dispatch/jobs/{jid}/photos", data={"kind": "after"}, files=files, headers=worker).status_code == 201
    assert client.post(f"/dispatch/jobs/{jid}/complete", json={}, headers=worker).status_code == 200
    got = client.get(f"/dispatch/jobs/{jid}/photos", headers=owner).json()
    assert set(got) == {"before", "after"}
    r = client.get(f"/dispatch/photos/{got['after']['id']}", headers=owner)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
