"""Hiring board: job-seeker profiles, job posts, applications, interest requests, shortlist and message threads.

Privacy by design (see CONSENT_NOTICE):
* Profiles have no gender, age/date of birth, religion, caste, marital/family status, photo or address fields
  (schemas reject them). Display name is free text; the UI recommends first name only.
* Phone and email are stored but never returned by public or candidate-search responses. A business sees them only
  for candidates who ACCEPTED that business's interest request (`_revealed`). Until then, talk via portal messages.
* Only businesses with an ACTIVE registration can post jobs, search candidates or send interest requests.
* `visibility: hidden` removes a profile from search; it stays visible only to businesses it applied to or that
  already have an interest request with it.
* Deleting a profile hard-deletes the profile, its applications, interest requests, shortlist entries and messages.
  The audit entry carries only the pseudonymous user id and candidate code, no personal data.
Scoping: seekers see only their own applications/interests/messages; businesses only their own posts, applicants,
sent interests and shortlist; officers get aggregates only (services/hiring_analytics.py).
"""

from __future__ import annotations

import re
import secrets
from datetime import date, timedelta

from pymongo.errors import DuplicateKeyError

from .. import catalog, mongo
from ..errors import Conflict, Forbidden, Invalid, NotFound
from ..seed.destinations import BY_ID_DEST
from ..seed.districts import BY_ID as DISTRICTS
from ..seed.skills import BY_KEY as SKILLS
from ..seed.skills import CATEGORIES, CERTIFICATION_SUGGESTIONS, JOB_TYPES, LANGUAGES
from ..seed.skills import SKILLS as SKILL_LIST
from . import matching, registry

PAGE_SIZE = 12
MAX_OPEN_JOBS = 20  # per business owner
CLOSES_MAX_DAYS = 180
CONSENT_VERSION = "2026-10-v1"
CONSENT_NOTICE = {
    "version": CONSENT_VERSION,
    "title": "Before you create your profile",
    "points": [
        "What employers see: your display name, headline, skills and years of experience, certificates (self-declared), "
        "languages, preferred districts, availability, expected pay and short bio. Only businesses with an active "
        "registration on this portal can search profiles; profiles are not on the open web.",
        "Your phone number and email are never shown publicly. A business sees them only after you accept its interest "
        "request. Until then you talk through portal messages.",
        "We never ask for your gender, age or date of birth, religion, caste, marital or family status, photo or address. "
        "Please do not put them in your bio either. We recommend using only your first name.",
        "You can hide your profile at any time (businesses you applied to can still see it), and delete it at any time: "
        "the profile, your applications, interest requests and messages are removed permanently.",
        "Certificates are self-declared; the portal does not check them.",
    ],
}
SYNTHETIC_CONTACT_NOTE = "Synthetic placeholder contact (demo data), not a real number."


# ------------------------------------------------------------------ vocabularies
def vocab() -> dict:
    return {
        "skills": [{"key": s["key"], "label": s["label"], "category": s["category"]} for s in SKILL_LIST],
        "skill_categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()],
        "job_types": [{"key": k, "label": v} for k, v in JOB_TYPES.items()],
        "languages": list(LANGUAGES),
        "certification_suggestions": list(CERTIFICATION_SUGGESTIONS),
        "application_statuses": list(catalog.JOB_APPLICATION_STATUSES),
        "interest_statuses": list(catalog.INTEREST_STATUSES),
        "consent_notice": CONSENT_NOTICE,
        "match": {"label": matching.CFG["label"], "weights": matching.CFG["weights"], "note": "Weights are ASSUMED; see hiring.yaml."},
        "page_size": PAGE_SIZE,
    }


def _today() -> str:
    return date.today().isoformat()


def _skill(k: str) -> dict:
    s = SKILLS[k]
    return {"key": k, "label": s["label"], "category": s["category"]}


def _check_dates(a: str | None, b: str | None, what: str) -> None:
    for v in (a, b):
        if v:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise Invalid(f"{what}: {v} is not a valid date.") from None
    if a and b and b < a:
        raise Invalid(f"{what}: the end date is before the start date.")


def _check_pay(lo: int | None, hi: int | None) -> None:
    if lo is not None and hi is not None and hi < lo:
        raise Invalid("Pay range: the maximum is below the minimum.")


# ------------------------------------------------------------------ profiles
def _clean_profile(data: dict, existing: dict | None = None) -> dict:
    out = dict(data)
    if "skills" in out and out["skills"] is not None:
        seen, skills = set(), []
        for s in out["skills"]:
            k = s["key"]
            if k not in SKILLS:
                raise Invalid(f"Unknown skill {k}. Pick from the list.")
            if k in seen:
                continue
            seen.add(k)
            skills.append({"key": k, "years": int(s.get("years") or 0)})
        out["skills"] = skills
        out["skill_keys"] = [s["key"] for s in skills]
    if "languages" in out and out["languages"] is not None:
        bad = [x for x in out["languages"] if x not in LANGUAGES]
        if bad:
            raise Invalid(f"Unknown language: {', '.join(bad)}. Use 'Other' for anything not listed.")
        out["languages"] = list(dict.fromkeys(out["languages"]))
    if "districts" in out and out["districts"] is not None:
        bad = [x for x in out["districts"] if x not in DISTRICTS]
        if bad:
            raise Invalid(f"Unknown district: {', '.join(bad)}.")
        out["districts"] = list(dict.fromkeys(out["districts"]))
    if "certifications" in out and out["certifications"] is not None:
        certs = []
        for c in out["certifications"]:
            c = re.sub(r"\s+", " ", str(c)).strip()[:80]
            if c and c not in certs:
                certs.append(c)
        out["certifications"] = certs
    for k in ("display_name", "headline", "bio"):
        if out.get(k) is not None:
            out[k] = re.sub(r"[ \t]+", " ", out[k]).strip()
    merged = {**(existing or {}), **out}
    _check_dates(merged.get("available_from"), merged.get("available_to"), "Availability")
    _check_pay(merged.get("pay_min"), merged.get("pay_max"))
    if not (merged.get("phone") or merged.get("email")):
        raise Invalid("Add a phone number or an email so employers you accept can contact you. They are never shown publicly.")
    return out


def profile_public(p: dict) -> dict:
    """What a business (or the officer analytics) may know about a candidate. Never contact details."""
    return {
        "code": p["code"],
        "display_name": p["display_name"],
        "headline": p["headline"],
        "skills": [{**_skill(s["key"]), "years": s.get("years", 0)} for s in p.get("skills", []) if s["key"] in SKILLS],
        "certifications": p.get("certifications", []),
        "certifications_note": "Self-declared, not verified by the portal.",
        "languages": p.get("languages", []),
        "districts": p.get("districts", []),
        "district_names": [DISTRICTS[d]["name"] for d in p.get("districts", []) if d in DISTRICTS],
        "any_district": not p.get("districts"),
        "availability": p["availability"],
        "availability_label": JOB_TYPES.get(p["availability"], p["availability"]),
        "available_from": p.get("available_from"),
        "available_to": p.get("available_to"),
        "pay_min": p.get("pay_min"),
        "pay_max": p.get("pay_max"),
        "bio": p.get("bio"),
        "updated_at": mongo.iso(p.get("updated_at")),
        "synthetic": bool(p.get("synthetic")),
    }


def profile_own(p: dict) -> dict:
    out = profile_public(p)
    out.update(
        visibility=p.get("visibility", "public"),
        phone=p.get("phone"),
        email=p.get("email"),
        consent={"version": p.get("consent", {}).get("version"), "at": mongo.iso(p.get("consent", {}).get("at"))},
        created_at=mongo.iso(p.get("created_at")),
    )
    return out


def own_profile_doc(user_id: str) -> dict | None:
    return mongo.clean(mongo.db().seeker_profiles.find_one({"user_id": user_id}))


def get_own(user_id: str) -> dict:
    p = own_profile_doc(user_id)
    return {"profile": profile_own(p) if p else None, "consent_notice": CONSENT_NOTICE}


def create_profile(user_id: str, data: dict) -> dict:
    if not data.pop("consent", False):
        raise Invalid("Please read the privacy notice and tick the consent box to create a profile.")
    d = mongo.db()
    if d.seeker_profiles.find_one({"user_id": user_id}, {"_id": 1}):
        raise Conflict("You already have a profile. Edit it instead.")
    doc = _clean_profile(data)
    now = mongo.now()
    doc.update(
        code=f"C-{mongo.next_seq('candidate'):04d}",
        user_id=user_id,
        consent={"version": CONSENT_VERSION, "at": now},
        synthetic=False,
        created_at=now,
        updated_at=now,
    )
    doc.setdefault("visibility", "public")
    try:
        d.seeker_profiles.insert_one(doc)
    except DuplicateKeyError:
        raise Conflict("You already have a profile. Edit it instead.") from None
    mongo.audit(f"seeker:{user_id}", "seeker.profile.created", doc["code"])
    return profile_own(mongo.clean(doc))


def update_profile(user_id: str, data: dict) -> dict:
    d = mongo.db()
    p = own_profile_doc(user_id)
    if not p:
        raise NotFound("You have no profile yet.")
    clean = _clean_profile(data, p)
    # Explicit nulls clear optional fields; required ones cannot be cleared.
    for k in ("display_name", "headline", "skills", "languages", "availability", "visibility"):
        if k in clean and clean[k] is None:
            clean.pop(k)
    clean["updated_at"] = mongo.now()
    d.seeker_profiles.update_one({"user_id": user_id}, {"$set": clean})
    if "visibility" in data and data["visibility"] and data["visibility"] != p.get("visibility"):
        mongo.audit(f"seeker:{user_id}", "seeker.profile.visibility", p["code"], data["visibility"])
    return profile_own(own_profile_doc(user_id))


def delete_profile(user_id: str) -> dict:
    """Hard delete: profile, own applications, interest requests, shortlist entries, messages of those threads."""
    d = mongo.db()
    p = own_profile_doc(user_id)
    if not p:
        raise NotFound("You have no profile.")
    code = p["code"]
    app_ids = [a["id"] for a in d.job_applications.find({"candidate_id": code}, {"id": 1})]
    int_ids = [i["id"] for i in d.interest_requests.find({"candidate_id": code}, {"id": 1})]
    n_msg = d.job_messages.delete_many({"thread_id": {"$in": app_ids + int_ids}}).deleted_count
    n_app = d.job_applications.delete_many({"candidate_id": code}).deleted_count
    n_int = d.interest_requests.delete_many({"candidate_id": code}).deleted_count
    d.job_shortlist.delete_many({"candidate_id": code})
    d.seeker_profiles.delete_one({"user_id": user_id})
    mongo.audit(f"seeker:{user_id}", "seeker.profile.deleted", code, f"applications={n_app} interests={n_int} messages={n_msg}")
    return {"deleted": True, "applications_removed": n_app, "interest_requests_removed": n_int, "messages_removed": n_msg}


def seeker_dashboard(user_id: str) -> dict:
    d = mongo.db()
    p = own_profile_doc(user_id)
    apps = list(d.job_applications.find({"seeker_user_id": user_id}, {"status": 1}))
    ints = list(d.interest_requests.find({"seeker_user_id": user_id}, {"status": 1}))
    by = {s: sum(1 for a in apps if a["status"] == s) for s in catalog.JOB_APPLICATION_STATUSES}
    return {
        "profile": profile_own(p) if p else None,
        "consent_notice": CONSENT_NOTICE,
        "summary": {
            "applications": len(apps),
            "applications_active": sum(by[s] for s in ("applied", "viewed", "shortlisted", "contacted")),
            "shortlisted": by["shortlisted"] + by["contacted"],
            "interests_pending": sum(1 for i in ints if i["status"] == "pending"),
            "interests_accepted": sum(1 for i in ints if i["status"] == "accepted"),
        },
        "applications_by_status": by,
    }


# ------------------------------------------------------------------ businesses and job posts
def _active_businesses(user_id: str) -> list[dict]:
    today = _today()
    out = []
    for b in mongo.db().businesses.find({"owner_user_id": user_id}).sort("name_lc", 1):
        if registry.effective_status(b, today) == "active":
            out.append(mongo.clean(b))
    return out


def require_active(user_id: str, business_id: str | None = None) -> dict:
    """The (given or first) business of this owner with an ACTIVE registration, else 403."""
    act = _active_businesses(user_id)
    if business_id:
        b = next((x for x in act if x["id"] == business_id), None)
        if not b:
            owned = mongo.db().businesses.find_one({"id": business_id, "owner_user_id": user_id}, {"_id": 1})
            if not owned:
                raise NotFound("Business not found in your account.")
            raise Forbidden("This business does not have an active registration. Only active registrations can hire on the portal.")
        return b
    if not act:
        raise Forbidden("Only businesses with an active registration can post jobs, search candidates or send interest requests.")
    return act[0]


def _season_months(j: dict) -> set[int]:
    f, t = j.get("season_from"), j.get("season_to")
    if not (f and t):
        return set(range(1, 13))
    a, b = date.fromisoformat(f), date.fromisoformat(t)
    months, cur = set(), date(a.year, a.month, 1)
    while cur <= b and len(months) < 12:
        months.add(cur.month)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return months


def job_public(j: dict) -> dict:
    dest = BY_ID_DEST.get(j.get("destination_id"))
    open_now = j["status"] == "open" and j["closes_on"] >= _today()
    return {
        "id": j["id"],
        "title": j["title"],
        "business_id": j["business_id"],
        "business_name": j["business_name"],
        "business_type": j.get("business_type"),
        "business_type_label": catalog.BUSINESS_TYPES.get(j.get("business_type"), ("",))[0] or None,
        "business_reg_no": j.get("business_reg_no"),
        "district": j["district"],
        "district_name": DISTRICTS[j["district"]]["name"],
        "destination_id": j.get("destination_id"),
        "destination_name": dest["name"] if dest else None,
        "skills": [_skill(k) for k in j["skills"] if k in SKILLS],
        "job_type": j["job_type"],
        "job_type_label": JOB_TYPES[j["job_type"]],
        "season_from": j.get("season_from"),
        "season_to": j.get("season_to"),
        "pay_min": j.get("pay_min"),
        "pay_max": j.get("pay_max"),
        "accommodation": bool(j.get("accommodation")),
        "food": bool(j.get("food")),
        "openings": j["openings"],
        "languages": j.get("languages", []),
        "description": j["description"],
        "closes_on": j["closes_on"],
        "posted_at": mongo.iso(j["created_at"]),
        "status": "open" if open_now else "closed",
        "closed_reason": j.get("closed_reason") if not open_now else None,
        "synthetic": bool(j.get("synthetic")),
    }


def _job_owner_view(j: dict) -> dict:
    out = job_public(j)
    apps = list(mongo.db().job_applications.find({"job_id": j["id"]}, {"status": 1}))
    out["applications"] = {s: sum(1 for a in apps if a["status"] == s) for s in catalog.JOB_APPLICATION_STATUSES}
    out["applications_total"] = sum(1 for a in apps if a["status"] != "withdrawn")
    out["applications_new"] = out["applications"]["applied"]
    out["closed_at"] = mongo.iso(j.get("closed_at"))
    return out


def create_job(user_id: str, actor: str, data: dict) -> dict:
    b = require_active(user_id, data.pop("business_id"))
    skills = list(dict.fromkeys(data["skills"]))
    bad = [k for k in skills if k not in SKILLS]
    if bad:
        raise Invalid(f"Unknown skill: {', '.join(bad)}.")
    district = data.get("district") or b["district"]
    if district not in DISTRICTS:
        raise Invalid("Unknown district.")
    dest = data.get("destination_id") or (b.get("destination_id") if district == b["district"] else None)
    if dest and (dest not in BY_ID_DEST or BY_ID_DEST[dest]["district"] != district):
        raise Invalid("That destination is not in the chosen district.")
    langs = [x for x in dict.fromkeys(data.get("languages") or []) if x in LANGUAGES]
    _check_dates(data.get("season_from"), data.get("season_to"), "Season")
    if data["job_type"] == "seasonal" and not (data.get("season_from") and data.get("season_to")):
        raise Invalid("Seasonal jobs need season start and end dates.")
    _check_pay(data.get("pay_min"), data.get("pay_max"))
    _check_dates(data["closes_on"], None, "Closes on")
    today = date.today()
    if not (today.isoformat() <= data["closes_on"] <= (today + timedelta(days=CLOSES_MAX_DAYS)).isoformat()):
        raise Invalid(f"'Closes on' must be between today and {CLOSES_MAX_DAYS} days from now.")
    d = mongo.db()
    if d.job_posts.count_documents({"owner_user_id": user_id, "status": "open"}) >= MAX_OPEN_JOBS:
        raise Conflict(f"At most {MAX_OPEN_JOBS} open job posts per account. Close one first.")
    now = mongo.now()
    doc = {
        "id": f"JOB-{mongo.next_seq('job'):06d}",
        "owner_user_id": user_id,
        "business_id": b["id"],
        "business_name": b["name"],
        "business_type": b["type"],
        "business_reg_no": b["reg_no"],
        "title": re.sub(r"\s+", " ", data["title"]).strip(),
        "skills": skills,
        "district": district,
        "destination_id": dest,
        "job_type": data["job_type"],
        "season_from": data.get("season_from"),
        "season_to": data.get("season_to"),
        "pay_min": data.get("pay_min"),
        "pay_max": data.get("pay_max"),
        "accommodation": bool(data.get("accommodation")),
        "food": bool(data.get("food")),
        "openings": data["openings"],
        "languages": langs,
        "description": data["description"].strip(),
        "closes_on": data["closes_on"],
        "status": "open",
        "closed_reason": None,
        "closed_at": None,
        "synthetic": False,
        "created_at": now,
        "updated_at": now,
    }
    d.job_posts.insert_one(doc)
    mongo.audit(actor, "job.posted", doc["id"], b["id"], district)
    return _job_owner_view(mongo.clean(doc))


def _own_job(user_id: str, job_id: str) -> dict:
    j = mongo.db().job_posts.find_one({"id": job_id, "owner_user_id": user_id})
    if not j:
        raise NotFound("Job post not found in your account.")
    return mongo.clean(j)


def my_jobs(user_id: str) -> dict:
    d = mongo.db()
    items = [_job_owner_view(mongo.clean(j)) for j in d.job_posts.find({"owner_user_id": user_id}).sort("created_at", -1)]
    ints = list(d.interest_requests.find({"owner_user_id": user_id}, {"status": 1}))
    active = _active_businesses(user_id)
    return {
        "items": items,
        "total": len(items),
        "can_hire": bool(active),
        "active_businesses": [
            {"id": b["id"], "name": b["name"], "district": b["district"], "destination_id": b.get("destination_id")} for b in active
        ],
        "summary": {
            "open_posts": sum(1 for j in items if j["status"] == "open"),
            "new_applications": sum(j["applications_new"] for j in items),
            "applications": sum(j["applications_total"] for j in items),
            "interests_pending": sum(1 for i in ints if i["status"] == "pending"),
            "interests_accepted": sum(1 for i in ints if i["status"] == "accepted"),
            "shortlisted": d.job_shortlist.count_documents({"owner_user_id": user_id}),
        },
    }


def update_job(user_id: str, job_id: str, data: dict, actor: str) -> dict:
    j = _own_job(user_id, job_id)
    upd: dict = {k: v for k, v in data.items() if v is not None and k not in ("status", "closed_reason")}
    if "closes_on" in upd:
        _check_dates(upd["closes_on"], None, "Closes on")
        today = date.today()
        if not (today.isoformat() <= upd["closes_on"] <= (today + timedelta(days=CLOSES_MAX_DAYS)).isoformat()):
            raise Invalid(f"'Closes on' must be between today and {CLOSES_MAX_DAYS} days from now.")
    status = data.get("status")
    if status == "closed" and j["status"] == "open":
        upd.update(status="closed", closed_reason=data.get("closed_reason") or "withdrawn", closed_at=mongo.now())
    elif status == "open" and j["status"] != "open":
        require_active(user_id, j["business_id"])
        if (upd.get("closes_on") or j["closes_on"]) < _today():
            raise Invalid("Set a new 'closes on' date to reopen this post.")
        upd.update(status="open", closed_reason=None, closed_at=None)
    if not upd:
        return _job_owner_view(j)
    upd["updated_at"] = mongo.now()
    mongo.db().job_posts.update_one({"id": job_id}, {"$set": upd})
    if "status" in upd:
        mongo.audit(actor, f"job.{upd['status']}", job_id, upd.get("closed_reason") or "", j["district"])
    return _job_owner_view(_own_job(user_id, job_id))


def list_jobs(
    *,
    skill: str | None = None,
    district: str | None = None,
    job_type: str | None = None,
    month: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
    seeker_user_id: str | None = None,
) -> dict:
    """Open jobs (public). A signed-in job seeker with a profile gets a match score per job, sorted by it."""
    f: dict = {"status": "open", "closes_on": {"$gte": _today()}}
    if skill:
        f["skills"] = skill
    if district:
        f["district"] = district
    if job_type:
        f["job_type"] = job_type
    jobs = [mongo.clean(j) for j in mongo.db().job_posts.find(f).sort("created_at", -1).limit(1000)]
    if month:
        jobs = [j for j in jobs if month in _season_months(j)]
    if q:
        toks = [t for t in re.split(r"\s+", q.lower().strip())[:6] if t]

        def hay(j: dict) -> str:
            labels = " ".join(SKILLS[k]["label"] for k in j["skills"] if k in SKILLS)
            return " ".join([j["title"], j["business_name"], DISTRICTS[j["district"]]["name"], labels]).lower()

        jobs = [j for j in jobs if all(t in hay(j) for t in toks)]
    prof = own_profile_doc(seeker_user_id) if seeker_user_id else None
    applied = set()
    if prof:
        applied = {a["job_id"] for a in mongo.db().job_applications.find({"seeker_user_id": seeker_user_id}, {"job_id": 1})}
    rows = []
    for j in jobs:
        out = job_public(j)
        if prof:
            out["match"] = matching.score(j, prof)
            out["applied"] = j["id"] in applied
        rows.append(out)
    if prof:
        rows.sort(key=lambda r: (-(r["match"]["score"] or 0), r["closes_on"], r["id"]))
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "openings": sum(r["openings"] for r in rows),
        "matched_to_profile": bool(prof),
    }


def get_job(job_id: str, seeker_user_id: str | None = None, owner_user_id: str | None = None) -> dict:
    j = mongo.db().job_posts.find_one({"id": job_id})
    if not j:
        raise NotFound("Job not found.")
    j = mongo.clean(j)
    out = _job_owner_view(j) if owner_user_id and j.get("owner_user_id") == owner_user_id else job_public(j)
    if seeker_user_id:
        prof = own_profile_doc(seeker_user_id)
        out["has_profile"] = bool(prof)
        if prof:
            out["match"] = matching.score(j, prof)
        a = mongo.db().job_applications.find_one({"job_id": job_id, "seeker_user_id": seeker_user_id})
        out["my_application"] = _app_seeker_view(mongo.clean(a), j) if a else None
    return out


# ------------------------------------------------------------------ applications
def _hist(status: str) -> dict:
    return {"status": status, "at": mongo.now()}


def _app_seeker_view(a: dict, job: dict | None = None) -> dict:
    job = job or mongo.clean(mongo.db().job_posts.find_one({"id": a["job_id"]}))
    return {
        "id": a["id"],
        "job": job_public(job) if job else None,
        "status": a["status"],
        "note": a.get("note"),
        "applied_at": mongo.iso(a["created_at"]),
        "updated_at": mongo.iso(a.get("updated_at")),
        "history": [{"status": h["status"], "at": mongo.iso(h["at"])} for h in a.get("history", [])],
        "can_message": a["status"] != "withdrawn",
        "messages": mongo.db().job_messages.count_documents({"thread_id": a["id"]}),
    }


def apply(user_id: str, job_id: str, note: str | None) -> dict:
    d = mongo.db()
    prof = own_profile_doc(user_id)
    if not prof:
        raise Conflict("Create your profile first, then apply.")
    j = d.job_posts.find_one({"id": job_id})
    if not j:
        raise NotFound("Job not found.")
    if j["status"] != "open" or j["closes_on"] < _today():
        raise Conflict("This job is closed.")
    now = mongo.now()
    doc = {
        "id": f"JA-{mongo.next_seq('job_application'):06d}",
        "job_id": job_id,
        "business_id": j["business_id"],
        "owner_user_id": j.get("owner_user_id"),
        "district": j["district"],
        "seeker_user_id": user_id,
        "candidate_id": prof["code"],
        "note": (note or "").strip() or None,
        "status": "applied",
        "history": [_hist("applied")],
        "synthetic": False,
        "created_at": now,
        "updated_at": now,
    }
    try:
        d.job_applications.insert_one(doc)
    except DuplicateKeyError:
        raise Conflict("You have already applied for this job.") from None
    mongo.audit(f"seeker:{user_id}", "job.applied", doc["id"], job_id, j["district"])
    return _app_seeker_view(mongo.clean(doc), mongo.clean(j))


def my_applications(user_id: str) -> dict:
    d = mongo.db()
    apps = [mongo.clean(a) for a in d.job_applications.find({"seeker_user_id": user_id}).sort("created_at", -1)]
    jobs = {j["id"]: mongo.clean(j) for j in d.job_posts.find({"id": {"$in": [a["job_id"] for a in apps]}})}
    items = [_app_seeker_view(a, jobs.get(a["job_id"])) for a in apps]
    return {"items": items, "total": len(items)}


def withdraw(user_id: str, app_id: str) -> dict:
    d = mongo.db()
    a = d.job_applications.find_one_and_update(
        {"id": app_id, "seeker_user_id": user_id, "status": {"$ne": "withdrawn"}},
        {"$set": {"status": "withdrawn", "updated_at": mongo.now()}, "$push": {"history": _hist("withdrawn")}},
    )
    if not a:
        if d.job_applications.find_one({"id": app_id, "seeker_user_id": user_id}):
            raise Conflict("Already withdrawn.")
        raise NotFound("Application not found.")
    return _app_seeker_view(mongo.clean(d.job_applications.find_one({"id": app_id})))


def _revealed_codes(owner_user_id: str, codes: list[str]) -> set[str]:
    return {
        i["candidate_id"]
        for i in mongo.db().interest_requests.find({"owner_user_id": owner_user_id, "candidate_id": {"$in": codes}, "status": "accepted"})
    }


def _contact(p: dict) -> dict:
    out = {"phone": p.get("phone"), "email": p.get("email"), "synthetic": bool(p.get("synthetic"))}
    if p.get("synthetic"):
        out["note"] = SYNTHETIC_CONTACT_NOTE
    return out


def _candidate_for_business(
    owner_user_id: str, p: dict, revealed: bool, *, interest: dict | None = None, shortlisted: bool | None = None
) -> dict:
    out = profile_public(p)
    out["contact"] = _contact(p) if revealed else None
    out["contact_visible"] = revealed
    if interest is not None or shortlisted is not None:
        out["interest"] = {"id": interest["id"], "status": interest["status"]} if interest else None
        out["shortlisted"] = bool(shortlisted)
    return out


def job_applications(user_id: str, job_id: str) -> dict:
    """Applicants for one of the caller's job posts. Listing marks new applications as `viewed`."""
    d = mongo.db()
    j = _own_job(user_id, job_id)
    d.job_applications.update_many(
        {"job_id": job_id, "status": "applied"},
        {"$set": {"status": "viewed", "updated_at": mongo.now()}, "$push": {"history": _hist("viewed")}},
    )
    apps = [mongo.clean(a) for a in d.job_applications.find({"job_id": job_id, "status": {"$ne": "withdrawn"}}).sort("created_at", 1)]
    codes = [a["candidate_id"] for a in apps]
    profs = {p["code"]: mongo.clean(p) for p in d.seeker_profiles.find({"code": {"$in": codes}})}
    revealed = _revealed_codes(user_id, codes)
    ints = {i["candidate_id"]: i for i in d.interest_requests.find({"owner_user_id": user_id, "candidate_id": {"$in": codes}})}
    sl = {s["candidate_id"] for s in d.job_shortlist.find({"owner_user_id": user_id, "candidate_id": {"$in": codes}})}
    items = []
    for a in apps:
        p = profs.get(a["candidate_id"])
        if not p:
            continue
        items.append(
            {
                "id": a["id"],
                "status": a["status"],
                "note": a.get("note"),
                "applied_at": mongo.iso(a["created_at"]),
                "history": [{"status": h["status"], "at": mongo.iso(h["at"])} for h in a.get("history", [])],
                "candidate": _candidate_for_business(
                    user_id, p, a["candidate_id"] in revealed, interest=ints.get(a["candidate_id"]), shortlisted=a["candidate_id"] in sl
                ),
                "match": matching.score(j, p),
                "messages": d.job_messages.count_documents({"thread_id": a["id"]}),
                "next_statuses": list(catalog.JOB_APPLICATION_TRANSITIONS.get(a["status"], ())),
            }
        )
    items.sort(key=lambda x: (-(x["match"]["score"] or 0), x["applied_at"]))
    return {"job": _job_owner_view(_own_job(user_id, job_id)), "items": items, "total": len(items)}


def set_application_status(user_id: str, app_id: str, status: str, actor: str) -> dict:
    d = mongo.db()
    a = d.job_applications.find_one({"id": app_id, "owner_user_id": user_id})
    if not a:
        raise NotFound("Application not found for your job posts.")
    allowed = catalog.JOB_APPLICATION_TRANSITIONS.get(a["status"], ())
    if status not in allowed:
        raise Conflict(f"Cannot move an application from {a['status'].replace('_', ' ')} to {status.replace('_', ' ')}.")
    r = d.job_applications.update_one(
        {"id": app_id, "status": a["status"]},
        {"$set": {"status": status, "updated_at": mongo.now()}, "$push": {"history": _hist(status)}},
    )
    if not r.matched_count:
        raise Conflict("The application changed meanwhile. Reload and try again.")
    mongo.audit(actor, "job.application." + status, app_id, a["job_id"], a.get("district"))
    return {"id": app_id, "status": status, "next_statuses": list(catalog.JOB_APPLICATION_TRANSITIONS.get(status, ()))}


# ------------------------------------------------------------------ candidates (business side)
def _can_view(owner_user_id: str, p: dict) -> bool:
    if p.get("visibility", "public") == "public":
        return True
    d = mongo.db()
    return bool(
        d.job_applications.find_one({"owner_user_id": owner_user_id, "candidate_id": p["code"], "status": {"$ne": "withdrawn"}}, {"_id": 1})
        or d.interest_requests.find_one({"owner_user_id": owner_user_id, "candidate_id": p["code"]}, {"_id": 1})
    )


def _available_in(p: dict, a: str | None, b: str | None) -> bool:
    pf, pt = p.get("available_from"), p.get("available_to")
    if b and pf and pf > b:
        return False
    return not (a and pt and pt < a)


def search_candidates(
    user_id: str,
    *,
    skill: str | None = None,
    district: str | None = None,
    available_from: str | None = None,
    available_to: str | None = None,
    exp_min: int | None = None,
    language: str | None = None,
    job_id: str | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict:
    require_active(user_id)
    _check_dates(available_from, available_to, "Availability window")
    if skill and skill not in SKILLS:
        raise Invalid("Unknown skill.")
    if district and district not in DISTRICTS:
        raise Invalid("Unknown district.")
    d = mongo.db()
    f: dict = {"visibility": "public"}
    if skill:
        f["skill_keys"] = skill
    if language:
        f["languages"] = language
    if district:
        f["$or"] = [{"districts": district}, {"districts": {"$size": 0}}]
    profs = [mongo.clean(p) for p in d.seeker_profiles.find(f, {"phone": 0, "email": 0, "user_id": 0})]
    if exp_min:

        def yrs(p: dict) -> int:
            ys = [s.get("years", 0) for s in p.get("skills", []) if not skill or s["key"] == skill]
            return max(ys) if ys else 0

        profs = [p for p in profs if yrs(p) >= exp_min]
    if available_from or available_to:
        profs = [p for p in profs if _available_in(p, available_from, available_to)]
    job = _own_job(user_id, job_id) if job_id else None
    target = job or {
        "skills": [skill] if skill else [],
        "district": district,
        "season_from": available_from if available_from and available_to else None,
        "season_to": available_to if available_from and available_to else None,
        "languages": [language] if language else [],
    }
    scored = [(matching.score(target, p), p) for p in profs]
    scored.sort(key=lambda x: (-(x[0]["score"] if x[0]["score"] is not None else -1), x[1]["code"]))
    total = len(scored)
    start = (page - 1) * page_size
    window = scored[start : start + page_size]
    codes = [p["code"] for _, p in window]
    ints = {i["candidate_id"]: i for i in d.interest_requests.find({"owner_user_id": user_id, "candidate_id": {"$in": codes}})}
    sl = {s["candidate_id"] for s in d.job_shortlist.find({"owner_user_id": user_id, "candidate_id": {"$in": codes}})}
    items = []
    for m, p in window:
        c = _candidate_for_business(user_id, p, False, interest=ints.get(p["code"]), shortlisted=p["code"] in sl)
        c.pop("contact")  # never in search results, even after acceptance (open the candidate page instead)
        c.pop("contact_visible")
        c["match"] = m
        items.append(c)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "matched_against": {"job_id": job["id"], "title": job["title"]} if job else ("filters" if any(target.values()) else None),
    }


def _profile_by_code(code: str) -> dict:
    p = mongo.db().seeker_profiles.find_one({"code": code})
    if not p:
        raise NotFound("Candidate not found.")
    return mongo.clean(p)


def candidate_detail(user_id: str, code: str, job_id: str | None = None) -> dict:
    require_active(user_id)
    p = _profile_by_code(code)
    if not _can_view(user_id, p):
        raise NotFound("Candidate not found.")
    d = mongo.db()
    interest = d.interest_requests.find_one({"owner_user_id": user_id, "candidate_id": code})
    revealed = bool(interest and interest["status"] == "accepted")
    out = _candidate_for_business(
        user_id,
        p,
        revealed,
        interest=mongo.clean(interest),
        shortlisted=bool(d.job_shortlist.find_one({"owner_user_id": user_id, "candidate_id": code})),
    )
    if interest:
        out["interest"].update(created_at=mongo.iso(interest["created_at"]), can_message=interest["status"] == "accepted")
    out["applications"] = [
        {"id": a["id"], "job_id": a["job_id"], "status": a["status"]}
        for a in d.job_applications.find({"owner_user_id": user_id, "candidate_id": code, "status": {"$ne": "withdrawn"}})
    ]
    if job_id:
        out["match"] = matching.score(_own_job(user_id, job_id), p)
    return out


def send_interest(user_id: str, code: str, data: dict, actor: str) -> dict:
    d = mongo.db()
    job = _own_job(user_id, data["job_id"]) if data.get("job_id") else None
    b = require_active(user_id, data.get("business_id") or (job["business_id"] if job else None))
    p = _profile_by_code(code)
    if not _can_view(user_id, p):
        raise NotFound("Candidate not found.")
    now = mongo.now()
    doc = {
        "id": f"INT-{mongo.next_seq('interest'):06d}",
        "owner_user_id": user_id,
        "business_id": b["id"],
        "business_name": b["name"],
        "business_type": b["type"],
        "district": b["district"],
        "candidate_id": code,
        "seeker_user_id": p.get("user_id"),
        "job_id": job["id"] if job else None,
        "message": (data.get("message") or "").strip() or None,
        "status": "pending",
        "synthetic": False,
        "created_at": now,
        "responded_at": None,
    }
    try:
        d.interest_requests.insert_one(doc)
    except DuplicateKeyError:
        raise Conflict("You have already sent this candidate an interest request.") from None
    mongo.audit(actor, "job.interest.sent", doc["id"], code, b["district"])
    return _interest_business_view(mongo.clean(doc), p)


def _interest_business_view(i: dict, p: dict | None) -> dict:
    job = mongo.db().job_posts.find_one({"id": i["job_id"]}) if i.get("job_id") else None
    revealed = i["status"] == "accepted" and p is not None
    return {
        "id": i["id"],
        "status": i["status"],
        "message": i.get("message"),
        "business_id": i["business_id"],
        "business_name": i["business_name"],
        "job": {"id": job["id"], "title": job["title"]} if job else None,
        "created_at": mongo.iso(i["created_at"]),
        "responded_at": mongo.iso(i.get("responded_at")),
        "candidate": _candidate_for_business(i["owner_user_id"], p, revealed) if p else None,
        "can_message": i["status"] == "accepted",
        "messages": mongo.db().job_messages.count_documents({"thread_id": i["id"]}),
    }


def business_interests(user_id: str) -> dict:
    d = mongo.db()
    ints = [mongo.clean(i) for i in d.interest_requests.find({"owner_user_id": user_id}).sort("created_at", -1)]
    profs = {p["code"]: mongo.clean(p) for p in d.seeker_profiles.find({"code": {"$in": [i["candidate_id"] for i in ints]}})}
    items = [_interest_business_view(i, profs.get(i["candidate_id"])) for i in ints]
    return {
        "items": items,
        "total": len(items),
        "counts": {s: sum(1 for i in items if i["status"] == s) for s in catalog.INTEREST_STATUSES},
    }


def _interest_seeker_view(i: dict) -> dict:
    job = mongo.db().job_posts.find_one({"id": i["job_id"]}) if i.get("job_id") else None
    return {
        "id": i["id"],
        "status": i["status"],
        "message": i.get("message"),
        "business_id": i["business_id"],
        "business_name": i["business_name"],
        "business_type_label": catalog.BUSINESS_TYPES.get(i.get("business_type"), ("",))[0] or None,
        "district_name": DISTRICTS[i["district"]]["name"] if i.get("district") in DISTRICTS else None,
        "job": job_public(mongo.clean(job)) if job else None,
        "created_at": mongo.iso(i["created_at"]),
        "responded_at": mongo.iso(i.get("responded_at")),
        "can_message": i["status"] == "accepted",
        "messages": mongo.db().job_messages.count_documents({"thread_id": i["id"]}),
        "accept_note": "Accepting shares your phone and email with this business only.",
    }


def seeker_interests(user_id: str) -> dict:
    items = [
        _interest_seeker_view(mongo.clean(i)) for i in mongo.db().interest_requests.find({"seeker_user_id": user_id}).sort("created_at", -1)
    ]
    return {"items": items, "total": len(items), "pending": sum(1 for i in items if i["status"] == "pending")}


def decide_interest(user_id: str, interest_id: str, action: str) -> dict:
    d = mongo.db()
    status = "accepted" if action == "accept" else "declined"
    i = d.interest_requests.find_one_and_update(
        {"id": interest_id, "seeker_user_id": user_id, "status": "pending"},
        {"$set": {"status": status, "responded_at": mongo.now()}},
    )
    if not i:
        if d.interest_requests.find_one({"id": interest_id, "seeker_user_id": user_id}):
            raise Conflict("You have already answered this request.")
        raise NotFound("Interest request not found.")
    mongo.audit(f"seeker:{user_id}", f"job.interest.{status}", interest_id, "", i.get("district"))
    return _interest_seeker_view(mongo.clean(d.interest_requests.find_one({"id": interest_id})))


# ------------------------------------------------------------------ shortlist
def shortlist_add(user_id: str, code: str) -> dict:
    require_active(user_id)
    p = _profile_by_code(code)
    if not _can_view(user_id, p):
        raise NotFound("Candidate not found.")
    mongo.db().job_shortlist.update_one(
        {"owner_user_id": user_id, "candidate_id": code}, {"$setOnInsert": {"created_at": mongo.now()}}, upsert=True
    )
    return {"candidate_id": code, "shortlisted": True}


def shortlist_remove(user_id: str, code: str) -> dict:
    mongo.db().job_shortlist.delete_one({"owner_user_id": user_id, "candidate_id": code})
    return {"candidate_id": code, "shortlisted": False}


def shortlist(user_id: str) -> dict:
    d = mongo.db()
    rows = list(d.job_shortlist.find({"owner_user_id": user_id}).sort("created_at", -1))
    codes = [r["candidate_id"] for r in rows]
    profs = {p["code"]: mongo.clean(p) for p in d.seeker_profiles.find({"code": {"$in": codes}})}
    revealed = _revealed_codes(user_id, codes)
    ints = {i["candidate_id"]: mongo.clean(i) for i in d.interest_requests.find({"owner_user_id": user_id, "candidate_id": {"$in": codes}})}
    items = []
    for r in rows:
        p = profs.get(r["candidate_id"])
        if p and _can_view(user_id, p):
            c = _candidate_for_business(user_id, p, r["candidate_id"] in revealed, interest=ints.get(r["candidate_id"]), shortlisted=True)
            c["shortlisted_at"] = mongo.iso(r["created_at"])
            items.append(c)
    return {"items": items, "total": len(items)}


# ------------------------------------------------------------------ message threads (application or interest)
def _thread_parent(thread_id: str, user_id: str, role: str) -> tuple[str, dict]:
    d = mongo.db()
    kind = "application" if thread_id.startswith("JA-") else "interest" if thread_id.startswith("INT-") else None
    if not kind:
        raise NotFound("Conversation not found.")
    col = d.job_applications if kind == "application" else d.interest_requests
    party = {"seeker_user_id": user_id} if role == "job_seeker" else {"owner_user_id": user_id} if role == "business" else None
    if party is None:
        raise NotFound("Conversation not found.")
    parent = col.find_one({"id": thread_id, **party})
    if not parent:
        raise NotFound("Conversation not found.")
    return kind, mongo.clean(parent)


def _thread_meta(kind: str, parent: dict, role: str) -> dict:
    d = mongo.db()
    job = d.job_posts.find_one({"id": parent.get("job_id")}) if parent.get("job_id") else None
    biz_name = parent.get("business_name") or (job["business_name"] if job else None)
    p = d.seeker_profiles.find_one({"code": parent["candidate_id"]}, {"display_name": 1, "code": 1})
    can = parent["status"] != "withdrawn" if kind == "application" else parent["status"] == "accepted"
    return {
        "id": parent["id"],
        "kind": kind,
        "status": parent["status"],
        "job": {"id": job["id"], "title": job["title"]} if job else None,
        "business_name": biz_name,
        "candidate": {"code": parent["candidate_id"], "display_name": p["display_name"] if p else None},
        "other_party": (biz_name or "Business") if role == "job_seeker" else (p["display_name"] if p else parent["candidate_id"]),
        "can_send": can,
        "note": "Text only, up to 1000 characters. Visible only to you and the other party. Do not share bank or ID details.",
    }


def thread(thread_id: str, user_id: str, role: str) -> dict:
    kind, parent = _thread_parent(thread_id, user_id, role)
    msgs = [
        {
            "id": m["id"],
            "from": m["sender_role"],
            "mine": m["sender_user_id"] == user_id,
            "text": m["text"],
            "at": mongo.iso(m["created_at"]),
        }
        for m in mongo.db().job_messages.find({"thread_id": thread_id}).sort("created_at", 1).limit(300)
    ]
    return {"thread": _thread_meta(kind, parent, role), "items": msgs, "total": len(msgs)}


def post_message(thread_id: str, user_id: str, role: str, text: str) -> dict:
    kind, parent = _thread_parent(thread_id, user_id, role)
    meta = _thread_meta(kind, parent, role)
    if not meta["can_send"]:
        raise Conflict(
            "Messages open once the candidate accepts the interest request." if kind == "interest" else "This application was withdrawn."
        )
    text = text.strip()
    if not text:
        raise Invalid("Write a message first.")
    doc = {
        "id": "msg_" + secrets.token_hex(6),
        "thread_id": thread_id,
        "sender_role": role,
        "sender_user_id": user_id,
        "text": text,
        "created_at": mongo.now(),
    }
    mongo.db().job_messages.insert_one(doc)
    return {"id": doc["id"], "from": role, "mine": True, "text": text, "at": mongo.iso(doc["created_at"])}
