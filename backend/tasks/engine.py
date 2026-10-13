"""Task engine (B3): create / ack / done with idempotency keys, reminders and escalation.

Time comes from a VirtualClock so a demo can run faster than real time (POST /demo/clock):
virtual now = anchor + real elapsed x multiplier. Task times (created_at, deadline, events) are
virtual. tick(now) is pure bookkeeping, driven every tick_seconds by APScheduler in the app and
by a fake clock in tests:
  - at each reminder fraction (0.5, 0.9) of the time between creation and deadline: a reminder
    to the assignee (task_event reminder_50 / reminder_90)
  - at escalate_at_fraction (0.9): an escalation to the supervisor (task_event escalation)
Every event kind fires at most once per task (a unique index on task_event (task_id, kind)), so
ticks, retries, restarts and concurrent workers never duplicate a message. Tasks are plain dicts
(the `task` documents without _id). Acked tasks still get reminders until done; done tasks get
none. All data is SYNTHETIC.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from backend.config import TaskConfig
from backend.db import EVENTS, NO_ID, TASKS, audit, ms, stamped

OPEN, ACKED, DONE = "open", "acked", "done"
ESCALATION = "escalation"


class VirtualClock:
    """Thread-safe clock whose speed can change without jumping back in time."""

    def __init__(self, multiplier: float = 1.0) -> None:
        self._lock = threading.Lock()
        self._real0 = datetime.now(UTC)
        self._virtual0 = self._real0
        self.multiplier = multiplier

    def now(self) -> datetime:
        with self._lock:
            elapsed = datetime.now(UTC) - self._real0
            return self._virtual0 + elapsed * self.multiplier

    def set_multiplier(self, multiplier: float) -> datetime:
        if multiplier <= 0:
            raise ValueError("multiplier must be positive")
        current = self.now()
        with self._lock:
            self._real0, self._virtual0 = datetime.now(UTC), current
            self.multiplier = multiplier
        return current


@dataclass(frozen=True)
class NewTask:
    idempotency_key: str
    title: str
    assignee: str
    supervisor: str = ""
    description: str = ""
    employee_id: str = ""
    due_in_minutes: int | None = None


class IdempotencyConflict(ValueError):
    """The key was used before for a DIFFERENT task."""


def _event(db: Database, task: dict, kind: str, message: str, now: datetime,
           source: str) -> bool:
    """Insert a task_event once per (task, kind); returns False if it already existed."""
    if db[EVENTS].find_one({"task_id": task["id"], "kind": kind}, {"_id": 1}) is not None:
        return False
    try:
        db[EVENTS].insert_one(stamped(db, EVENTS, {"task_id": task["id"], "kind": kind,
                                                   "message": message}, source, now))
    except DuplicateKeyError:  # another worker fired it first
        return False
    return True


def _same(existing: dict, new: NewTask) -> tuple[dict, bool]:
    same = (existing["title"], existing["assignee"], existing["supervisor"]) == (
        new.title, new.assignee, new.supervisor)
    if not same:
        raise IdempotencyConflict(f"idempotency_key {new.idempotency_key!r} was used for a "
                                  "different task")
    return existing, False


def create(db: Database, new: NewTask, cfg: TaskConfig, now: datetime,
           source: str) -> tuple[dict, bool]:
    """(task, created). A retry with the same key and the same content returns the same task."""
    existing = db[TASKS].find_one({"idempotency_key": new.idempotency_key}, NO_ID)
    if existing is not None:
        return _same(existing, new)
    minutes = new.due_in_minutes or cfg.default_due_minutes
    task = stamped(db, TASKS, {
        "idempotency_key": new.idempotency_key, "title": new.title,
        "description": new.description, "assignee": new.assignee, "supervisor": new.supervisor,
        "employee_id": new.employee_id, "status": OPEN,
        "deadline": ms(now + timedelta(minutes=minutes)), "acked_at": None, "done_at": None},
        source, now)
    try:
        db[TASKS].insert_one(dict(task))
    except DuplicateKeyError:  # a concurrent create with the same key won the unique index
        return _same(db[TASKS].find_one({"idempotency_key": new.idempotency_key}, NO_ID), new)
    _event(db, task, "created", f"Task '{task['title']}' assigned to {task['assignee']}", now,
           source)
    audit(db, "task.create", {"task_id": task["id"], "key": task["idempotency_key"]}, source)
    return task, True


def _transition(db: Database, task_id: int, status: str, now: datetime, source: str) -> dict:
    task = db[TASKS].find_one({"id": task_id}, NO_ID)
    if task is None:
        raise LookupError(f"task {task_id} not found")
    if task["status"] == DONE and status == ACKED:
        return task  # acking a finished task changes nothing
    if task["status"] != status:
        changes: dict = {"status": status}
        if status == ACKED:
            changes["acked_at"] = ms(now)
        if status == DONE:
            changes["done_at"] = ms(now)
            changes["acked_at"] = task["acked_at"] or ms(now)
        # conditional on the status read above: a concurrent identical call changes nothing
        moved = db[TASKS].find_one_and_update({"id": task_id, "status": task["status"]},
                                              {"$set": changes},
                                              return_document=ReturnDocument.AFTER)
        if moved is None:
            return db[TASKS].find_one({"id": task_id}, NO_ID)
        moved.pop("_id")  # (no projection: mongomock returns None with {"_id": 0} here)
        task = moved
        _event(db, task, status, f"Task '{task['title']}' {status} by {task['assignee']}", now,
               source)
        audit(db, f"task.{status}", {"task_id": task["id"]}, source)
    return task


def ack(db: Database, task_id: int, now: datetime, source: str) -> dict:
    return _transition(db, task_id, ACKED, now, source)


def done(db: Database, task_id: int, now: datetime, source: str) -> dict:
    return _transition(db, task_id, DONE, now, source)


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)  # a client without tz_aware gives naive


def fraction_elapsed(task: dict, now: datetime) -> float:
    start, end = _aware(task["created_at"]), _aware(task["deadline"])
    return (now - start) / (end - start)


def tick(db: Database, cfg: TaskConfig, now: datetime, source: str = "scheduler") -> int:
    """Fire every due reminder / escalation exactly once; returns the number of new events."""
    fired = 0
    for task in db[TASKS].find({"status": {"$ne": DONE}}, NO_ID).sort("id", 1):
        f = fraction_elapsed(task, now)
        due = _aware(task["deadline"]).strftime("%Y-%m-%d %H:%M")
        for frac in cfg.reminder_fractions:
            if f >= frac:
                pct = round(frac * 100)
                fired += _event(db, task, f"reminder_{pct}",
                                f"Reminder to {task['assignee']}: '{task['title']}' is {pct}% of "
                                f"the way to its deadline ({due} UTC)", now, source)
        if f >= cfg.escalate_at_fraction and task["supervisor"]:
            fired += _event(db, task, ESCALATION,
                            f"Escalation to {task['supervisor']}: '{task['title']}' (assigned to "
                            f"{task['assignee']}) is not done and is "
                            f"{round(cfg.escalate_at_fraction * 100)}% of the way to its "
                            f"deadline ({due} UTC)", now, source)
    return fired
