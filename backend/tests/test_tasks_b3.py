"""B3: task engine. A simulated clock proves the right message at 50% and 90%, escalation to the
supervisor, and no duplicates on retries or repeated ticks."""

import time
from datetime import UTC, datetime, timedelta

import pytest

from backend.config import load_backend_config
from backend.db import EVENTS, TASKS, ensure_indexes
from backend.mongo import get_database
from backend.tasks import engine
from backend.tests.conftest import fresh_settings

T0 = datetime(2029, 12, 24, 9, 0, tzinfo=UTC)


@pytest.fixture()
def db():
    settings = fresh_settings()
    database = get_database(settings)
    ensure_indexes(database)
    yield database
    database.client.drop_database(settings.database_name)


@pytest.fixture()
def cfg():
    return load_backend_config().tasks


def kinds(db, task_id: int) -> list[str]:
    return [e["kind"] for e in db[EVENTS].find({"task_id": task_id}).sort("id", 1)]


def test_reminders_fire_at_50_and_90_percent_once(db, cfg) -> None:
    new = engine.NewTask("k1", "Fix AC in 204", "tech_1", supervisor="head_maint",
                         due_in_minutes=100)
    task, created = engine.create(db, new, cfg, T0, "test")
    assert created
    at = lambda m: T0 + timedelta(minutes=m)  # noqa: E731
    assert engine.tick(db, cfg, at(40)) == 0
    assert engine.tick(db, cfg, at(55)) == 1
    assert kinds(db, task["id"]) == ["created", "reminder_50"]
    assert engine.tick(db, cfg, at(60)) == 0  # no duplicate
    assert engine.tick(db, cfg, at(91)) == 2  # reminder_90 + escalation
    assert engine.tick(db, cfg, at(95)) == 0
    msg = {e["kind"]: e["message"] for e in db[EVENTS].find({"task_id": task["id"]})}
    assert msg["reminder_50"].startswith("Reminder to tech_1") and "50%" in msg["reminder_50"]
    assert "90%" in msg["reminder_90"]
    assert msg["escalation"].startswith("Escalation to head_maint")


def test_done_tasks_get_no_reminders(db, cfg) -> None:
    task, _ = engine.create(db, engine.NewTask("k2", "Towels 112", "hk_1", "hk_head",
                                               due_in_minutes=10), cfg, T0, "test")
    engine.done(db, task["id"], T0 + timedelta(minutes=2), "test")
    assert engine.tick(db, cfg, T0 + timedelta(minutes=9.5)) == 0
    assert kinds(db, task["id"]) == ["created", "done"]


def test_retries_never_duplicate(db, cfg) -> None:
    new = engine.NewTask("k3", "Heater 108", "tech_2", "head_maint", due_in_minutes=30)
    a, c1 = engine.create(db, new, cfg, T0, "test")
    b, c2 = engine.create(db, new, cfg, T0 + timedelta(seconds=5), "test")
    assert (a["id"], c1, c2) == (b["id"], True, False)
    for _ in range(3):
        engine.ack(db, a["id"], T0 + timedelta(minutes=1), "test")
    assert kinds(db, a["id"]) == ["created", "acked"]
    with pytest.raises(engine.IdempotencyConflict):
        engine.create(db, engine.NewTask("k3", "Something else", "x"), cfg, T0, "test")
    assert db[TASKS].count_documents({"idempotency_key": "k3"}) == 1


def test_unique_index_backs_idempotency_under_a_race(db, cfg, monkeypatch) -> None:
    """Two creates that both miss the lookup: the unique index lets only one insert win."""
    new = engine.NewTask("k4", "Lamp 301", "tech_3", "head_maint", due_in_minutes=30)
    first, _ = engine.create(db, new, cfg, T0, "test")
    tasks = db[TASKS]
    original = type(tasks).find_one
    missed = []

    def find_one(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if self.name == TASKS and not missed:
            missed.append(True)
            return None  # the first lookup "misses", as if another worker had not inserted yet
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(tasks), "find_one", find_one)
    again, created = engine.create(db, new, cfg, T0, "test")
    assert (again["id"], created) == (first["id"], False)
    assert tasks.count_documents({"idempotency_key": "k4"}) == 1


def test_task_endpoints_idempotent(client) -> None:
    body = {"idempotency_key": "api-1", "title": "Linen change 210", "assignee": "hk_2",
            "supervisor": "hk_head", "due_in_minutes": 60}
    r1, r2 = client.post("/tasks", json=body), client.post("/tasks", json=body)
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r1.json()["id"] == r2.json()["id"]
    tid = r1.json()["id"]
    assert client.post(f"/tasks/{tid}/ack").json()["status"] == "acked"
    assert client.post(f"/tasks/{tid}/ack").json()["status"] == "acked"
    assert client.post(f"/tasks/{tid}/done").json()["status"] == "done"
    listed = client.get("/tasks", params={"status": "done"}).json()
    assert [t["id"] for t in listed] == [tid]
    assert [e["kind"] for e in listed[0]["events"]] == ["created", "acked", "done"]
    assert client.post("/tasks", json={**body, "title": "other"}).status_code == 409
    assert client.post("/tasks/999/ack").status_code == 404


def test_live_scheduler_with_demo_clock(client) -> None:
    assert client.post("/demo/clock", json={"multiplier": 600}).status_code == 200
    body = {"idempotency_key": "live-1", "title": "AC 204", "assignee": "tech_1",
            "supervisor": "head_maint", "due_in_minutes": 1}  # 60 virtual s = 0.1 real s
    tid = client.post("/tasks", json=body).json()["id"]
    deadline = time.time() + 6
    while time.time() < deadline:
        ev = [e["kind"] for e in client.get("/tasks").json()[0]["events"]]
        if "escalation" in ev:
            break
        time.sleep(0.2)
    assert ev.count("reminder_50") == 1 and ev.count("reminder_90") == 1
    assert ev.count("escalation") == 1
    assert client.get("/tasks").json()[0]["id"] == tid
