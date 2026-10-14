"""Staffing requests: when a week's roster is short, the hotel asks the tourism portal's staffing partners for extra hands.

Flow: create (stored first, status "pending_send") -> forward to the portal (portal_client.send) -> "sent" with the portal's
reference, or stays "pending_send" with a plain error and can be retried (POST /staffing/requests/{id}/send).
No personal data: department / skill, dates, number of openings and a short note (phone numbers / e-mails masked).
The property's portal API key is read at send time and never stored on the request, logged or returned.

Retention cover (someone's chance of leaving is HIGH, from the attrition model on SYNTHETIC data):
  find_cover      asks the portal how many job seekers fit that person's role in the hotel's district (count + anonymised
                  previews; contact only through the portal, where the job seeker decides).
  post_cover_job  when nobody fits, ONE click by the owner posts a job via the same staffing request flow. Idempotent: while a
                  cover post for that person is open (its window has not ended) a repeat returns it instead of posting again.
  The post never says why: the note is a neutral "planning ahead" line; the employee id stays on the hotel's own record.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from .. import mongo
from . import portal_client, tenants
from .errors import Invalid, NotFound

STATUSES = ("pending_send", "sent")
MAX_DAYS = 31
# The tourism portal's own limits (portal/hoi_portal: StaffingRequestIn and services/staffing.ingest_request). A request outside
# them is refused by the portal with HTTP 422, so it is refused here first, with the reason, before anything is saved.
PORTAL_MAX_LEAD_DAYS = 180  # the window must start within 180 days
PORTAL_SKILL_MAX = 40  # characters of `skill`
PORTAL_NOTE_MAX = 300  # characters of `note`
_SKILL_KEY = re.compile(r"^[a-z][a-z_]{1,39}$")


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
    rid: str | None = None,
    for_employee: str | None = None,
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
    today = date.today()
    if d1 < today:
        raise Invalid("These dates are already over. Choose dates from today on.")
    if d0 > today + timedelta(days=PORTAL_MAX_LEAD_DAYS):
        raise Invalid(f"The tourism portal takes requests that start within {PORTAL_MAX_LEAD_DAYS} days. Choose earlier dates.")
    doc = {
        "id": rid or mongo.new_id("stf"),
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
    if for_employee:
        doc["for_employee"] = for_employee  # hotel-side only: never sent to the portal
    try:
        mongo.col("staffing_requests").insert_one(doc)
    except DuplicateKeyError:  # the same deterministic id twice (a double click): send / return the first one
        return send(tid, doc["id"], actor)
    tenants.audit(tid, actor, "staffing.requested", f"{doc['id']} {department} x{openings} {date_from}..{date_to}")
    return send(tid, doc["id"], actor)


def _raw(tid: str, rid: str) -> dict:
    r = mongo.col("staffing_requests").find_one({"tenant_id": tid, "id": rid})
    if not r:
        raise NotFound("Staffing request not found.")
    return r


def payload(r: dict) -> dict:
    """The exact body the portal accepts: {external_id, department, skill, date_from, date_to, openings, note}.

    `skill` must be a short key (the portal maps HOI department names and falls back to `department` for an unknown key),
    so free text typed by the owner ("room cleaning, tandoor") goes into the note instead, and the skill becomes the
    department's portal key. The note is cut to the portal's 300 characters (contract test: portal/tests/test_hoi_contract.py)."""
    free = " ".join((r.get("skill") or "").split())
    note = r.get("note") or ""
    if _SKILL_KEY.match(free):
        skill = free
    else:
        skill = portal_skill(r["department"]) or r["department"]
        if free:
            note = f"Skill: {free}. {note}".strip()
    return {
        "external_id": r["id"],
        "department": r["department"],
        "skill": skill[:PORTAL_SKILL_MAX],
        "date_from": r["date_from"],
        "date_to": r["date_to"],
        "openings": r["openings"],
        "note": note[:PORTAL_NOTE_MAX],
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
            ref = res.get("id") or res.get("job_id") or res.get("request_id") or res.get("reference")
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


# ------------------------------------------------------------------ retention cover (high chance of leaving)
# HOI department -> tourism-portal skill key (the portal's hiring vocabulary, GET /api/v1/jobs/meta). ASSUMED mapping.
PORTAL_SKILL = {
    "housekeeping": "housekeeping",
    "front_office": "front_office",
    "fnb_service": "fb_service",
    "food_beverage": "fb_service",
    "kitchen": "cook_indian",
    "maintenance": "maintenance",
    "security": "security_guard",
}
COVER_DAYS = 30  # the cover post asks for someone within the next 30 days (one request covers at most MAX_DAYS)
COVER_NOTE = "Planning ahead: one more person for the {dept} team."
PORTAL_NAME = "Uttarakhand Travel Guide"
CANDIDATE_FIELDS = ("code", "skills", "districts", "availability", "available_from", "available_to", "match", "synthetic")


def portal_skill(department: str, role_title: str = "") -> str | None:
    if department == "kitchen" and "helper" in (role_title or "").lower():
        return "kitchen_helper"
    return PORTAL_SKILL.get(department)


def staff_member(tid: str, employee_id: str) -> dict:
    s = mongo.col("staff").find_one({"tenant_id": tid, "employee_id": employee_id.strip().upper()}, {"_id": 0})
    if not s:
        raise NotFound("No staff member with this id.")
    return s


def _cover_property(tid: str, employee_id: str, property_id: str | None) -> dict:
    if property_id:
        return tenants.get_property(tid, property_id)
    prop = tenants.property_of_staff(tid, employee_id)
    if not prop:
        raise NotFound("This hotel group has no property yet.")
    return prop


def open_cover(tid: str, property_id: str, employee_id: str) -> dict | None:
    """The newest cover post for this person whose window has not ended yet."""
    r = mongo.col("staffing_requests").find_one(
        {
            "tenant_id": tid,
            "property_id": property_id,
            "source": "retention",
            "for_employee": employee_id,
            "date_to": {"$gte": date.today().isoformat()},
        },
        sort=[("created_at", DESCENDING), ("_id", DESCENDING)],
    )
    return _out(r) if r else None


def _job_view(r: dict | None) -> dict | None:
    if not r:
        return None
    ref = r.get("portal_ref")
    return {
        "id": r["id"],
        "status": r["status"],
        "department": r["department"],
        "skill": r.get("skill") or "",
        "date_from": r["date_from"],
        "date_to": r["date_to"],
        "portal_job_id": ref,
        "job_url": portal_client.job_url(ref) if ref and r["status"] == "sent" else None,
        "last_error": r.get("last_error"),
    }


def find_cover(tid: str, actor: str, employee_id: str, property_id: str | None = None) -> dict:
    """Ask the portal who could cover this person's role. Never raises for portal trouble: `status` says what happened.

    status: matches (n > 0) | no_matches | no_key (no portal API key saved) | no_skill (role not on the portal) | error"""
    s = staff_member(tid, employee_id)
    emp = s["employee_id"]
    prop = _cover_property(tid, emp, property_id)
    skill = portal_skill(s["department"], s.get("role_title", ""))
    out: dict = {
        "employee_id": emp,
        "department": s["department"],
        "role_title": s.get("role_title") or "",
        "property_id": prop["id"],
        "skill": skill,
        "portal_name": PORTAL_NAME,
        "portal_url": portal_client.base_url(),
        "matches": 0,
        "candidates": [],
        "search_url": None,
        "job": _job_view(open_cover(tid, prop["id"], emp)),
        "privacy": "Anonymised profiles only. To contact someone, open them on the portal and send an interest request; "
        "they decide whether to share their contact details.",
        "synthetic": True,
    }
    if not skill:
        return {**out, "status": "no_skill", "message": "This role is not on the job portal's list, so it cannot be searched."}
    key = tenants.portal_key(tid, prop["id"])
    if not key:
        return {**out, "status": "no_key", "message": "No tourism-portal API key is saved for this property (Settings > This property)."}
    try:
        res = portal_client.candidate_matches(skill, key)
    except portal_client.PortalError as e:
        return {**out, "status": "error", "message": e.message[:300]}
    items = [i for i in res.get("items") or [] if isinstance(i, dict)]
    out["candidates"] = [
        {**{k: i.get(k) for k in CANDIDATE_FIELDS}, "open_url": portal_client.page_url(str(i.get("open_path") or "#/jobs/hire"))}
        for i in items[:5]
    ]
    out["matches"] = int(res.get("total") or 0)
    if res.get("search_path"):
        out["search_url"] = portal_client.page_url(str(res["search_path"]))
    tenants.audit(tid, actor, "retention.cover_checked", f"{emp} {skill} matches={out['matches']}")
    n = out["matches"]
    if n:
        return {**out, "status": "matches", "message": f"{n} job seeker{'s' if n != 1 else ''} on the {PORTAL_NAME} could fit this role."}
    return {**out, "status": "no_matches", "message": f"No one on the {PORTAL_NAME} fits this role right now. You can post a job."}


def post_cover_job(tid: str, actor: str, employee_id: str, property_id: str | None = None) -> dict:
    """Post (once) a job on the portal for this person's role. A repeat while that post is open returns it (created False)."""
    s = staff_member(tid, employee_id)
    emp = s["employee_id"]
    prop = _cover_property(tid, emp, property_id)
    skill = portal_skill(s["department"], s.get("role_title", ""))
    if not skill:
        raise Invalid("This role is not on the job portal's list, so no job can be posted for it.")
    existing = open_cover(tid, prop["id"], emp)
    if existing:
        r = send(tid, existing["id"], actor) if existing["status"] == "pending_send" else existing
        created = False
    else:
        d0 = date.today()
        r = create(
            tid,
            actor,
            department=s["department"],
            skill=skill,
            date_from=d0.isoformat(),
            date_to=(d0 + timedelta(days=COVER_DAYS)).isoformat(),
            openings=1,
            note=COVER_NOTE.format(dept=s["department"].replace("_", " ")),
            property_id=prop["id"],
            source="retention",
            rid=f"stf_ret_{prop['id']}_{emp}_{d0.isoformat()}",
            for_employee=emp,
        )
        created = True
    job = _job_view(r)
    if job and job["status"] == "sent":
        msg = f"Job posted on the {PORTAL_NAME}." if created else f"A job for this role is already on the {PORTAL_NAME}."
    else:
        msg = "The job is saved but not on the portal yet: " + ((job or {}).get("last_error") or "try again later.")
    return {"created": created, "job": job, "message": msg, "portal_name": PORTAL_NAME}
