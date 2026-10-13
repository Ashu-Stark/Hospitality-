"""B5: metrics overview (ROI labelled as an assumption), demo reset and voice ingest."""

from backend.db import EMPLOYEES, TASKS


def test_metrics_overview_and_roi_override(client) -> None:
    empty = client.get("/metrics/overview").json()
    assert empty["roster_id"] is None and empty["flagged_count"] == 0
    assert "ASSUMPTION" in empty["roi_note"] and empty["synthetic"]
    client.post("/roster/generate", json={"use_cache": True})
    body = {"idempotency_key": "m1", "title": "t", "assignee": "a", "due_in_minutes": 60}
    tid = client.post("/tasks", json=body).json()["id"]
    client.post(f"/tasks/{tid}/done")
    m = client.get("/metrics/overview", params={"replacement_cost_inr": 1000}).json()
    assert m["roster_id"] is not None and m["overtime_hours"] >= 0
    assert m["tasks_total"] == 1 and m["tasks_on_time_rate"] == 1.0
    assert m["replacement_cost_inr"] == 1000
    assert m["roi_inr"] == m["flagged_still_employed"] * 1000


def test_demo_reset_rebuilds(client) -> None:
    client.post("/tasks", json={"idempotency_key": "r1", "title": "t", "assignee": "a"})
    client.post("/demo/clock", json={"multiplier": 50})
    r = client.post("/demo/reset").json()
    assert r["status"] == "reset" and r["employee_snapshot_rows"] == 60
    db = client.app.state.db
    assert db[TASKS].count_documents({}) == 0
    assert db[EMPLOYEES].count_documents({}) == 60
    assert db["counters"].find_one({"_id": TASKS}) is None  # ids restart at 1
    tid = client.post("/tasks", json={"idempotency_key": "r1", "title": "t", "assignee": "a"})
    assert tid.status_code == 201 and tid.json()["id"] == 1
    assert client.get("/demo/clock").json()["multiplier"] == 1.0


def test_voice_ingest_demo_clip_creates_a_task(client) -> None:
    r = client.post("/voice/ingest", json={"file": "clip_01.wav"})
    assert r.status_code == 200, r.text
    b = r.json()
    x = b["voice"]["extraction"]
    assert (x["room"], x["issue"], x["urgency"]) == ("204", "ac_not_working", "high")
    assert b["voice"]["fallback_used"]  # no audio / API keys yet: cached demo result
    assert b["task"]["assignee"] == "maintenance head"
    assert b["task"]["title"] == "ac not working in room 204"
    again = client.post("/voice/ingest", json={"file": "clip_01.wav"}).json()
    assert again["task"]["id"] == b["task"]["id"]  # idempotent


def test_voice_ingest_clear_errors(client) -> None:
    missing = client.post("/voice/ingest", json={"file": "clip_02.wav"})
    assert missing.status_code == 503 and "not found" in missing.json()["detail"]
    escape = client.post("/voice/ingest", json={"file": "../../data/exits.csv"})
    assert escape.status_code == 422
