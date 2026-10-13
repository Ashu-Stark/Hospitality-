"""Local (community-driven) experiences hosted by registered local businesses, and "request to join" requests.

* Hosts are businesses of type guide, homestay or adventure operator with an ACTIVE registration. A host lists
  experiences from the business dashboard; each one is linked to a destination and to 1-3 registered homestays
  nearby ("stay nearby"), so a visitor's spend stays local.
* Public pages list and show experiences. "Request to join" takes no payment: it creates a request that only the
  host business owner sees (with the visitor's contact) and can accept or decline.
* Seeded experiences are SYNTHETIC sample text (prices, group sizes, community-share notes are illustrative).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .. import catalog, mongo
from ..errors import Conflict, Forbidden, Invalid, NotFound
from ..seed.destinations import BY_ID_DEST
from ..seed.districts import BY_ID as DISTRICTS
from . import registry, search

PAGE_SIZE = 12
MAX_LISTED_PER_BUSINESS = 12
MAX_STAYS = 3
JOIN_HORIZON_DAYS = 365
NOTE = "Sample listings for the concept: hosts, prices, group sizes and community-share notes are synthetic. No payment is taken here."


def _host_public(b: dict | None) -> dict | None:
    if not b:
        return None
    p = registry.public(b)
    return {
        k: p[k]
        for k in (
            "id",
            "name",
            "type",
            "type_label",
            "reg_no",
            "status",
            "verified",
            "rating",
            "district_name",
            "destination_name",
            "languages",
        )
    }


def public(e: dict, host: dict | None = None, stays: list[dict] | None = None) -> dict:
    dest = BY_ID_DEST.get(e["destination_id"], {})
    out = {
        "id": e["id"],
        "title": e["title"],
        "type": e["type"],
        "type_label": catalog.LOCAL_EXPERIENCE_TYPES.get(e["type"], e["type"]),
        "destination_id": e["destination_id"],
        "destination_name": dest.get("name"),
        "district": e["district"],
        "district_name": DISTRICTS[e["district"]]["name"],
        "description": e["description"],
        "duration_hours": e["duration_hours"],
        "group_min": e["group_min"],
        "group_max": e["group_max"],
        "price_min": e.get("price_min"),
        "price_max": e.get("price_max"),
        "price_note": "Per person, indicative (sample)" if e.get("synthetic") else "Per person, set by the host",
        "languages": e.get("languages", []),
        "months": e.get("months", []),
        "community_share": e.get("community_share"),
        "what_to_bring": e.get("what_to_bring", []),
        "host_business_id": e["host_business_id"],
        "stay_business_ids": e.get("stay_business_ids", []),
        "status": e.get("status", "listed"),
        "synthetic": bool(e.get("synthetic")),
    }
    if host is not None:
        out["host"] = _host_public(host)
    if stays is not None:
        out["stays_nearby"] = [registry.public(s) for s in stays]
    return out


def _businesses(ids: list[str]) -> dict[str, dict]:
    return {b["id"]: mongo.clean(b) for b in mongo.db().businesses.find({"id": {"$in": list(set(ids))}})}


def list_public(
    *,
    type: str | None = None,
    destination: str | None = None,
    district: str | None = None,
    month: int | None = None,
    q: str | None = None,
    host: str | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict:
    f: dict = {"status": "listed"}
    if type:
        if type not in catalog.LOCAL_EXPERIENCE_TYPES:
            raise Invalid("Unknown experience type.")
        f["type"] = type
    if destination:
        f["destination_id"] = destination
    if district:
        if district not in DISTRICTS:
            raise Invalid("Unknown district.")
        f["district"] = district
    if month:
        f["months"] = month
    if host:
        f["host_business_id"] = host
    f.update(search.regex_filter(q))
    d = mongo.db()
    docs = [mongo.clean(e) for e in d.local_experiences.find(f).sort([("destination_id", 1), ("id", 1)])]
    hosts = _businesses([e["host_business_id"] for e in docs])
    today = date.today().isoformat()
    # Only experiences whose host registration is currently active are public.
    docs = [
        e for e in docs if e["host_business_id"] in hosts and registry.effective_status(hosts[e["host_business_id"]], today) == "active"
    ]
    total = len(docs)
    start = (page - 1) * page_size
    items = [public(e, hosts[e["host_business_id"]]) for e in docs[start : start + page_size]]
    by_type: dict[str, int] = {}
    for e in docs:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "by_type": by_type,
        "types": [{"key": k, "label": v} for k, v in catalog.LOCAL_EXPERIENCE_TYPES.items()],
        "note": NOTE,
    }


def _get(exp_id: str) -> dict:
    e = mongo.db().local_experiences.find_one({"id": exp_id})
    if not e:
        raise NotFound("Experience not found.")
    return mongo.clean(e)


def get_public(exp_id: str) -> dict:
    e = _get(exp_id)
    biz = _businesses([e["host_business_id"], *e.get("stay_business_ids", [])])
    host = biz.get(e["host_business_id"])
    if e.get("status") != "listed" or not host or registry.effective_status(host) != "active":
        raise NotFound("Experience not found.")
    today = date.today().isoformat()
    stays = [biz[s] for s in e.get("stay_business_ids", []) if s in biz and registry.effective_status(biz[s], today) == "active"]
    out = public(e, host, stays)
    more = mongo.db().local_experiences.find({"destination_id": e["destination_id"], "status": "listed", "id": {"$ne": e["id"]}}).limit(3)
    out["more_here"] = [{"id": m["id"], "title": m["title"], "type": m["type"]} for m in more]
    out["note"] = NOTE
    out["join_note"] = (
        "Request to join sends your request to the host only. No payment is taken on this portal; the host replies with "
        "availability and how to pay. Your contact is shared with this host only."
    )
    return out


def for_destination(dest_id: str, limit: int = 4) -> dict:
    r = list_public(destination=dest_id, page_size=limit)
    return {"items": r["items"], "total": r["total"]}


def counts_by_destination() -> dict[str, int]:
    out: dict[str, int] = {}
    for e in mongo.db().local_experiences.find({"status": "listed"}, {"destination_id": 1}):
        out[e["destination_id"]] = out.get(e["destination_id"], 0) + 1
    return out


# ------------------------------------------------------------------ host side (business dashboard)
def _host_business(user_id: str, business_id: str) -> dict:
    b = mongo.db().businesses.find_one({"id": business_id, "owner_user_id": user_id})
    if not b:
        raise NotFound("Business not found in your account.")
    b = mongo.clean(b)
    if b["type"] not in catalog.LOCAL_EXPERIENCE_HOST_TYPES:
        raise Forbidden("Only guides, homestays and adventure operators can list local experiences.")
    if registry.effective_status(b) != "active":
        raise Forbidden("This registration is not active. Renew it to list experiences.")
    return b


def _check(data: dict, b: dict, existing: dict | None = None) -> dict:
    cur = {**(existing or {}), **{k: v for k, v in data.items() if v is not None}}
    if cur.get("type") not in catalog.LOCAL_EXPERIENCE_TYPES:
        raise Invalid("Unknown experience type.")
    dest_id = cur.get("destination_id") or b.get("destination_id")
    if dest_id not in BY_ID_DEST:
        raise Invalid("Unknown destination.")
    if BY_ID_DEST[dest_id]["district"] != b["district"]:
        raise Invalid("The destination must be in your business's district.")
    if cur["group_max"] < cur["group_min"]:
        raise Invalid("Group size: the maximum is below the minimum.")
    if cur.get("price_min") is not None and cur.get("price_max") is not None and cur["price_max"] < cur["price_min"]:
        raise Invalid("Price: the maximum is below the minimum.")
    months = sorted({int(m) for m in cur.get("months") or []})
    if not months or any(m < 1 or m > 12 for m in months):
        raise Invalid("Choose the months when the experience runs (1-12).")
    stays = list(dict.fromkeys(cur.get("stay_business_ids") or []))[:MAX_STAYS]
    if stays:
        found = _businesses(stays)
        bad = [s for s in stays if s not in found or found[s]["type"] != "homestay" or found[s]["district"] != b["district"]]
        if bad:
            raise Invalid("Stays nearby must be registered homestays in your district: " + ", ".join(bad))
    langs = [x for x in dict.fromkeys(cur.get("languages") or []) if x in catalog.LANGUAGES]
    return {
        "title": re.sub(r"\s+", " ", cur["title"]).strip(),
        "type": cur["type"],
        "destination_id": dest_id,
        "district": b["district"],
        "description": cur["description"].strip(),
        "duration_hours": cur["duration_hours"],
        "group_min": cur["group_min"],
        "group_max": cur["group_max"],
        "price_min": cur.get("price_min"),
        "price_max": cur.get("price_max"),
        "languages": langs,
        "months": months,
        "stay_business_ids": stays,
        "community_share": (cur.get("community_share") or "").strip() or None,
        "what_to_bring": [x.strip() for x in (cur.get("what_to_bring") or []) if x and x.strip()][:6],
    }


def _owner_view(e: dict, req_counts: dict | None = None) -> dict:
    out = public(e)
    out["requests"] = (req_counts or {}).get(e["id"], {"pending": 0, "total": 0})
    out["created_at"] = mongo.iso(e.get("created_at"))
    return out


def mine(user_id: str) -> dict:
    d = mongo.db()
    owned = [mongo.clean(b) for b in d.businesses.find({"owner_user_id": user_id}).sort("name_lc", 1)]
    hosts = [b for b in owned if b["type"] in catalog.LOCAL_EXPERIENCE_HOST_TYPES]
    host_ids = [b["id"] for b in hosts]
    items = [
        mongo.clean(e)
        for e in d.local_experiences.find({"host_business_id": {"$in": host_ids}, "status": {"$ne": "archived"}}).sort("id", 1)
    ]
    counts: dict[str, dict] = {}
    for r in d.experience_requests.find({"host_business_id": {"$in": host_ids}}, {"experience_id": 1, "status": 1}):
        c = counts.setdefault(r["experience_id"], {"pending": 0, "total": 0})
        c["total"] += 1
        c["pending"] += r["status"] == "pending"
    today = date.today().isoformat()
    return {
        "items": [_owner_view(e, counts) for e in items],
        "total": len(items),
        "can_host": any(registry.effective_status(b, today) == "active" for b in hosts),
        "host_businesses": [
            {
                "id": b["id"],
                "name": b["name"],
                "type": b["type"],
                "district": b["district"],
                "destination_id": b.get("destination_id"),
                "status": registry.effective_status(b, today),
            }
            for b in hosts
        ],
        "types": [{"key": k, "label": v} for k, v in catalog.LOCAL_EXPERIENCE_TYPES.items()],
        "requests_pending": sum(c["pending"] for c in counts.values()),
    }


def create(user_id: str, actor: str, data: dict) -> dict:
    b = _host_business(user_id, data.pop("business_id"))
    d = mongo.db()
    if d.local_experiences.count_documents({"host_business_id": b["id"], "status": "listed"}) >= MAX_LISTED_PER_BUSINESS:
        raise Conflict(f"At most {MAX_LISTED_PER_BUSINESS} listed experiences per business.")
    clean = _check(data, b)
    now = mongo.now()
    doc = {
        "id": f"LX-{mongo.next_seq('local_experience'):04d}",
        **clean,
        "host_business_id": b["id"],
        "owner_user_id": user_id,
        "status": "listed",
        "synthetic": False,
        "created_at": now,
        "updated_at": now,
    }
    dest = BY_ID_DEST[doc["destination_id"]]
    doc["search_text"] = search.normalize(
        doc["title"], catalog.LOCAL_EXPERIENCE_TYPES[doc["type"]], dest["name"], DISTRICTS[doc["district"]]["name"], b["name"]
    )
    d.local_experiences.insert_one(doc)
    _changed()
    mongo.audit(actor, "experience.listed", doc["id"], b["id"], b["district"])
    return _owner_view(mongo.clean(doc))


def _own(user_id: str, exp_id: str) -> dict:
    e = mongo.db().local_experiences.find_one({"id": exp_id, "owner_user_id": user_id, "status": {"$ne": "archived"}})
    if not e:
        raise NotFound("Experience not found in your account.")
    return mongo.clean(e)


def update(user_id: str, exp_id: str, actor: str, data: dict) -> dict:
    e = _own(user_id, exp_id)
    status = data.pop("status", None)
    b = _host_business(user_id, e["host_business_id"])
    upd = _check(data, b, e)
    if status in ("listed", "paused"):
        upd["status"] = status
    upd["updated_at"] = mongo.now()
    mongo.db().local_experiences.update_one({"id": exp_id}, {"$set": upd})
    _changed()
    mongo.audit(actor, "experience.updated", exp_id, status or "", b["district"])
    return _owner_view(_own(user_id, exp_id))


def delete(user_id: str, exp_id: str, actor: str) -> dict:
    """Remove from the public list (archived). Pending join requests are declined automatically."""
    e = _own(user_id, exp_id)
    d = mongo.db()
    d.local_experiences.update_one({"id": exp_id}, {"$set": {"status": "archived", "updated_at": mongo.now()}})
    _changed()
    n = d.experience_requests.update_many(
        {"experience_id": exp_id, "status": "pending"},
        {"$set": {"status": "declined", "decided_at": mongo.now(), "reason": "Experience withdrawn"}},
    ).modified_count
    mongo.audit(actor, "experience.archived", exp_id, f"{n} pending requests declined", e["district"])
    return {"id": exp_id, "status": "archived", "requests_declined": n}


# ------------------------------------------------------------------ join requests
def _req_host_view(r: dict, exps: dict[str, dict]) -> dict:
    e = exps.get(r["experience_id"], {})
    return {
        "id": r["id"],
        "experience_id": r["experience_id"],
        "experience_title": e.get("title"),
        "host_business_id": r["host_business_id"],
        "name": r["name"],
        "group_size": r["group_size"],
        "date": r["date"],
        "contact": r["contact"],
        "note": r.get("note"),
        "status": r["status"],
        "created_at": mongo.iso(r.get("created_at")),
        "decided_at": mongo.iso(r.get("decided_at")),
        "synthetic": bool(r.get("synthetic")),
    }


def request_join(exp_id: str, data: dict) -> dict:
    e = get_public(exp_id)  # 404 for unlisted experiences or inactive hosts
    try:
        day = date.fromisoformat(data["date"])
    except ValueError:
        raise Invalid("date must be YYYY-MM-DD.") from None
    today = date.today()
    if day < today or day > today + timedelta(days=JOIN_HORIZON_DAYS):
        raise Invalid(f"Choose a date between today and {JOIN_HORIZON_DAYS} days from now.")
    if day.month not in e["months"]:
        raise Invalid("The host does not run this experience in that month. See the season on the page.")
    if not (e["group_min"] <= data["group_size"] <= e["group_max"]):
        raise Invalid(f"Group size must be between {e['group_min']} and {e['group_max']}.")
    doc = {
        "id": f"JR-{mongo.next_seq('experience_request'):06d}",
        "experience_id": exp_id,
        "host_business_id": e["host_business_id"],
        "owner_user_id": mongo.db().businesses.find_one({"id": e["host_business_id"]}, {"owner_user_id": 1}).get("owner_user_id"),
        "name": data["name"],
        "group_size": data["group_size"],
        "date": day.isoformat(),
        "contact": data["contact"],
        "note": data.get("note"),
        "status": "pending",
        "synthetic": False,
        "created_at": mongo.now(),
        "decided_at": None,
    }
    mongo.db().experience_requests.insert_one(doc)
    mongo.audit("public", "experience.join_requested", doc["id"], exp_id, e["district"])
    return {
        "request_id": doc["id"],
        "status": "pending",
        "experience_id": exp_id,
        "host_name": e["host"]["name"],
        "message": "Request sent to the host. They will contact you to confirm; no payment is taken on this portal.",
    }


def host_requests(user_id: str, status: str | None = None) -> dict:
    d = mongo.db()
    f: dict = {"owner_user_id": user_id}
    if status:
        if status not in catalog.JOIN_REQUEST_STATUSES:
            raise Invalid("Unknown status.")
        f["status"] = status
    reqs = [mongo.clean(r) for r in d.experience_requests.find(f).sort("created_at", -1).limit(200)]
    exps = {e["id"]: e for e in d.local_experiences.find({"id": {"$in": list({r["experience_id"] for r in reqs})}}, {"id": 1, "title": 1})}
    items = [_req_host_view(r, exps) for r in reqs]
    return {"items": items, "total": len(items), "pending": sum(1 for i in items if i["status"] == "pending")}


def decide(user_id: str, req_id: str, action: str, actor: str) -> dict:
    d = mongo.db()
    r = d.experience_requests.find_one({"id": req_id, "owner_user_id": user_id})
    if not r:
        raise NotFound("Request not found in your account.")
    new = {"accept": "accepted", "decline": "declined"}[action]
    if r["status"] != "pending":
        raise Conflict(f"This request is already {r['status']}.")
    d.experience_requests.update_one({"id": req_id, "status": "pending"}, {"$set": {"status": new, "decided_at": mongo.now()}})
    mongo.audit(actor, f"experience.request_{new}", req_id, r["experience_id"], None)
    r = mongo.clean(d.experience_requests.find_one({"id": req_id}))
    exps = {e["id"]: e for e in d.local_experiences.find({"id": r["experience_id"]}, {"id": 1, "title": 1})}
    return _req_host_view(r, exps)


def _changed() -> None:
    from . import destinations

    destinations.invalidate_list()
