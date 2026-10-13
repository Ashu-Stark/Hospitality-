"""MongoDB persistence: one cached client, the `hoi_platform` database, indexes, integer counters, small helpers.

Conventions (docs/MONGODB.md):
- `MONGODB_URI` unset or `mongomock://` -> in-memory mongomock (development/tests only, one warning).
- Timestamps are stored as timezone-aware UTC datetimes; the API renders them as before (local ISO strings).
- Every business document carries `tenant_id`; public ids are the `id` field (unique index), `_id` never leaves this layer.
- Fields starting with "_" are internal (e.g. `_username_lc`) and are stripped by clean().
- No multi-document transactions: services use conditional single-document updates, unique indexes and compensating writes.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.database import Database

from . import config

log = logging.getLogger("hoi.platform.mongo")
_LOCK = threading.Lock()
_CLIENTS: dict[str, Any] = {}
_READY: set[tuple[str, str]] = set()
_WARNED = False


def is_mock(uri: str | None) -> bool:
    return not uri or uri.strip().startswith("mongomock://")


def backend() -> str:
    """'mongodb' or 'mongomock' (never the URI)."""
    return "mongomock" if config.settings.uses_mongomock else "mongodb"


def client():
    global _WARNED
    uri = (config.settings.mongodb_uri or "").strip()
    key = "mongomock://" if is_mock(uri) else uri
    with _LOCK:
        if key not in _CLIENTS:
            if is_mock(uri):
                import mongomock

                if not _WARNED:
                    log.warning("MONGODB_URI not set (or mongomock://): using in-memory mongomock; data is lost on restart.")
                    _WARNED = True
                _CLIENTS[key] = mongomock.MongoClient(tz_aware=True, tzinfo=UTC)
            else:
                from pymongo import MongoClient

                _CLIENTS[key] = MongoClient(uri, tz_aware=True, tzinfo=UTC, serverSelectionTimeoutMS=8000, appname="hoi-platform")
        return _CLIENTS[key]


def db() -> Database:
    s = config.settings
    d = client()[s.db_name]
    key = ("mongomock" if is_mock(s.mongodb_uri) else s.mongodb_uri or "", s.db_name)
    if key not in _READY:
        with _LOCK:
            if key not in _READY:
                ensure_indexes(d)
                _READY.add(key)
    return d


def col(name: str):
    return db()[name]


def ping() -> bool:
    db().command("ping")
    return True


# ------------------------------------------------------------------ indexes
def _ix(*fields: str) -> list[tuple[str, int]]:
    return [(f[1:], DESCENDING) if f.startswith("-") else (f, ASCENDING) for f in fields]


INDEXES: dict[str, list[tuple[list, dict]]] = {
    "tenants": [(_ix("id"), {"unique": True})],
    "properties": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "created_at"), {})],
    "staff": [(_ix("tenant_id", "employee_id"), {"unique": True})],
    "invites": [(_ix("code"), {"unique": True}), (_ix("tenant_id", "-created_at"), {})],
    "users": [
        (_ix("id"), {"unique": True}),
        (_ix("_username_lc"), {"unique": True}),
        (_ix("tenant_id", "role", "username"), {}),
    ],
    "audit_log": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "-id"), {})],
    "dispatch_context": [(_ix("tenant_id"), {"unique": True})],
    "jobs": [
        (_ix("id"), {"unique": True}),
        (_ix("tenant_id", "status"), {}),
        (_ix("tenant_id", "-created_at"), {}),
        (_ix("tenant_id", "room_id", "kind", "created_at"), {}),
    ],
    "photos": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "job_id", "kind"), {})],
    "photo_blobs": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "id"), {})],
    "inv_suppliers": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "name"), {})],
    "inv_locations": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "name"), {})],
    "inv_items": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "_sku_lc"), {"unique": True})],
    "inv_stock": [(_ix("tenant_id", "item_id", "location_id"), {"unique": True})],
    "inv_moves": [
        (_ix("id"), {"unique": True}),
        (_ix("tenant_id", "-id"), {}),
        (_ix("tenant_id", "item_id", "location_id"), {}),
        (_ix("tenant_id", "kind", "at"), {}),
    ],
    "inv_reqs": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "-created_at"), {})],
    "inv_pos": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "-created_at"), {})],
    "inv_counts": [(_ix("id"), {"unique": True}), (_ix("tenant_id", "status", "-created_at"), {})],
    "refresh_tokens": [(_ix("token_hash"), {"unique": True}), (_ix("id"), {"unique": True}), (_ix("user_id"), {})],
    "rooms": [
        (_ix("id"), {"unique": True}),
        (_ix("guest_token"), {"unique": True}),
        (_ix("tenant_id", "number"), {"unique": True}),
        (_ix("tenant_id", "floor", "number"), {}),
    ],
    "roster_snapshots": [(_ix("tenant_id"), {"unique": True})],
}


def ensure_indexes(d: Database) -> None:
    """Idempotent: create_index is a no-op when the index already exists."""
    for name, specs in INDEXES.items():
        for keys, opts in specs:
            d[name].create_index(keys, **opts)


# ------------------------------------------------------------------ ids, time, serialisation
def next_id(name: str, n: int = 1) -> int:
    """Next integer id for `name` (atomic). With n > 1 a block is reserved and its first id is returned."""
    doc = db().counters.find_one_and_update({"_id": name}, {"$inc": {"seq": n}}, upsert=True, return_document=ReturnDocument.AFTER)
    return int(doc["seq"]) - n + 1


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(v: Any) -> Any:
    """Render a stored UTC datetime the way the API always has: server-local ISO time without offset."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v.astimezone().replace(tzinfo=None).isoformat()
    return v


def iso_aware(v: Any) -> Any:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v.astimezone().isoformat()
    return v


def _plain(v: Any) -> Any:
    if isinstance(v, datetime):
        return iso(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return v


def clean(doc: dict | None, aware: tuple[str, ...] = ()) -> dict | None:
    """API-ready copy: drop `_id` and internal `_` fields, datetimes -> ISO strings."""
    if doc is None:
        return None
    return {k: (iso_aware(v) if k in aware else _plain(v)) for k, v in doc.items() if not k.startswith("_")}


def find(name: str, flt: dict, sort: list | None = None, limit: int = 0, aware: tuple[str, ...] = ()) -> list[dict]:
    cur = col(name).find(flt)
    if sort:
        cur = cur.sort(sort)
    if limit:
        cur = cur.limit(limit)
    return [clean(d, aware) for d in cur]


def find_one(name: str, flt: dict, aware: tuple[str, ...] = ()) -> dict | None:
    return clean(col(name).find_one(flt), aware)


# User-keyed maps (employee ids, preference names) are stored as [{"k":..., "v":...}] so any key is safe in MongoDB.
def to_pairs(d: dict | None) -> list[dict]:
    return [{"k": str(k), "v": v} for k, v in (d or {}).items()]


def from_pairs(p: Any) -> dict:
    if isinstance(p, dict):
        return dict(p)
    return {x["k"]: x["v"] for x in (p or [])}
