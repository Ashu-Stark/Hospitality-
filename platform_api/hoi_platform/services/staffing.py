"""Staffing requests: when a week's roster is short, the hotel asks the tourism portal's staffing partners for extra hands.

Flow: create (stored first, status "pending_send") -> forward to the portal (portal_client.send) -> "sent" with the portal's
reference, or stays "pending_send" with a plain error and can be retried (POST /staffing/requests/{id}/send).
No personal data: department / skill, dates, number of openings and a short note (phone numbers / e-mails masked).
The property's portal API key is read at send time and never stored on the request, logged or returned.
"""

from __future__ import annotations

from datetime import date

from pymongo import DESCENDING

from .. import mongo
from . import portal_client, tenants
from .errors import Invalid, NotFound

STATUSES = ("pending_send", "sent")
MAX_DAYS = 31


def _scrub(text: str) -> str:
    from .guest import scrub  # masks phone numbers and e-mail addresses, caps the length

    return scrub(text or "", 500)


def _out(r: dict) -> dict:
    return mongo.clean(r)


def create(
    tid: str,
    actor: str,
    *,
    department: str,
    date_from: str,
    date_to: str,
    openings: int,
    skill: str = "",
    note: str = "",
    property_id: str | None = None,
    source: str = "manual",
) -> dict:
    prop = tenants.get_property(tid, property_id)
    try:
        d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError:
        raise Invalid("Dates must be real dates (YYYY-MM-DD).") from None
    if d1 < d0:
        raise Invalid("The end date is before the start date.")
    if (d1 - d0).days >= MAX_DAYS:
        raise Invalid(f"One request covers at most {MAX_DAYS} days.")
    doc = {
        "id": mongo.new_id("stf"),
        "tenant_id": tid,
        "property_id": prop["id"],
        "property_name": prop["name"],
        "department": department,
        "skill": (skill or "").strip()[:60],
        "date_from": date_from,
        "date_to": date_to,
        "openings": int(openings),
        "note": _scrub(note),
        "source": source,
        "status": "pending_send",
        "attempts": 0,
        "last_error": None,
        "portal_ref": None,
        "created_by": actor,
        "created_at": mongo.now(),
        "sent_at": None,
    }
    mongo.col("staffing_requests").insert_one(doc)
    tenants.audit(tid, actor, "staffing.requested", f"{doc['id']} {department} x{openings} {date_from}..{date_to}")
    return send(tid, doc["id"], actor)


def _raw(tid: str, rid: str) -> dict:
    r = mongo.col("staffing_requests").find_one({"tenant_id": tid, "id": rid})
    if not r:
        raise NotFound("Staffing request not found.")
    return r


def payload(r: dict) -> dict:
    return {
        "external_id": r["id"],
        "department": r["department"],
        "skill": r.get("skill") or "",
        "date_from": r["date_from"],
        "date_to": r["date_to"],
        "openings": r["openings"],
        "note": r.get("note") or "",
    }


def send(tid: str, rid: str, actor: str) -> dict:
    """Forward (or retry) one request. Never raises for portal failures: the request stays pending with the reason."""
    r = _raw(tid, rid)
    if r["status"] == "sent":
        return _out(r)
    key = tenants.portal_key(tid, r["property_id"])
    sets: dict = {"last_try_at": mongo.now()}
    if not key:
        sets["last_error"] = "No tourism-portal API key is saved for this property (Settings > This property)."
    else:
        try:
            res = portal_client.send(payload(r), key)
            ref = res.get("id") or res.get("request_id") or res.get("reference")
            sets.update(status="sent", sent_at=mongo.now(), last_error=None, portal_ref=str(ref)[:80] if ref else None)
        except portal_client.PortalError as e:
            sets["last_error"] = e.message[:300]
    # claim on status so two concurrent sends cannot both flip a request
    mongo.col("staffing_requests").update_one(
        {"tenant_id": tid, "id": rid, "status": "pending_send"}, {"$set": sets, "$inc": {"attempts": 1}}
    )
    out = _out(_raw(tid, rid))
    tenants.audit(tid, actor, "staffing.sent" if out["status"] == "sent" else "staffing.send_failed", rid)
    return out


def list_requests(tid: str, property_id: str | None = None, limit: int = 100) -> list[dict]:
    flt: dict = {"tenant_id": tid}
    if property_id:
        flt["property_id"] = property_id
    return mongo.find("staffing_requests", flt, [("created_at", DESCENDING), ("_id", DESCENDING)], limit)
