"""Retry-safe POSTs with an optional Idempotency-Key header (guest requests, staff job actions, supply requests).

Why: Render's gateway can answer 502/504 after the app already did the work, and a phone on hotel Wi-Fi can lose the
answer to a request that succeeded. The guest then taps again (a second job for the same towels) or the worker's retry of
"accept" gets 409 "no longer available" although they did accept. The client now sends one key per attempt and reuses it
for every retry of that attempt; the server stores the first answer and replays it for the same key.

    first request      -> reserve the key (unique index), run the action, store the answer
    same key, same body-> the stored answer again, with "Idempotent-Replayed: true" (nothing runs twice)
    same key, still running (a double tap in flight) -> 409, safe to retry
    same key, different body -> 422 (a client bug: one key must mean one request)
    the action fails   -> the key is released, so a corrected retry is processed normally

Keys are scoped (room token or user id + endpoint), so two clients choosing the same key never collide. Records expire
after 24 h (TTL index in mongo.INDEXES). Without the header nothing changes: old clients keep working.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from fastapi import Header, Response
from fastapi.encoders import jsonable_encoder
from pymongo.errors import DuplicateKeyError

from . import mongo
from .services.errors import Conflict, Invalid

TTL_SECONDS = 86400
REPLAYED = "Idempotent-Replayed"

# FastAPI dependency: the header is optional; 8-100 visible characters (a UUID from crypto.randomUUID() fits)
KeyHeader = Header(None, alias="Idempotency-Key", min_length=8, max_length=100, pattern=r"^[\x21-\x7e]+$")


def _fingerprint(body: Any) -> str:
    return hashlib.sha256(json.dumps(jsonable_encoder(body), sort_keys=True).encode()).hexdigest()


def run(scope: str, key: str | None, body: Any, response: Response, action: Callable[[], Any]) -> Any:
    """Runs action() at most once per (scope, key); body is what the client sent (compared on reuse)."""
    if not key:
        return action()
    k, fp = f"{scope}:{key}", _fingerprint(body)
    col = mongo.col("idempotency_keys")
    try:
        col.insert_one({"key": k, "fingerprint": fp, "state": "running", "created_at": mongo.now()})
    except DuplicateKeyError:
        prev = col.find_one({"key": k}) or {}
        if prev.get("fingerprint") != fp:
            raise Invalid("This Idempotency-Key was already used for a different request.") from None
        if prev.get("state") != "done":
            raise Conflict("This request is still being processed. Please wait a moment and try again.") from None
        response.headers[REPLAYED] = "true"
        return prev["result"]
    try:
        result = jsonable_encoder(action())
    except BaseException:
        col.delete_one({"key": k, "state": "running"})  # failed: not stored, so a corrected retry runs normally
        raise
    col.update_one({"key": k}, {"$set": {"state": "done", "result": result}})
    return result
