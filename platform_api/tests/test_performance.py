"""Performance score (plan 4.1): components from dispatch jobs, own-baseline delta, minimum job count, role scoping.

Jobs are seeded through the API (offer, accept, photos, start, complete, room inspection); only their timestamps are then
moved into the scoring periods, as the dispatch tests do for offer expiry. All data is SYNTHETIC.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import auth, jpeg

from hoi_platform import mongo
from hoi_platform.services import performance

NOW = datetime.now(UTC).replace(microsecond=0)
A, B, M = "HS05", "HB1", "MX1"  # A is the demo worker account; B too few jobs; M another department


def _ctx(client, owner, working):
    r = client.put("/dispatch/context", json={"day": "2029-12-24", "shift": "morning", "working": working, "bands": {}}, headers=owner)
    assert r.status_code == 200


def _work(client, owner, job, emp):
    jid = job["id"]
    assert job["offer_to"] == emp, job
    assert client.post(f"/dispatch/jobs/{jid}/accept", json={"employee_id": emp}, headers=owner).status_code == 200
    files = {"file": ("p.jpg", jpeg(), "image/jpeg")}
    assert (
        client.post(f"/dispatch/jobs/{jid}/photos", data={"kind": "before", "employee_id": emp}, files=files, headers=owner).status_code
        == 201
    )
    assert client.post(f"/dispatch/jobs/{jid}/start", json={"employee_id": emp}, headers=owner).status_code == 200
    assert (
        client.post(f"/dispatch/jobs/{jid}/photos", data={"kind": "after", "employee_id": emp}, files=files, headers=owner).status_code
        == 201
    )
    assert client.post(f"/dispatch/jobs/{jid}/complete", json={"employee_id": emp}, headers=owner).json()["status"] == "done"
    return jid


def _retime(jid, done_ago_days, work_min, accept_s=5):
    """Move a finished job into a period: offered -> accepted (accept_s later) -> started 1 min later -> done after work_min."""
    done = NOW - timedelta(days=done_ago_days)
    started = done - timedelta(minutes=work_min)
    accepted = started - timedelta(minutes=1)
    offered = accepted - timedelta(seconds=accept_s)
    doc = mongo.col("jobs").find_one({"id": jid})
    att = doc["attempts"]
    att[-1].update(offered_at=offered, at=accepted)
    mongo.col("jobs").update_one(
        {"id": jid},
        {"$set": {"created_at": offered, "accepted_at": accepted, "started_at": started, "done_at": done, "attempts": att}},
    )


def _job(client, owner, emp, dept, done_ago, work_min, title="Fix it"):
    _ctx(client, owner, {emp: dept})
    job = client.post("/dispatch/jobs", json={"title": title, "department": dept, "urgency": "medium"}, headers=owner).json()
    _retime(_work(client, owner, job, emp), done_ago, work_min)


def _cleaning(client, owner, emp, passed, done_ago, work_min=20):
    _ctx(client, owner, {emp: "housekeeping"})
    room = mongo.col("rooms").find_one({"tenant_id": auth_tid(client, owner), "status": {"$in": ["ready", "occupied"]}})
    mongo.col("rooms").update_one({"id": room["id"]}, {"$set": {"status": "occupied"}})
    r = client.post(f"/rooms/{room['id']}/checkout", headers=owner).json()
    job = client.get(f"/dispatch/jobs?status=offered&worker={emp}", headers=owner).json()
    job = next(j for j in job if j["id"] == r["current_job_id"])
    jid = _work(client, owner, job, emp)
    assert (
        client.post(
            f"/rooms/{room['id']}/inspect", json={"passed": passed, "note": "" if passed else "bathroom"}, headers=owner
        ).status_code
        == 200
    )
    _retime(jid, done_ago, work_min)
    mongo.col("jobs").delete_many(
        {"room_id": room["id"], "status": {"$ne": "done"}}
    )  # the re-clean job after a fail is not part of this test


def auth_tid(client, owner):
    return client.get("/auth/me", headers=owner).json()["user"]["tenant_id"]


@pytest.fixture(scope="module")
def seeded(client):
    owner = auth(client, "demo.owner")
    client.post("/dispatch/reset", headers=owner)
    # A, current period: 4 inspected cleanings (3 pass, 1 re-clean) + 2 other jobs, one of them late (71 min > 60 target)
    for passed in (True, True, True, False):
        _cleaning(client, owner, A, passed, done_ago=2)
    _job(client, owner, A, "housekeeping", 3, 20, "Extra towels")
    _job(client, owner, A, "housekeeping", 4, 70, "Deep clean the lobby")
    # one decline in the current period (A is the only candidate, so the job becomes unassigned)
    _ctx(client, owner, {A: "housekeeping"})
    j = client.post("/dispatch/jobs", json={"title": "Turndown", "department": "housekeeping"}, headers=owner).json()
    assert client.post(f"/dispatch/jobs/{j['id']}/decline", json={"employee_id": A}, headers=owner).json()["status"] == "unassigned"
    # A, previous period (days 15-28): 5 on-time jobs, no inspections -> baseline exists
    for d in (16, 18, 20, 22, 24):
        _job(client, owner, A, "housekeeping", d, 20, "Fresh linen")
    # B: only 3 jobs -> insufficient data; M: maintenance (outside the housekeeping head's department)
    for d in (1, 2, 3):
        _job(client, owner, B, "housekeeping", d, 40, "Fresh towels")
    _job(client, owner, M, "maintenance", 2, 30, "AC repair")
    yield owner
    client.post("/dispatch/reset", headers=owner)


def test_components_score_and_baseline(client, seeded):
    out = client.get("/dispatch/performance?days=14", headers=seeded).json()
    assert out["weights"] == performance.WEIGHTS and out["min_jobs"] == 5 and "not for disciplinary use" in out["note"]
    rows = {w["employee_id"]: w for w in out["workers"]}
    a = rows[A]
    c = a["components"]
    assert a["status"] == "ok" and a["completed_jobs"] == 6 and a["department"] == "housekeeping"
    assert (c["on_time"]["on_time"], c["on_time"]["jobs"]) == (5, 6)
    assert (c["quality"]["passed"], c["quality"]["inspected"]) == (3, 4) and c["quality"]["value"] == 0.75
    # department median work time over A [20 x5, 70] and B [40 x3] = 20 min; A's median is 20 -> full speed marks
    assert c["speed"]["median_minutes"] == 20 and c["speed"]["department_median_minutes"] == 20 and c["speed"]["value"] == 1
    assert c["responsiveness"]["median_seconds_to_accept"] == 5 and c["responsiveness"]["value"] == 1
    assert (c["reliability"]["offers"], c["reliability"]["declined"], c["reliability"]["timed_out"]) == (7, 1, 0)
    expected = 100 * (0.35 * 5 / 6 + 0.20 * 1 + 0.25 * 0.75 + 0.10 * 1 + 0.10 * 6 / 7)
    assert a["score"] == pytest.approx(expected, abs=0.1)
    # baseline: 5 on-time jobs, no inspection (quality excluded, weights re-normalised), all accepted fast -> 100
    assert a["baseline_score"] == 100 and a["delta"] == pytest.approx(a["score"] - 100, abs=0.1)
    assert 1 <= len(a["reasons"]) <= 3 and all(isinstance(r, str) and r.endswith(".") for r in a["reasons"])
    assert a["reasons"][0].startswith("On time") and any("re-clean" in r for r in a["reasons"])  # largest change first


def test_minimum_jobs_and_quality_renormalised(client, seeded):
    rows = {w["employee_id"]: w for w in client.get("/dispatch/performance", headers=seeded).json()["workers"]}
    b = rows[B]
    assert b["status"] == "insufficient_data" and b["score"] is None and b["completed_jobs"] == 3
    assert "at least 5" in b["reasons"][0]
    # the score function itself: no inspected job -> quality left out and the rest re-normalised to sum 1
    comp = {k: {"value": 1.0} for k in performance.WEIGHTS} | {"quality": {"value": None}}
    score, used = performance._score(comp)
    assert score == 100 and "quality" not in used and sum(used.values()) == pytest.approx(1)


def test_roles_and_scoping(client, seeded):
    head, hr, worker = auth(client, "demo.housekeeping"), auth(client, "demo.hr"), auth(client, "HS05")
    owner_ids = {w["employee_id"] for w in client.get("/dispatch/performance", headers=seeded).json()["workers"]}
    assert {A, B, M} <= owner_ids
    h = client.get("/dispatch/performance", headers=head).json()
    assert (
        h["department"] == "housekeeping"
        and M not in {w["employee_id"] for w in h["workers"]}
        and A in {w["employee_id"] for w in h["workers"]}
    )
    assert client.get("/dispatch/performance", headers=hr).status_code == 200
    assert client.get("/dispatch/performance", headers=worker).status_code == 403
    assert client.get("/dispatch/performance?days=0", headers=seeded).status_code == 422
    # a worker sees only their own score and reasons: no colleagues, no risk bands
    me = client.get("/me/performance", headers=worker)
    assert me.status_code == 200
    body = me.json()
    assert body["employee_id"] == A and "workers" not in body and body["status"] == "ok"
    text = json.dumps(body).lower()
    assert B.lower() not in text and M.lower() not in text and "band" not in text
    assert client.get("/me/performance", headers=seeded).status_code == 403  # owners use /dispatch/performance
