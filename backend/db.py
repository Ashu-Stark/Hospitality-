"""MongoDB collections and the seed step from the SYNTHETIC ml data files (docs/MONGODB.md).

Every document has created_at and source (where it came from: the ml data seed, an API call,
the roster solver, the loop, ...) and an integer `id` from the `counters` collection (the API
exposes integer ids; `_id` never leaves this layer). The seed reads only ml/data output tables
and ml/data/demo (never ml/data/internal/). No multi-document transactions: single-document
writes plus unique indexes (task.idempotency_key, one task_event per task and kind).

Collections (dates as ISO "YYYY-MM-DD" strings, times as timezone-aware UTC datetimes):
  employee_snapshot  one per employee active in the snapshot week (staff and demo heroes)
  roster             a roster with its assignments embedded (employee_id, day, shift, hours)
  task, task_event   the task engine (B3)
  intervention       closed-loop actions (B4)
  audit_log          every state change (detail is a JSON-safe dict)
  counters           {_id: collection name, seq: last id}
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.database import Database

from backend.config import ML_DATA

EMPLOYEES, ROSTERS, TASKS, EVENTS = "employee_snapshot", "roster", "task", "task_event"
INTERVENTIONS, AUDIT, COUNTERS = "intervention", "audit_log", "counters"
COLLECTIONS = (EMPLOYEES, ROSTERS, TASKS, EVENTS, INTERVENTIONS, AUDIT)
NO_ID = {"_id": 0}  # projection: never return Mongo's ObjectId


def utcnow() -> datetime:
    return ms(datetime.now(UTC))


def ms(t: datetime) -> datetime:
    """MongoDB keeps milliseconds: round down at write time so reads match what was returned."""
    return t.replace(microsecond=t.microsecond // 1000 * 1000)


def next_ids(db: Database, name: str, n: int = 1) -> list[int]:
    """n new integer ids for collection `name` (one atomic $inc on counters)."""
    doc = db[COUNTERS].find_one_and_update({"_id": name}, {"$inc": {"seq": n}}, upsert=True,
                                           return_document=ReturnDocument.AFTER)
    return list(range(doc["seq"] - n + 1, doc["seq"] + 1))


def stamped(db: Database, name: str, doc: dict, source: str,
            created_at: datetime | None = None) -> dict:
    """doc + a new id, created_at and source (ready to insert)."""
    return {"id": next_ids(db, name)[0], **doc, "created_at": ms(created_at or utcnow()),
            "source": source}


def insert(db: Database, name: str, doc: dict, source: str,
           created_at: datetime | None = None) -> dict:
    """Insert one stamped document; returns it without _id."""
    row = stamped(db, name, doc, source, created_at)
    db[name].insert_one(dict(row))  # a copy: insert_one adds _id to the dict it gets
    return row


def json_safe(value: object) -> object:
    """Dates, numpy numbers etc. as JSON values, so any detail dict is a valid document."""
    return json.loads(json.dumps(value, default=str))


def audit(db: Database, action: str, detail: dict, source: str) -> None:
    insert(db, AUDIT, {"action": action, "detail": json_safe(detail)}, source)


def ensure_indexes(db: Database) -> None:
    """Idempotent; run at startup. Unique indexes enforce the business rules."""
    for name in COLLECTIONS:
        db[name].create_index("id", unique=True)
    db[TASKS].create_index("idempotency_key", unique=True)
    db[TASKS].create_index([("status", ASCENDING), ("id", ASCENDING)])
    db[TASKS].create_index([("employee_id", ASCENDING), ("id", ASCENDING)])
    db[EVENTS].create_index([("task_id", ASCENDING), ("kind", ASCENDING)], unique=True)
    db[EMPLOYEES].create_index("employee_id")
    db[ROSTERS].create_index("week_start")
    db[INTERVENTIONS].create_index("employee_id")
    db[AUDIT].create_index([("action", ASCENDING), ("id", DESCENDING)])


def drop_all(db: Database) -> None:
    """Drop every hoi_ops collection (counters too, so ids restart at 1)."""
    for name in (*COLLECTIONS, COUNTERS):
        db.drop_collection(name)


# --- seed ----------------------------------------------------------------------------------


def pay_in_force(employees: pd.DataFrame, pay_changes: pd.DataFrame, week: str) -> pd.Series:
    """Monthly pay per employee_id on `week`: hire pay, replaced by the latest earlier raise."""
    pay = employees.set_index("employee_id")["monthly_pay"].astype(float)
    done = pay_changes[pay_changes["effective_date"] <= week].sort_values("effective_date")
    pay.update(done.groupby("employee_id")["monthly_pay"].last().astype(float))
    return pay


def snapshot_frame(data_dir: Path = ML_DATA) -> pd.DataFrame:
    """Active employees (staff + demo heroes) in the latest week, with skills and leave."""
    behaviour = pd.concat([pd.read_csv(data_dir / "weekly_behaviour.csv"),
                           pd.read_csv(data_dir / "demo" / "hero_weekly.csv")])
    week = behaviour["week_start"].max()
    active = behaviour[(behaviour["week_start"] == week) & behaviour["is_active"].astype(bool)]
    emp = pd.concat([pd.read_csv(data_dir / "employee_v2.csv", keep_default_na=False),
                     pd.read_csv(data_dir / "demo" / "hero_employees.csv", keep_default_na=False)])
    heroes = set(pd.read_csv(data_dir / "demo" / "hero_employees.csv")["employee_id"])
    skills = pd.read_csv(data_dir / "employee_skill.csv").groupby("employee_id")["skill"].agg(
        lambda s: json.dumps(sorted(s)))
    df = active[["employee_id", "week_start", "leave_days"]].merge(
        emp[["employee_id", "department", "role", "contract_type", "is_department_head",
             "manager_id"]], on="employee_id", how="left")
    df = df.reset_index(drop=True)
    df["skills"] = df["employee_id"].map(skills).fillna("[]")
    df["monthly_pay"] = df["employee_id"].map(
        pay_in_force(emp, pd.read_csv(data_dir / "pay_changes.csv"), week))
    df["is_demo_hero"] = df["employee_id"].isin(heroes)
    df["is_department_head"] = df["is_department_head"].astype(str).str.lower() == "true"
    return df.sort_values("employee_id").reset_index(drop=True)


def seed(db: Database, source: str, data_dir: Path = ML_DATA) -> int:
    """(Re)load the employee snapshot from the ml data; returns documents written."""
    db[EMPLOYEES].delete_many({})
    df = snapshot_frame(data_dir)
    now = utcnow()
    docs = [{"id": i, "employee_id": r.employee_id, "week_start": r.week_start,
             "department": r.department, "role": r.role, "contract_type": r.contract_type,
             "is_department_head": bool(r.is_department_head),
             "is_demo_hero": bool(r.is_demo_hero), "manager_id": str(r.manager_id),
             "skills": json.loads(r.skills), "leave_days": int(r.leave_days),
             "monthly_pay": float(r.monthly_pay), "created_at": now, "source": source}
            for i, r in zip(next_ids(db, EMPLOYEES, len(df)), df.itertuples(index=False),
                            strict=True)]
    if docs:
        db[EMPLOYEES].insert_many(docs)
    audit(db, "seed", {"rows": len(df), "week_start": df["week_start"].iloc[0]}, source)
    return len(df)


def ensure_seeded(db: Database, source: str) -> None:
    ensure_indexes(db)
    if db[EMPLOYEES].find_one({}, {"_id": 1}) is None:
        seed(db, source)
