"""Refresh tokens: long-lived, opaque, stored only as a hash, rotated on every use, revocable.

Rotation with reuse detection: presenting a refresh token that was already rotated revokes the whole chain
for that user (it was probably stolen).

Atomicity without transactions: rotation claims the presented token with one conditional update
(`revoked: 0` and not expired -> `revoked: 1, replaced_by: <new id>`), so two concurrent refreshes with the same
token cannot both succeed. The token hash has a unique index.
"""

from __future__ import annotations

from datetime import timedelta

from .. import config, mongo, security
from .errors import Unauthorized


def _new_doc(user_id: str) -> tuple[str, dict]:
    raw, digest = security.new_refresh_token()
    now = mongo.now()
    doc = {
        "id": mongo.new_id("rt"),
        "user_id": user_id,
        "token_hash": digest,
        "expires_at": now + timedelta(days=config.settings.refresh_ttl_days),
        "revoked": 0,
        "created_at": now,
        "replaced_by": None,
    }
    return raw, doc


def issue(user_id: str) -> str:
    raw, doc = _new_doc(user_id)
    mongo.col("refresh_tokens").insert_one(doc)
    return raw


def rotate(raw: str) -> tuple[str, str]:
    """Return (user_id, new_raw_token). Raises Unauthorized for unknown, expired, revoked or reused tokens."""
    rt = mongo.col("refresh_tokens")
    digest = security.hash_refresh(raw)
    t = rt.find_one({"token_hash": digest}, {"user_id": 1})
    if not t:
        raise Unauthorized("Session expired. Sign in again.")
    new_raw, new_doc = _new_doc(t["user_id"])
    claimed = rt.find_one_and_update(
        {"token_hash": digest, "revoked": 0, "expires_at": {"$gt": mongo.now()}},
        {"$set": {"revoked": 1, "replaced_by": new_doc["id"]}},
    )
    if not claimed:
        cur = rt.find_one({"token_hash": digest}) or {}
        if cur.get("revoked") and cur.get("replaced_by"):  # reuse of a rotated token: revoke every session of this user
            revoke_all(cur["user_id"])
        raise Unauthorized("Session expired. Sign in again.")
    rt.insert_one(new_doc)
    return claimed["user_id"], new_raw


def revoke(raw: str) -> None:
    mongo.col("refresh_tokens").update_one({"token_hash": security.hash_refresh(raw)}, {"$set": {"revoked": 1}})


def revoke_all(user_id: str) -> None:
    mongo.col("refresh_tokens").update_many({"user_id": user_id}, {"$set": {"revoked": 1}})
