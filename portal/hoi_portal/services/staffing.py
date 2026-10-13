"""Staffing agencies and HOI staffing requests on the hiring board.

* A staffing agency is a registered business of type `staffing_agency` (same application -> officer approval ->
  registration number flow as any other business). Its profile lists the skills it pools (`agency_skills`) and the
  districts it serves (`districts_served`).
* Agencies publish BLOCK OFFERS of pooled workers ("12 housekeeping staff available Apr-Jun, Rishikesh"). No worker is
  identified: an offer is a count per skill, place and window.
* HOI integration: when a hotel's roster week is short of staff, the HOI platform calls
  POST /api/v1/ingest/staffing-request with the hotel's business API key. The portal creates (or updates) one job post
  marked "Staffing request via HOI" and notifies every active agency whose skills and districts match (in-portal
  notifications). Idempotent per (business, source_id): repeating a call never creates a second post or re-notifies.
* Agencies respond to a request with how many workers they can supply; the hotel owner sees the responses on the job.
* HOI retention check (GET /api/v1/ingest/candidate-matches, same API key): before posting a job, a hotel can ask how many
  PUBLIC job-seeker profiles fit one skill in its own district. It gets a count and a few anonymised previews (candidate
  code, skills with years, districts, availability, match score). Never a name, headline, bio or contact detail: the hotel
  follows up on the portal itself (interest request -> the job seeker decides whether to share contact details).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .. import catalog, mongo
from ..errors import Conflict, Forbidden, Invalid, NotFound
from ..seed.destinations import BY_ID_DEST
from ..seed.districts import BY_ID as DISTRICTS
from ..seed.skills import BY_KEY as SKILLS
from ..seed.skills import JOB_TYPES
from . import matching, registry

MAX_OPEN_HOI_REQUESTS = 30  # per business
MAX_OPEN_OFFERS = 20  # per agency
MAX_WINDOW_DAYS = 366
# HOI roster roles -> hiring-board skill keys (the platform may send either).
SKILL_ALIASES = {
    "food_beverage": "fb_service",
    "f&b": "fb_service",
    "kitchen": "kitchen_helper",
    "chef": "cook_indian",
    "security": "security_guard",
    "fnb_service": "fb_service",
}
HOI_LABEL = "Staffing request via HOI"
MATCH_PREVIEW_MAX = 5
NOTE = "Agencies and offers shown here are synthetic sample data unless marked otherwise."


def _today() -> date:
    return date.today()


def _skill_key(raw: str) -> str:
    k = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    k = SKILL_ALIASES.get(k, k)
    if k not in SKILLS:
        raise Invalid(f"Unknown skill: {raw}. Use a skill key from GET /api/v1/jobs/meta.")
    return k


def _district_id(raw: str | None, default: str) -> str:
    if not raw:
        return default
    v = raw.strip().lower()
    for did, dd in DISTRICTS.items():
        if v in (did, dd["name"].lower()):
            return did
    raise Invalid(f"Unknown district: {raw}.")


def _dates(a: str, b: str, what: str) -> tuple[date, date]:
    try:
        da, db = date.fromisoformat(a), date.fromisoformat(b)
    except (TypeError, ValueError):
        raise Invalid(f"{what}: dates must be YYYY-MM-DD.") from None
    if db < da:
        raise Invalid(f"{what}: the end date is before the start date.")
    if (db - da).days > MAX_WINDOW_DAYS:
        raise Invalid(f"{what}: at most {MAX_WINDOW_DAYS} days.")
    return da, db


def agency_public(b: dict) -> dict:
    p = registry.public(b)
    out = {
        k: p[k]
        for k in (
            "id",
            "name",
            "reg_no",
            "status",
            "verified",
            "rating",
            "district",
            "district_name",
            "destination_name",
            "languages",
            "synthetic",
        )
    }
    out["pool_size"] = b.get("capacity")
    out["skills"] = [{"key": k, "label": SKILLS[k]["label"]} for k in b.get("agency_skills", []) if k in SKILLS]
    out["districts_served"] = [{"id": d, "name": DISTRICTS[d]["name"]} for d in b.get("districts_served", []) if d in DISTRICTS]
    return out


def offer_public(o: dict, agency: dict | None) -> dict:
    dest = BY_ID_DEST.get(o.get("destination_id"))
    return {
        "id": o["id"],
        "agency": agency_public(agency) if agency else None,
        "skill": {"key": o["skill"], "label": SKILLS[o["skill"]]["label"]} if o["skill"] in SKILLS else None,
        "district": o["district"],
        "district_name": DISTRICTS[o["district"]]["name"],
        "destination_id": o.get("destination_id"),
        "destination_name": dest["name"] if dest else None,
        "workers": o["workers"],
        "available_from": o["available_from"],
        "available_to": o["available_to"],
        "note": o.get("note"),
        "status": o["status"] if o["available_to"] >= _today().isoformat() else "expired",
        "synthetic": bool(o.get("synthetic")),
    }


def _agencies(ids: list[str]) -> dict[str, dict]:
    return {b["id"]: mongo.clean(b) for b in mongo.db().businesses.find({"id": {"$in": list(set(ids))}, "type": "staffing_agency"})}


def list_offers(skill: str | None = None, district: str | None = None, month: int | None = None, page_size: int = 50) -> dict:
    f: dict = {"status": "open", "available_to": {"$gte": _today().isoformat()}}
    if skill:
        f["skill"] = _skill_key(skill)
    if district:
        f["district"] = _district_id(district, district)
    offers = [mongo.clean(o) for o in mongo.db().staffing_offers.find(f).sort("available_from", 1)]
    if month:
        offers = [o for o in offers if month in _months(o["available_from"], o["available_to"])]
    ags = _agencies([o["agency_business_id"] for o in offers])
    today = _today().isoformat()
    offers = [
        o for o in offers if o["agency_business_id"] in ags and registry.effective_status(ags[o["agency_business_id"]], today) == "active"
    ]
    items = [offer_public(o, ags[o["agency_business_id"]]) for o in offers[:page_size]]
    return {"items": items, "total": len(offers), "workers": sum(o["workers"] for o in offers), "note": NOTE}


def _months(a: str, b: str) -> set[int]:
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    out, cur = set(), date(da.year, da.month, 1)
    while cur <= db and len(out) < 12:
        out.add(cur.month)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return out


# ------------------------------------------------------------------ agency owner
def _own_agency(user_id: str, business_id: str, need_active: bool = True) -> dict:
    b = mongo.db().businesses.find_one({"id": business_id, "owner_user_id": user_id})
    if not b:
        raise NotFound("Business not found in your account.")
    b = mongo.clean(b)
    if b["type"] != "staffing_agency":
        raise Forbidden("Only registered staffing agencies can do this.")
    if need_active and registry.effective_status(b) != "active":
        raise Forbidden("This agency's registration is not active. Renew it first.")
    return b


def update_agency(user_id: str, business_id: str, data: dict, actor: str) -> dict:
    b = _own_agency(user_id, business_id, need_active=False)
    upd: dict = {}
    if data.get("agency_skills") is not None:
        upd["agency_skills"] = list(dict.fromkeys(_skill_key(s) for s in data["agency_skills"]))
    if data.get("districts_served") is not None:
        upd["districts_served"] = list(dict.fromkeys(_district_id(x, x) for x in data["districts_served"]))
    if upd:
        mongo.db().businesses.update_one({"id": b["id"]}, {"$set": upd})
        mongo.audit(actor, "agency.updated", b["id"], ", ".join(upd), b["district"])
    return agency_public(mongo.clean(mongo.db().businesses.find_one({"id": b["id"]})))


def create_offer(user_id: str, actor: str, data: dict) -> dict:
    b = _own_agency(user_id, data["business_id"])
    skill = _skill_key(data["skill"])
    district = _district_id(data.get("district"), b["district"])
    dest = data.get("destination_id")
    if dest and (dest not in BY_ID_DEST or BY_ID_DEST[dest]["district"] != district):
        raise Invalid("That destination is not in the chosen district.")
    da, db = _dates(data["available_from"], data["available_to"], "Availability")
    if db < _today():
        raise Invalid("Availability has already ended.")
    d = mongo.db()
    if d.staffing_offers.count_documents({"agency_business_id": b["id"], "status": "open"}) >= MAX_OPEN_OFFERS:
        raise Conflict(f"At most {MAX_OPEN_OFFERS} open offers per agency.")
    now = mongo.now()
    doc = {
        "id": f"OFR-{mongo.next_seq('staffing_offer'):05d}",
        "agency_business_id": b["id"],
        "owner_user_id": user_id,
        "skill": skill,
        "district": district,
        "destination_id": dest,
        "workers": data["workers"],
        "available_from": da.isoformat(),
        "available_to": db.isoformat(),
        "note": (data.get("note") or "").strip() or None,
        "status": "open",
        "synthetic": False,
        "created_at": now,
        "updated_at": now,
    }
    d.staffing_offers.insert_one(doc)
    mongo.audit(actor, "agency.offer_posted", doc["id"], b["id"], district)
    return offer_public(mongo.clean(doc), b)


def update_offer(user_id: str, offer_id: str, data: dict, actor: str) -> dict:
    d = mongo.db()
    o = d.staffing_offers.find_one({"id": offer_id, "owner_user_id": user_id})
    if not o:
        raise NotFound("Offer not found in your account.")
    o = mongo.clean(o)
    upd: dict = {}
    if data.get("workers") is not None:
        upd["workers"] = data["workers"]
    if data.get("note") is not None:
        upd["note"] = data["note"].strip() or None
    if data.get("available_from") or data.get("available_to"):
        da, db = _dates(data.get("available_from") or o["available_from"], data.get("available_to") or o["available_to"], "Availability")
        upd.update(available_from=da.isoformat(), available_to=db.isoformat())
    if data.get("status") in ("open", "withdrawn"):
        upd["status"] = data["status"]
    if upd:
        upd["updated_at"] = mongo.now()
        d.staffing_offers.update_one({"id": offer_id}, {"$set": upd})
        mongo.audit(actor, "agency.offer_updated", offer_id, upd.get("status", ""), o["district"])
    o = mongo.clean(d.staffing_offers.find_one({"id": offer_id}))
    return offer_public(o, _agencies([o["agency_business_id"]]).get(o["agency_business_id"]))


def _matches(agency: dict, skill: str, district: str) -> bool:
    return skill in agency.get("agency_skills", []) and (district in agency.get("districts_served", []) or district == agency["district"])


def _request_view(j: dict, agency_ids: list[str] | None = None) -> dict:
    from .hiring import job_public

    out = job_public(j)
    if agency_ids is not None:
        r = mongo.db().staffing_responses.find_one({"job_id": j["id"], "agency_business_id": {"$in": agency_ids}})
        out["my_response"] = _response_view(mongo.clean(r)) if r else None
    return out


def _response_view(r: dict, agency: dict | None = None) -> dict:
    out = {
        "id": r["id"],
        "job_id": r["job_id"],
        "agency_business_id": r["agency_business_id"],
        "workers": r["workers"],
        "note": r.get("note"),
        "created_at": mongo.iso(r.get("created_at")),
        "updated_at": mongo.iso(r.get("updated_at")),
    }
    if agency:
        out["agency"] = agency_public(agency)
    return out


def agency_dashboard(user_id: str) -> dict:
    """Everything an agency owner needs: own agencies, offers, notifications and matching open HOI requests."""
    d = mongo.db()
    today = _today().isoformat()
    agencies = [mongo.clean(b) for b in d.businesses.find({"owner_user_id": user_id, "type": "staffing_agency"}).sort("name_lc", 1)]
    ids = [a["id"] for a in agencies]
    active = [a for a in agencies if registry.effective_status(a, today) == "active"]
    offers = [
        offer_public(mongo.clean(o), next((a for a in agencies if a["id"] == o["agency_business_id"]), None))
        for o in d.staffing_offers.find({"agency_business_id": {"$in": ids}}).sort("available_from", 1)
    ]
    requests = []
    seen: set[str] = set()
    for j in d.job_posts.find({"via_hoi": True, "status": "open", "closes_on": {"$gte": today}}).sort("created_at", -1).limit(200):
        j = mongo.clean(j)
        if j["id"] in seen:
            continue
        if any(_matches(a, s, j["district"]) for a in active for s in j["skills"]):
            seen.add(j["id"])
            requests.append(_request_view(j, ids))
    notes = notifications(user_id, limit=30)
    return {
        "agencies": [agency_public(a) | {"status": registry.effective_status(a, today)} for a in agencies],
        "offers": offers,
        "open_requests": requests,
        "notifications": notes["items"],
        "unread": notes["unread"],
        "summary": {
            "agencies": len(agencies),
            "open_offers": sum(1 for o in offers if o["status"] == "open"),
            "workers_offered": sum(o["workers"] for o in offers if o["status"] == "open"),
            "open_requests": len(requests),
            "responded": sum(1 for r in requests if r.get("my_response")),
        },
        "note": NOTE,
    }


def respond(user_id: str, job_id: str, data: dict, actor: str) -> dict:
    b = _own_agency(user_id, data["business_id"])
    d = mongo.db()
    j = d.job_posts.find_one({"id": job_id, "via_hoi": True})
    if not j:
        raise NotFound("Staffing request not found.")
    j = mongo.clean(j)
    if j["status"] != "open" or j["closes_on"] < _today().isoformat():
        raise Conflict("This staffing request is closed.")
    if not any(_matches(b, s, j["district"]) for s in j["skills"]):
        raise Forbidden("Your agency does not list this skill or district. Update your agency profile first.")
    now = mongo.now()
    existing = d.staffing_responses.find_one({"job_id": job_id, "agency_business_id": b["id"]})
    if existing:
        d.staffing_responses.update_one(
            {"id": existing["id"]}, {"$set": {"workers": data["workers"], "note": data.get("note"), "updated_at": now}}
        )
        rid = existing["id"]
    else:
        rid = f"SR-{mongo.next_seq('staffing_response'):06d}"
        d.staffing_responses.insert_one(
            {
                "id": rid,
                "job_id": job_id,
                "agency_business_id": b["id"],
                "owner_user_id": user_id,
                "job_owner_user_id": j.get("owner_user_id"),
                "workers": data["workers"],
                "note": data.get("note"),
                "created_at": now,
                "updated_at": now,
            }
        )
        if j.get("owner_user_id"):
            _notify(
                j["owner_user_id"],
                j["business_id"],
                "agency_response",
                job_id,
                f"{b['name']} can supply {data['workers']} worker(s)",
                j["title"],
            )
    d.notifications.update_many({"user_id": user_id, "job_id": job_id}, {"$set": {"read": True}})
    mongo.audit(actor, "agency.responded", job_id, f"{b['id']} {data['workers']}", j["district"])
    return _response_view(mongo.clean(d.staffing_responses.find_one({"id": rid})), b)


def responses_for_job(job_id: str) -> list[dict]:
    rs = [mongo.clean(r) for r in mongo.db().staffing_responses.find({"job_id": job_id}).sort("created_at", 1)]
    ags = _agencies([r["agency_business_id"] for r in rs])
    return [_response_view(r, ags.get(r["agency_business_id"])) for r in rs]


# ------------------------------------------------------------------ notifications (in-portal)
def _notify(user_id: str, business_id: str, kind: str, job_id: str, title: str, text: str) -> bool:
    """One notification per (user, kind, job). Returns True when a new one was created."""
    d = mongo.db()
    if d.notifications.find_one({"user_id": user_id, "kind": kind, "job_id": job_id, "business_id": business_id}):
        return False
    d.notifications.insert_one(
        {
            "id": f"NTF-{mongo.next_seq('notification'):06d}",
            "user_id": user_id,
            "business_id": business_id,
            "kind": kind,
            "job_id": job_id,
            "title": title[:160],
            "text": text[:300],
            "read": False,
            "created_at": mongo.now(),
        }
    )
    return True


def notifications(user_id: str, limit: int = 50) -> dict:
    d = mongo.db()
    items = [
        {k: n.get(k) for k in ("id", "business_id", "kind", "job_id", "title", "text", "read")} | {"created_at": mongo.iso(n["created_at"])}
        for n in d.notifications.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
    ]
    return {"items": items, "total": len(items), "unread": d.notifications.count_documents({"user_id": user_id, "read": False})}


def mark_read(user_id: str, note_id: str) -> dict:
    r = mongo.db().notifications.update_one({"id": note_id, "user_id": user_id}, {"$set": {"read": True}})
    if not r.matched_count:
        raise NotFound("Notification not found.")
    return {"id": note_id, "read": True}


# ------------------------------------------------------------------ HOI ingest: staffing request
def _notify_agencies(job: dict) -> int:
    d = mongo.db()
    today = _today().isoformat()
    n = 0
    for a in d.businesses.find({"type": "staffing_agency", "status": "active", "valid_until": {"$gte": today}}):
        a = mongo.clean(a)
        if not any(_matches(a, s, job["district"]) for s in job["skills"]):
            continue
        key_user = a.get("owner_user_id") or f"agency:{a['id']}"  # synthetic agencies have no account; keep the record anyway
        created = _notify(
            key_user,
            a["id"],
            "staffing_request",
            job["id"],
            f"{HOI_LABEL}: {job['openings']} x {SKILLS[job['skills'][0]]['label']}, {DISTRICTS[job['district']]['name']}",
            f"{job['business_name']} needs staff {job['season_from']} to {job['season_to']}. Respond from your dashboard.",
        )
        n += created
    return n


def ingest_request(business: dict, key_prefix: str, body: dict) -> dict:
    """Create or update the job post for one HOI roster shortage. Idempotent per (business, source_id)."""
    if registry.effective_status(business) != "active":
        raise Forbidden("This registration is not active, so it cannot post staffing requests. Renew first.")
    if body["source"] not in catalog.STAFFING_SOURCES:
        raise Invalid("Unknown source.")
    try:
        skill = _skill_key(body["skill"])
    except Invalid:
        if not body.get("department") or body["department"] == body["skill"]:
            raise
        skill = _skill_key(body["department"])
    district = _district_id(body.get("district"), business["district"])
    if district != business["district"]:
        raise Invalid("district must be the hotel's own district.")
    da, db = _dates(body["from"], body["to"], "Staffing window")
    today = _today()
    if db < today:
        raise Invalid("The staffing window has already ended.")
    if da > today + timedelta(days=180):
        raise Invalid("The staffing window starts more than 180 days from now.")
    source_id = (body.get("source_id") or f"{skill}:{district}:{da.isoformat()}:{db.isoformat()}").strip()[:80]
    shift = re.sub(r"\s+", " ", (body.get("shift_note") or "")).strip()
    d = mongo.db()
    key = {"business_id": business["id"], "staffing_request.source_id": source_id}
    existing = d.job_posts.find_one(key)
    label = SKILLS[skill]["label"]
    title = f"{label}: {body['openings']} needed ({da.strftime('%d %b')}-{db.strftime('%d %b')})"[:80]
    description = (
        f"{HOI_LABEL}: {business['name']} is short of {label.lower()} staff for its roster. "
        + (f"Shifts: {shift}. " if shift else "")
        + "Registered staffing agencies can respond from their dashboard; individual job seekers can apply here."
    )[:1000]
    closes_on = min(max(da, today), today + timedelta(days=180)).isoformat()
    now = mongo.now()
    if existing:
        existing = mongo.clean(existing)
        upd = {}
        for k, v in (
            ("openings", body["openings"]),
            ("season_from", da.isoformat()),
            ("season_to", db.isoformat()),
            ("description", description),
            ("title", title),
        ):
            if existing.get(k) != v:
                upd[k] = v
        if upd:
            upd.update(updated_at=now, closes_on=closes_on)
            d.job_posts.update_one({"id": existing["id"]}, {"$set": upd})
        job = mongo.clean(d.job_posts.find_one({"id": existing["id"]}))
        notified = _notify_agencies(job) if job["status"] == "open" else 0
        result = "updated" if upd else "unchanged"
    else:
        if d.job_posts.count_documents({"business_id": business["id"], "via_hoi": True, "status": "open"}) >= MAX_OPEN_HOI_REQUESTS:
            raise Conflict(f"At most {MAX_OPEN_HOI_REQUESTS} open staffing requests per business.")
        job = {
            "id": f"JOB-{mongo.next_seq('job'):06d}",
            "owner_user_id": business.get("owner_user_id"),
            "business_id": business["id"],
            "business_name": business["name"],
            "business_type": business["type"],
            "business_reg_no": business["reg_no"],
            "title": title,
            "skills": [skill],
            "district": district,
            "destination_id": business.get("destination_id"),
            "job_type": "seasonal",
            "season_from": da.isoformat(),
            "season_to": db.isoformat(),
            "pay_min": None,
            "pay_max": None,
            "accommodation": False,
            "food": False,
            "openings": body["openings"],
            "languages": [],
            "description": description,
            "closes_on": closes_on,
            "status": "open",
            "closed_reason": None,
            "closed_at": None,
            "via_hoi": True,
            "staffing_request": {"source": body["source"], "source_id": source_id, "shift_note": shift or None},
            "synthetic": False,
            "created_at": now,
            "updated_at": now,
        }
        d.job_posts.insert_one(job)
        job = mongo.clean(job)
        notified = _notify_agencies(job)
        result = "created"
    if result != "unchanged":
        mongo.audit(f"apikey:{key_prefix}", f"staffing_request.{result}", job["id"], source_id, district)
    return {
        "result": result,
        "job_id": job["id"],
        "business_id": business["id"],
        "source_id": source_id,
        "status": job["status"],
        "openings": job["openings"],
        "agencies_notified": notified,
        "agencies_matching": d.notifications.count_documents({"kind": "staffing_request", "job_id": job["id"]}),
        "label": HOI_LABEL,
    }


def candidate_matches(business: dict, skill_raw: str, limit: int = MATCH_PREVIEW_MAX) -> dict:
    """Count + anonymised previews of PUBLIC job-seeker profiles with this skill who prefer the hotel's district (or any
    district). Shows less than the signed-in candidate search: no display name, headline or bio (free text that may hold
    personal details), never phone or e-mail. Only an ACTIVE registration may ask (same rule as candidate search)."""
    if registry.effective_status(business) != "active":
        raise Forbidden("This registration is not active, so it cannot search candidates. Renew first.")
    skill = _skill_key(skill_raw)
    district = business["district"]
    flt = {"visibility": "public", "skill_keys": skill, "$or": [{"districts": district}, {"districts": {"$size": 0}}]}
    profs = [mongo.clean(p) for p in mongo.db().seeker_profiles.find(flt, {"phone": 0, "email": 0, "user_id": 0})]
    target = {"skills": [skill], "district": district}
    scored = sorted(((matching.score(target, p), p) for p in profs), key=lambda x: (-(x[0]["score"] or 0), x[1]["code"]))
    items = [
        {
            "code": p["code"],
            "skills": [{"label": SKILLS[s["key"]]["label"], "years": s.get("years", 0)} for s in p.get("skills", []) if s["key"] in SKILLS],
            "districts": [DISTRICTS[d]["name"] for d in p.get("districts", []) if d in DISTRICTS] or ["Any district"],
            "availability": JOB_TYPES.get(p.get("availability") or "", p.get("availability") or ""),
            "available_from": p.get("available_from"),
            "available_to": p.get("available_to"),
            "match": m["score"],
            "synthetic": bool(p.get("synthetic")),
            "open_path": f"#/business/hiring/candidates/{p['code']}",
        }
        for m, p in scored[: max(0, min(limit, MATCH_PREVIEW_MAX))]
    ]
    return {
        "skill": {"key": skill, "label": SKILLS[skill]["label"]},
        "district": {"id": district, "name": DISTRICTS[district]["name"]},
        "total": len(scored),
        "items": items,
        "search_path": f"#/business/hiring/candidates?skill={skill}&district={district}",
        "privacy": "Anonymised previews only. Contact details are shared only if the job seeker accepts your interest request on the portal.",
        "note": "Profiles marked synthetic are sample data.",
    }
