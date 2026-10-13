"""Business onboarding: application -> officer review (approve / request changes / reject) -> registration number,
and yearly renewal.

States: submitted -> changes_requested -> (edited) submitted -> approved | rejected. Decisions are conditional
single-document updates (`status: submitted`), so two officers cannot decide the same application twice.
"""

from __future__ import annotations

from datetime import date, timedelta

from pymongo import ReturnDocument

from .. import catalog, mongo
from ..errors import Conflict, Forbidden, Invalid, NotFound
from ..seed.destinations import BY_ID_DEST
from ..seed.districts import BY_ID as DISTRICTS
from . import registry
from .businesses import RENEWAL_WINDOW_DAYS, get_owned

OPEN = ("submitted", "changes_requested")
EDITABLE = ("business_name", "type", "district", "destination_id", "capacity", "beds", "languages", "documents", "notes")


def public(a: dict, officer: bool = False) -> dict:
    required = catalog.REQUIRED_DOCS[a["type"]]
    docs = a.get("documents") or {}
    out = {
        "id": a["id"],
        "kind": a["kind"],
        "status": a["status"],
        "business_id": a.get("business_id"),
        "business_name": a["business_name"],
        "type": a["type"],
        "type_label": catalog.BUSINESS_TYPES[a["type"]][0],
        "district": a["district"],
        "district_name": DISTRICTS[a["district"]]["name"],
        "destination_id": a.get("destination_id"),
        "destination_name": BY_ID_DEST[a["destination_id"]]["name"] if a.get("destination_id") in BY_ID_DEST else None,
        "capacity": a.get("capacity"),
        "capacity_unit": catalog.BUSINESS_TYPES[a["type"]][2],
        "beds": a.get("beds"),
        "languages": a.get("languages") or [],
        "documents": docs,
        "required_documents": required,
        "missing_documents": [k for k in required if not docs.get(k)],
        "notes": a.get("notes"),
        "reason": a.get("reason"),
        "reg_no": a.get("reg_no"),
        "submitted_at": mongo.iso(a.get("submitted_at")),
        "updated_at": mongo.iso(a.get("updated_at")),
        "decided_at": mongo.iso(a.get("decided_at")),
        "history": [
            {"at": mongo.iso(h["at"]), "action": h["action"], "reason": h.get("reason"), **({"by": h.get("by")} if officer else {})}
            for h in a.get("history", [])
        ],
        "synthetic": bool(a.get("synthetic")),
    }
    if officer:
        out["owner_user_id"] = a.get("owner_user_id")
    return out


def _validate(body: dict) -> dict:
    btype = body.get("type")
    if btype not in catalog.BUSINESS_TYPES:
        raise Invalid("Unknown business type.")
    district = body.get("district")
    if district not in DISTRICTS:
        raise Invalid("Unknown district.")
    dest = body.get("destination_id")
    if dest is not None and (dest not in BY_ID_DEST or BY_ID_DEST[dest]["district"] != district):
        raise Invalid("Destination must be one of the listed destinations in the chosen district (or leave it empty).")
    docs = body.get("documents") or {}
    unknown = set(docs) - set(catalog.CHECKLIST)
    if unknown:
        raise Invalid(f"Unknown document keys: {', '.join(sorted(unknown))}.")
    langs = [lang for lang in (body.get("languages") or []) if lang in catalog.LANGUAGES]
    name = (body.get("business_name") or "").strip()
    if len(name) < 3:
        raise Invalid("Business name is required.")
    return {
        "business_name": name,
        "type": btype,
        "district": district,
        "destination_id": dest,
        "capacity": int(body["capacity"]),
        "beds": body.get("beds") if btype in catalog.STAY_TYPES else None,
        "languages": langs or ["Hindi"],
        "documents": {k: bool(docs.get(k)) for k in catalog.CHECKLIST},
        "notes": (body.get("notes") or "").strip() or None,
    }


def create(user_id: str, username: str, body: dict) -> dict:
    fields = _validate(body)
    now = mongo.now()
    doc = {
        "id": f"APP-{mongo.next_seq('application'):06d}",
        "kind": "new",
        "status": "submitted",
        "owner_user_id": user_id,
        "business_id": None,
        "reason": None,
        "reg_no": None,
        "submitted_at": now,
        "updated_at": now,
        "decided_at": None,
        "history": [{"at": now, "by": username, "action": "submitted", "reason": None}],
        "synthetic": False,
        **fields,
    }
    mongo.db().applications.insert_one(doc)
    mongo.audit(username, "application.submitted", doc["id"], fields["business_name"], fields["district"])
    return public(doc)


def list_own(user_id: str) -> dict:
    items = [public(a) for a in mongo.db().applications.find({"owner_user_id": user_id}).sort("submitted_at", -1)]
    return {"items": items, "total": len(items)}


def get_own(user_id: str, app_id: str) -> dict:
    a = mongo.db().applications.find_one({"id": app_id, "owner_user_id": user_id})
    if not a:
        raise NotFound("Application not found in your account.")
    return a


def resubmit(user_id: str, username: str, app_id: str, body: dict) -> dict:
    a = get_own(user_id, app_id)
    if a["status"] != "changes_requested":
        raise Conflict("Only applications with changes requested can be edited.")
    merged = {k: a.get(k) for k in EDITABLE} | {k: v for k, v in body.items() if v is not None}
    if a["kind"] == "renewal":  # identity of a renewed business cannot change
        for k in ("type", "district", "destination_id", "business_name"):
            merged[k] = a[k]
    fields = _validate(merged)
    now = mongo.now()
    r = mongo.db().applications.find_one_and_update(
        {"id": app_id, "status": "changes_requested"},
        {
            "$set": {**fields, "status": "submitted", "updated_at": now, "reason": None},
            "$push": {"history": {"at": now, "by": username, "action": "resubmitted", "reason": None}},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not r:
        raise Conflict("Application changed meanwhile; reload.")
    mongo.audit(username, "application.resubmitted", app_id, "", a["district"])
    return public(r)


def renew(user_id: str, username: str, business_id: str) -> dict:
    b = get_owned(user_id, business_id)
    status = registry.effective_status(b)
    if status == "suspended":
        raise Forbidden("A suspended registration cannot be renewed online. Contact the district office.")
    days_left = (date.fromisoformat(b["valid_until"]) - date.today()).days
    if status == "active" and days_left > RENEWAL_WINDOW_DAYS:
        raise Conflict(f"Renewal opens {RENEWAL_WINDOW_DAYS} days before expiry ({b['valid_until']}).")
    d = mongo.db()
    if d.applications.find_one({"business_id": b["id"], "kind": "renewal", "status": {"$in": list(OPEN)}}):
        raise Conflict("A renewal for this business is already under review.")
    now = mongo.now()
    doc = {
        "id": f"APP-{mongo.next_seq('application'):06d}",
        "kind": "renewal",
        "status": "submitted",
        "owner_user_id": user_id,
        "business_id": b["id"],
        "business_name": b["name"],
        "type": b["type"],
        "district": b["district"],
        "destination_id": b.get("destination_id"),
        "capacity": b["capacity"],
        "beds": b.get("beds"),
        "languages": b.get("languages", []),
        "documents": {k: k in catalog.REQUIRED_DOCS[b["type"]] for k in catalog.CHECKLIST},
        "notes": None,
        "reason": None,
        "reg_no": b["reg_no"],
        "submitted_at": now,
        "updated_at": now,
        "decided_at": None,
        "history": [{"at": now, "by": username, "action": "submitted", "reason": None}],
        "synthetic": False,
    }
    d.applications.insert_one(doc)
    if status == "expired":
        d.businesses.update_one({"id": b["id"]}, {"$set": {"status": "pending"}})
    mongo.audit(username, "renewal.submitted", doc["id"], b["reg_no"], b["district"])
    return public(doc)


# ------------------------------------------------------------------ officer side
def officer_list(district: str | None, status: str | None, kind: str | None, page: int = 1, page_size: int = 50) -> dict:
    f: dict = {}
    if district:
        f["district"] = district
    if status:
        if status not in catalog.APPLICATION_STATUSES:
            raise Invalid("Unknown status.")
        f["status"] = status
    if kind:
        if kind not in catalog.APPLICATION_KINDS:
            raise Invalid("Unknown kind.")
        f["kind"] = kind
    col = mongo.db().applications
    page, page_size = max(1, page), min(max(1, page_size), 100)
    total = col.count_documents(f)
    items = [public(a, officer=True) for a in col.find(f).sort("submitted_at", 1).skip((page - 1) * page_size).limit(page_size)]
    counts = {s: col.count_documents({**{k: v for k, v in f.items() if k != "status"}, "status": s}) for s in catalog.APPLICATION_STATUSES}
    return {"items": items, "total": total, "page": page, "page_size": page_size, "counts": counts}


def officer_get(app_id: str, district: str | None) -> dict:
    f = {"id": app_id}
    if district:
        f["district"] = district
    a = mongo.db().applications.find_one(f)
    if not a:
        raise NotFound("Application not found.")
    return public(a, officer=True)


def decide(app_id: str, action: str, reason: str | None, district: str | None, actor: str) -> dict:
    if action not in ("approve", "request_changes", "reject"):
        raise Invalid("action must be approve, request_changes or reject.")
    reason = (reason or "").strip() or None
    if action != "approve" and not reason:
        raise Invalid("Give a reason so the applicant knows what to do.")
    d = mongo.db()
    f = {"id": app_id}
    if district:
        f["district"] = district
    a = d.applications.find_one(f)
    if not a:
        raise NotFound("Application not found.")
    if a["status"] != "submitted":
        raise Conflict(f"Application is {a['status']}; only submitted applications can be decided.")
    if action == "approve":
        missing = [k for k in catalog.REQUIRED_DOCS[a["type"]] if not (a.get("documents") or {}).get(k)]
        if missing:
            raise Invalid("Cannot approve: required documents not ticked: " + ", ".join(catalog.CHECKLIST[k] for k in missing) + ".")
    new_status = {"approve": "approved", "request_changes": "changes_requested", "reject": "rejected"}[action]
    now = mongo.now()
    claimed = d.applications.find_one_and_update(
        {"id": app_id, "status": "submitted"},
        {
            "$set": {"status": new_status, "reason": reason, "decided_at": now, "updated_at": now, "decided_by": actor},
            "$push": {"history": {"at": now, "by": actor, "action": new_status, "reason": reason}},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not claimed:
        raise Conflict("Application was decided by someone else; reload.")
    try:
        if action == "approve":
            claimed = _approve(claimed, actor)
        elif a["kind"] == "renewal" and action == "reject":
            b = d.businesses.find_one({"id": a["business_id"]})
            if b and b["status"] == "pending":
                d.businesses.update_one({"id": b["id"]}, {"$set": {"status": "expired"}})
    except Exception:  # compensating write: put the application back in the queue
        d.applications.update_one({"id": app_id}, {"$set": {"status": "submitted", "decided_at": None}, "$pop": {"history": 1}})
        raise
    mongo.audit(actor, f"application.{new_status}", app_id, reason or "", a["district"])
    return public(claimed, officer=True)


def _approve(a: dict, actor: str) -> dict:
    d = mongo.db()
    today = date.today()
    if a["kind"] == "renewal":
        b = d.businesses.find_one({"id": a["business_id"]})
        if not b:
            raise NotFound("Business for this renewal no longer exists.")
        start = max(today, date.fromisoformat(b["valid_until"]))
        valid = (start + timedelta(days=365)).isoformat()
        d.businesses.update_one(
            {"id": b["id"]}, {"$set": {"status": "active", "valid_until": valid, "capacity": a["capacity"], "renewed_at": mongo.now()}}
        )
        return d.applications.find_one({"id": a["id"]})
    reg_no = registry.issue_reg_no(a["type"], a["district"])
    bid = "biz_" + reg_no.split("-")[-1] + "_" + a["id"][-6:]
    biz = {
        "id": bid,
        "reg_no": reg_no,
        "name": a["business_name"],
        "name_lc": a["business_name"].lower(),
        "type": a["type"],
        "district": a["district"],
        "destination_id": a.get("destination_id"),
        "status": "active",
        "verified": True,
        "rating": None,
        "capacity": a["capacity"],
        "beds": a.get("beds"),
        "languages": a.get("languages", []),
        "registered_on": today.isoformat(),
        "valid_until": (today + timedelta(days=365)).isoformat(),
        "hoi_connected": False,
        "owner_user_id": a["owner_user_id"],
        "synthetic": False,
        "created_at": mongo.now(),
        "application_id": a["id"],
    }
    biz["search_text"] = registry.search_text(biz)
    d.businesses.insert_one(biz)
    return d.applications.find_one_and_update(
        {"id": a["id"]}, {"$set": {"reg_no": reg_no, "business_id": bid}}, return_document=ReturnDocument.AFTER
    )
