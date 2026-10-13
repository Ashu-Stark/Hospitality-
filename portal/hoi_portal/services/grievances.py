"""Tourist grievances: file (public, rate-limited), track by ticket id + 6-digit tracking code, officer handling.

The tracking code is stored only as SHA-256(ticket:code). The optional contact is visible to officers only.
Status: received -> assigned -> in_progress -> resolved / closed. SLA 7 days (ASSUMED) from filing.
"""

from __future__ import annotations

from datetime import timedelta

from pymongo import ReturnDocument

from .. import catalog, mongo, security
from ..errors import Conflict, Invalid, NotFound
from ..seed.districts import BY_ID as DISTRICTS
from . import registry

NOT_FOUND = "No grievance matches that ticket id and tracking code."


def _overdue(g: dict) -> bool:
    if g["status"] in catalog.GRIEVANCE_OPEN:
        return mongo.now() > mongo.aware(g["sla_due_at"])
    resolved = mongo.aware(g.get("resolved_at"))
    return bool(resolved and resolved > mongo.aware(g["sla_due_at"]))


def public(g: dict, officer: bool = False) -> dict:
    out = {
        "ticket_id": g["ticket_id"],
        "category": g["category"],
        "category_label": catalog.GRIEVANCE_CATEGORIES[g["category"]],
        "district": g["district"],
        "district_name": DISTRICTS[g["district"]]["name"],
        "business_reg_no": g.get("business_reg_no"),
        "status": g["status"],
        "created_at": mongo.iso(g["created_at"]),
        "updated_at": mongo.iso(g.get("updated_at")),
        "sla_due_at": mongo.iso(g["sla_due_at"]),
        "sla_days": catalog.GRIEVANCE_SLA_DAYS,
        "overdue": _overdue(g),
        "resolved_at": mongo.iso(g.get("resolved_at")),
        "timeline": [
            {
                "status": h["status"],
                "at": mongo.iso(h["at"]),
                "note": h.get("note"),
                **({"by": h.get("by"), "public": h.get("public", True)} if officer else {}),
            }
            for h in g.get("history", [])
            if officer or h.get("public", True)
        ],
        "synthetic": bool(g.get("synthetic")),
    }
    if officer:
        out.update(
            description=g["description"], contact=g.get("contact"), assigned_to=g.get("assigned_to"), business_id=g.get("business_id")
        )
    return out


def file(body: dict) -> dict:
    cat, district = body.get("category"), body.get("district")
    if cat not in catalog.GRIEVANCE_CATEGORIES:
        raise Invalid("Unknown category.")
    if district not in DISTRICTS:
        raise Invalid("Unknown district.")
    desc = (body.get("description") or "").strip()
    if len(desc) < 10:
        raise Invalid("Describe the problem in at least 10 characters.")
    reg = (body.get("business_reg_no") or "").strip().upper() or None
    biz = None
    if reg:
        if not registry.REG_RE.match(reg):
            raise Invalid("Registration number format: UK-<TYPE>-<DISTRICT>-<5 digits>.")
        biz = mongo.db().businesses.find_one({"reg_no": reg})
    now = mongo.now()
    ticket = f"UTHP-G-{mongo.next_seq('grievance'):06d}"
    code = security.new_tracking_code()
    doc = {
        "ticket_id": ticket,
        "code_hash": security.tracking_hash(ticket, code),
        "category": cat,
        "district": district,
        "business_reg_no": reg,
        "business_id": biz["id"] if biz else None,
        "description": desc,
        "contact": (body.get("contact") or "").strip() or None,
        "status": "received",
        "assigned_to": None,
        "created_at": now,
        "updated_at": now,
        "sla_due_at": now + timedelta(days=catalog.GRIEVANCE_SLA_DAYS),
        "resolved_at": None,
        "history": [{"status": "received", "at": now, "note": "Grievance received.", "public": True, "by": "system"}],
        "synthetic": False,
    }
    mongo.db().grievances.insert_one(doc)
    mongo.audit("public", "grievance.filed", ticket, cat, district)
    out = public(doc)
    out["tracking_code"] = code
    out["message"] = "Keep the ticket id and tracking code. You need both to check the status. The code is shown only once."
    return out


def track(ticket_id: str, code: str) -> dict:
    ticket_id = (ticket_id or "").strip().upper()[:20]
    code = (code or "").strip()[:6]
    g = mongo.db().grievances.find_one({"ticket_id": ticket_id})
    expected = security.tracking_hash(ticket_id, code)
    if not g or not security.same(g["code_hash"], expected):
        raise NotFound(NOT_FOUND)
    return public(g)


# ------------------------------------------------------------------ officer side
def officer_list(
    district: str | None, status: str | None, overdue: bool | None, category: str | None, page: int = 1, page_size: int = 50
) -> dict:
    f: dict = {}
    if district:
        f["district"] = district
    if status:
        if status not in catalog.GRIEVANCE_STATUSES and status != "open":
            raise Invalid("Unknown status.")
        f["status"] = {"$in": list(catalog.GRIEVANCE_OPEN)} if status == "open" else status
    if category:
        f["category"] = category
    docs = list(mongo.db().grievances.find(f).sort("created_at", -1))
    items = [public(g, officer=True) for g in docs]
    if overdue is not None:
        items = [i for i in items if i["overdue"] == overdue]
    page, page_size = max(1, page), min(max(1, page_size), 100)
    return {
        "items": items[(page - 1) * page_size : page * page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "open": sum(1 for i in items if i["status"] in catalog.GRIEVANCE_OPEN),
        "overdue": sum(1 for i in items if i["overdue"] and i["status"] in catalog.GRIEVANCE_OPEN),
    }


def officer_get(ticket_id: str, district: str | None) -> dict:
    f = {"ticket_id": ticket_id}
    if district:
        f["district"] = district
    g = mongo.db().grievances.find_one(f)
    if not g:
        raise NotFound("Grievance not found.")
    return g


def update(ticket_id: str, body: dict, district: str | None, actor: str) -> dict:
    g = officer_get(ticket_id, district)
    new = body.get("status")
    note = (body.get("note") or "").strip() or None
    public_note = bool(body.get("public", True))
    assign_to = body.get("assign_to")
    if not new and not note and not assign_to:
        raise Invalid("Nothing to update: give a status, a note or assign_to.")
    sets: dict = {"updated_at": mongo.now()}
    if assign_to:
        sets["assigned_to"] = str(assign_to)[:60]
        if not new and g["status"] == "received":
            new = "assigned"
    if new and new != g["status"]:
        if new not in catalog.GRIEVANCE_TRANSITIONS.get(g["status"], ()):
            raise Conflict(f"Cannot move a grievance from {g['status']} to {new}.")
        if new in ("resolved", "closed") and not note:
            raise Invalid("Add a note explaining the resolution.")
        sets["status"] = new
        if new in ("resolved", "closed") and not g.get("resolved_at"):
            sets["resolved_at"] = mongo.now()
        if new == "in_progress" and g["status"] == "resolved":
            sets["resolved_at"] = None
    entry = {"status": sets.get("status", g["status"]), "at": mongo.now(), "note": note, "public": public_note, "by": actor}
    r = mongo.db().grievances.find_one_and_update(
        {"ticket_id": ticket_id, "status": g["status"]}, {"$set": sets, "$push": {"history": entry}}, return_document=ReturnDocument.AFTER
    )
    if not r:
        raise Conflict("Grievance changed meanwhile; reload.")
    mongo.audit(actor, "grievance.updated", ticket_id, f"{g['status']}->{entry['status']}", g["district"])
    return public(r, officer=True)
