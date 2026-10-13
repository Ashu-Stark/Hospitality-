"""Road / weather / general advisories posted by district officers (open / caution / closed, segment, reason, expiry).

Seeded advisories carry `sample: true` and say so in their text: they are not real road status.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from .. import catalog, mongo
from ..errors import Invalid, NotFound
from ..seed.destinations import BY_ID_DEST
from ..seed.districts import BY_ID as DISTRICTS
from . import search

MAX_DAYS = 60


def active_filter() -> dict:
    return {"expires_at": {"$gt": mongo.now()}}


def public(a: dict) -> dict:
    dest = BY_ID_DEST.get(a.get("destination_id"))
    return {
        "id": a["id"],
        "kind": a["kind"],
        "status": a.get("status"),
        "district": a["district"],
        "district_name": DISTRICTS[a["district"]]["name"],
        "destination_id": a.get("destination_id"),
        "destination_name": dest["name"] if dest else None,
        "segment": a.get("segment"),
        "title": a["title"],
        "reason": a.get("reason"),
        "posted_at": mongo.iso(a.get("posted_at")),
        "expires_at": mongo.iso(a.get("expires_at")),
        "active": mongo.aware(a["expires_at"]) > mongo.now(),
        "sample": bool(a.get("sample")),
        "posted_by_role": a.get("posted_by_role"),
    }


def search_text(a: dict) -> str:
    dest = BY_ID_DEST.get(a.get("destination_id"), {})
    return search.normalize(a["title"], a.get("segment"), a.get("reason"), a["kind"], DISTRICTS[a["district"]]["name"], dest.get("name"))


def list_public(district: str | None = None, destination: str | None = None, kind: str | None = None) -> dict:
    f = active_filter()
    if district:
        if district not in DISTRICTS:
            raise Invalid("Unknown district.")
        f["district"] = district
    if destination:
        if destination not in BY_ID_DEST:
            raise Invalid("Unknown destination.")
        f["$or"] = [{"destination_id": destination}, {"district": BY_ID_DEST[destination]["district"], "destination_id": None}]
    if kind:
        f["kind"] = kind
    items = [public(a) for a in mongo.db().advisories.find(f).sort("posted_at", -1)]
    order = {"closed": 0, "caution": 1, "open": 2, None: 3}
    items.sort(key=lambda a: order.get(a["status"], 3))
    by_district = {}
    for a in items:
        by_district.setdefault(a["district"], 0)
        by_district[a["district"]] += 1
    return {
        "items": items,
        "total": len(items),
        "by_district": by_district,
        "note": "Items marked sample are illustrative, not real road status.",
    }


def _validate(body: dict, district: str) -> dict:
    kind = body.get("kind") or "road"
    if kind not in catalog.ADVISORY_KINDS:
        raise Invalid("kind must be road, weather or general.")
    status = body.get("status")
    if kind == "road" and status not in catalog.ROAD_STATUSES:
        raise Invalid("Road advisories need status open, caution or closed.")
    if status is not None and status not in catalog.ROAD_STATUSES:
        raise Invalid("status must be open, caution or closed.")
    dest = body.get("destination_id")
    if dest and (dest not in BY_ID_DEST or BY_ID_DEST[dest]["district"] != district):
        raise Invalid("That destination is not in this district.")
    exp = body.get("expires_at")
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        except ValueError:
            raise Invalid("expires_at must be an ISO date-time.") from None
    exp = mongo.aware(exp) if exp else mongo.now() + timedelta(days=3)
    if exp <= mongo.now() or exp > mongo.now() + timedelta(days=MAX_DAYS):
        raise Invalid(f"expires_at must be in the future and within {MAX_DAYS} days.")
    return {
        "kind": kind,
        "status": status,
        "destination_id": dest or None,
        "segment": (body.get("segment") or "").strip() or None,
        "title": body["title"].strip(),
        "reason": (body.get("reason") or "").strip() or None,
        "expires_at": exp,
    }


def create(body: dict, district: str, actor: str, role: str, sample: bool = False) -> dict:
    if district not in DISTRICTS:
        raise Invalid("Unknown district.")
    doc = _validate(body, district) | {
        "id": "adv_" + secrets.token_hex(5),
        "district": district,
        "posted_at": mongo.now(),
        "posted_by": actor,
        "posted_by_role": role,
        "sample": sample,
    }
    doc["search_text"] = search_text(doc)
    mongo.db().advisories.insert_one(doc)
    _changed()
    mongo.audit(actor, "advisory.created", doc["id"], doc["title"], district)
    return public(doc)


def _get_scoped(adv_id: str, district: str | None) -> dict:
    f = {"id": adv_id}
    if district:
        f["district"] = district
    a = mongo.db().advisories.find_one(f)
    if not a:
        raise NotFound("Advisory not found.")
    return a


def update(adv_id: str, body: dict, district: str | None, actor: str) -> dict:
    a = _get_scoped(adv_id, district)
    merged = {**a, **{k: v for k, v in body.items() if v is not None}}
    doc = _validate(merged, a["district"])
    doc["search_text"] = search_text({**a, **doc})
    mongo.db().advisories.update_one({"id": adv_id}, {"$set": doc})
    _changed()
    mongo.audit(actor, "advisory.updated", adv_id, doc["title"], a["district"])
    return public(mongo.db().advisories.find_one({"id": adv_id}))


def expire(adv_id: str, district: str | None, actor: str) -> dict:
    """Withdraw an advisory now (kept for the record)."""
    a = _get_scoped(adv_id, district)
    mongo.db().advisories.update_one({"id": adv_id}, {"$set": {"expires_at": mongo.now()}})
    _changed()
    mongo.audit(actor, "advisory.withdrawn", adv_id, a["title"], a["district"])
    return public(mongo.db().advisories.find_one({"id": adv_id}))


def list_scoped(district: str | None, include_expired: bool = True) -> dict:
    f: dict = {} if include_expired else active_filter()
    if district:
        f["district"] = district
    items = [public(a) for a in mongo.db().advisories.find(f).sort("posted_at", -1).limit(200)]
    return {"items": items, "total": len(items)}


def _changed() -> None:
    from . import destinations

    destinations.invalidate_list()
