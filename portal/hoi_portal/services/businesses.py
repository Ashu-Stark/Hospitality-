"""Business-owner side (own businesses, API keys, occupancy) and officer actions on businesses (suspend / reinstate)."""

from __future__ import annotations

import secrets
from datetime import date

from .. import catalog, mongo, security
from ..errors import Conflict, Invalid, NotFound
from . import ingest, registry

MAX_ACTIVE_KEYS = 3
RENEWAL_WINDOW_DAYS = 60


def _owner_view(b: dict) -> dict:
    out = registry.public(b)
    d = mongo.db()
    days_left = (date.fromisoformat(b["valid_until"]) - mongo.today()).days if b.get("valid_until") else None
    open_renewal = d.applications.find_one(
        {"business_id": b["id"], "kind": "renewal", "status": {"$in": ["submitted", "changes_requested"]}}
    )
    out.update(
        days_to_expiry=days_left,
        renewal_due=days_left is not None and days_left <= RENEWAL_WINDOW_DAYS and out["status"] != "suspended",
        open_renewal_id=open_renewal["id"] if open_renewal else None,
        reports_occupancy=b["type"] in catalog.STAY_TYPES,
        api_keys_active=d.api_keys.count_documents({"business_id": b["id"], "revoked": False}),
    )
    return out


def owned(user_id: str) -> list[dict]:
    return [_owner_view(mongo.clean(b)) for b in mongo.db().businesses.find({"owner_user_id": user_id}).sort("name_lc", 1)]


def get_owned(user_id: str, business_id: str) -> dict:
    b = mongo.db().businesses.find_one({"id": business_id, "owner_user_id": user_id})
    if not b:
        raise NotFound("Business not found in your account.")
    return mongo.clean(b)


def owned_detail(user_id: str, business_id: str) -> dict:
    b = get_owned(user_id, business_id)
    out = _owner_view(b)
    if b["type"] in catalog.STAY_TYPES:
        out["occupancy_months"] = ingest.monthly_history(b["id"], 12)
    return out


def dashboard(user_id: str) -> dict:
    from . import applications

    biz = owned(user_id)
    apps = applications.list_own(user_id)["items"]
    return {
        "businesses": biz,
        "applications": apps,
        "summary": {
            "businesses": len(biz),
            "active": sum(1 for b in biz if b["status"] == "active"),
            "renewals_due": sum(1 for b in biz if b["renewal_due"]),
            "applications_open": sum(1 for a in apps if a["status"] in ("submitted", "changes_requested")),
            "changes_requested": sum(1 for a in apps if a["status"] == "changes_requested"),
        },
    }


# ------------------------------------------------------------------ API keys (shown once, stored as SHA-256)
def _key_public(k: dict) -> dict:
    return {
        "id": k["id"],
        "business_id": k["business_id"],
        "label": k.get("label"),
        "prefix": k["prefix"],
        "created_at": mongo.iso(k["created_at"]),
        "last_used_at": mongo.iso(k.get("last_used_at")),
        "revoked": k["revoked"],
    }


def create_key(user_id: str, business_id: str, label: str | None, actor: str) -> dict:
    b = get_owned(user_id, business_id)
    if b["type"] not in catalog.STAY_TYPES:
        raise Invalid("API keys are for hotels and homestays that report occupancy.")
    d = mongo.db()
    if d.api_keys.count_documents({"business_id": b["id"], "revoked": False}) >= MAX_ACTIVE_KEYS:
        raise Conflict(f"At most {MAX_ACTIVE_KEYS} active keys per business. Revoke one first.")
    raw, digest = security.new_api_key()
    doc = {
        "id": "key_" + secrets.token_hex(6),
        "business_id": b["id"],
        "owner_user_id": user_id,
        "label": (label or "HOI ingest").strip()[:60],
        "key_hash": digest,
        "prefix": raw[:10],
        "created_at": mongo.now(),
        "last_used_at": None,
        "revoked": False,
    }
    d.api_keys.insert_one(doc)
    mongo.audit(actor, "apikey.created", b["id"], doc["prefix"], b["district"])
    out = _key_public(doc)
    out["api_key"] = raw
    out["warning"] = "Copy this key now. It is shown only once and stored only as a hash."
    return out


def list_keys(user_id: str, business_id: str) -> dict:
    b = get_owned(user_id, business_id)
    items = [_key_public(k) for k in mongo.db().api_keys.find({"business_id": b["id"]}).sort("created_at", -1)]
    return {"items": items, "total": len(items)}


def revoke_key(user_id: str, business_id: str, key_id: str, actor: str) -> dict:
    b = get_owned(user_id, business_id)
    k = mongo.db().api_keys.find_one_and_update(
        {"id": key_id, "business_id": b["id"]}, {"$set": {"revoked": True, "revoked_at": mongo.now()}}
    )
    if not k:
        raise NotFound("Key not found.")
    mongo.audit(actor, "apikey.revoked", b["id"], k["prefix"], b["district"])
    return _key_public({**k, "revoked": True})


# ------------------------------------------------------------------ officer actions
def officer_list(district: str | None, status: str | None, type: str | None, q: str | None, page: int, page_size: int) -> dict:
    return registry.list_businesses(district=district, status=status, type=type, q=q, page=page, page_size=page_size)


def set_status(business_id: str, status: str, reason: str, district: str | None, actor: str) -> dict:
    if status not in ("active", "suspended"):
        raise Invalid("Officers can set status to active (reinstate) or suspended.")
    f = {"id": business_id}
    if district:
        f["district"] = district
    b = mongo.db().businesses.find_one(f)
    if not b:
        raise NotFound("Business not found.")
    if status == "active" and b["status"] != "suspended":
        raise Conflict("Only a suspended business can be reinstated.")
    mongo.db().businesses.update_one(
        {"id": business_id},
        {"$set": {"status": status, "status_reason": reason, "status_changed_at": mongo.now(), "verified": b.get("verified")}},
    )
    mongo.audit(actor, f"business.{status}", business_id, reason, b["district"])
    return registry.public(mongo.clean(mongo.db().businesses.find_one({"id": business_id})))
