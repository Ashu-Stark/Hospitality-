"""Accounts: create, authenticate (with lockout), redeem invites, enable/disable, preferences."""

from __future__ import annotations

import secrets
from datetime import UTC, timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .. import mongo, security
from . import tenants
from .errors import Invalid, NotFound, Unauthorized

ROLES = {
    "platform_admin": "Platform admin (HOI staff)",
    "owner": "Owner / GM",
    "hr": "HR",
    "dept_head": "Department head",
    "storekeeper": "Storekeeper",
    "worker": "Employee",
}
MAX_FAILED, LOCK_MINUTES = 5, 5
PUBLIC_FIELDS = ("id", "tenant_id", "username", "role", "employee_id", "active", "created_at", "last_login")


def public(u: dict) -> dict:
    out = {k: mongo.iso(u.get(k)) for k in PUBLIC_FIELDS}
    out["active"] = bool(out["active"])
    out["prefs"] = mongo.from_pairs(u.get("prefs"))
    return out


def _raw(flt: dict) -> dict | None:
    return mongo.col("users").find_one(flt)


def get(uid: str) -> dict:
    r = _raw({"id": uid})
    if not r:
        raise NotFound("User not found")
    return mongo.clean(r)


def by_username(username: str) -> dict | None:
    """Usernames are unique across the platform (case-insensitive), so this lookup is not tenant-scoped."""
    r = _raw({"_username_lc": username.strip().lower()})
    return get(r["id"]) if r else None


def create(username: str, password: str, role: str, tenant_id: str | None, employee_id: str | None = None) -> dict:
    if role not in ROLES:
        raise Invalid(f"Unknown role {role}")
    if role != "platform_admin" and not tenant_id:
        raise Invalid("Hotel users need a tenant.")
    if len(password) < 6:
        raise Invalid("Password/PIN must be at least 6 characters.")
    username = username.strip()
    if not username:
        raise Invalid("Username is required.")
    pw_hash, salt = security.hash_password(password)
    uid = mongo.new_id("usr")
    doc = {
        "id": uid,
        "tenant_id": tenant_id,
        "username": username,
        "_username_lc": username.lower(),
        "role": role,
        "employee_id": employee_id,
        "pw_hash": pw_hash,
        "salt": salt,
        "failed": 0,
        "locked_until": None,
        "active": 1,
        "prefs": [],
        "created_at": mongo.now(),
        "last_login": None,
    }
    try:
        mongo.col("users").insert_one(doc)  # the unique index on _username_lc makes this race-free
    except DuplicateKeyError:
        raise Invalid("That username is taken.") from None
    tenants.audit(tenant_id, username, "user.created", f"role={role}")
    return get(uid)


def authenticate(username: str, password: str) -> dict:
    u = _raw({"_username_lc": username.strip().lower()})
    if not u:
        security.burn_time(password)
        raise Unauthorized("Wrong username or password.")
    if not u["active"]:
        raise Unauthorized("This account is disabled.")
    locked = u.get("locked_until")
    if locked and (locked if locked.tzinfo else locked.replace(tzinfo=UTC)) > mongo.now():
        raise Unauthorized("Too many failed attempts. Try again in a few minutes.")
    if not security.verify_password(password, u["pw_hash"], u["salt"]):
        after = mongo.col("users").find_one_and_update({"id": u["id"]}, {"$inc": {"failed": 1}}, return_document=ReturnDocument.AFTER)
        failed = int(after["failed"])
        lock = failed >= MAX_FAILED
        if lock:
            mongo.col("users").update_one(
                {"id": u["id"]}, {"$set": {"failed": 0, "locked_until": mongo.now() + timedelta(minutes=LOCK_MINUTES)}}
            )
        tenants.audit(u["tenant_id"], u["username"], "login.failed", "locked" if lock else f"attempt {failed}")
        raise Unauthorized("Wrong username or password.")
    check_tenant_active(u)
    mongo.col("users").update_one({"id": u["id"]}, {"$set": {"failed": 0, "locked_until": None, "last_login": mongo.now()}})
    tenants.audit(u["tenant_id"], u["username"], "login.ok")
    return get(u["id"])


def check_tenant_active(u: dict) -> None:
    if u.get("tenant_id"):
        t = mongo.col("tenants").find_one({"id": u["tenant_id"]}, {"status": 1})
        if not t or t["status"] == "suspended":
            raise Unauthorized("This hotel's workspace is suspended. Contact HOI support.")


def redeem_invite(code: str, username: str, password: str, employee_id: str | None) -> dict:
    inv = mongo.col("invites").find_one({"code": code.strip().upper()})
    if not inv:
        raise Invalid("Invite code not found or already used.")
    if inv["role"] == "worker" and not (employee_id or "").strip():
        raise Invalid("Employees must enter their employee ID.")
    # Claim the invite atomically (single use), then create the account; put the invite back if that fails.
    claimed = mongo.col("invites").find_one_and_delete({"code": inv["code"]})
    if not claimed:
        raise Invalid("Invite code not found or already used.")
    try:
        u = create(username, password, inv["role"], inv["tenant_id"], employee_id.strip().upper() if employee_id else None)
    except Exception:
        claimed.pop("_id", None)
        mongo.col("invites").insert_one(claimed)  # compensating write
        raise
    tenants.audit(inv["tenant_id"], username, "invite.redeemed", f"role={inv['role']}")
    return authenticate(username, password) if u else u


def list_for_tenant(tid: str) -> list[dict]:
    rows = mongo.col("users").find({"tenant_id": tid}).sort([("role", 1), ("username", 1)])
    return [public(u) for u in rows]


def set_active(tid: str, uid: str, active: bool, actor: str) -> dict:
    u = get(uid)
    if u["tenant_id"] != tid:
        raise NotFound("User not found")
    mongo.col("users").update_one({"id": uid, "tenant_id": tid}, {"$set": {"active": int(active)}})
    tenants.audit(tid, actor, "user.enabled" if active else "user.disabled", u["username"])
    return public(get(uid))


def set_prefs(uid: str, prefs: dict) -> dict:
    u = get(uid)
    merged = {**mongo.from_pairs(u.get("prefs")), **prefs}
    mongo.col("users").update_one({"id": uid}, {"$set": {"prefs": mongo.to_pairs(merged)}})
    return public(get(uid))


# ------------------------------------------------------------------ demo accounts
# The demo hotel is the FICTIONAL Himsagar Ridge Resort, Mussoorie (hoi_platform/seed.py); accounts link to staff ids.
DEMO_ACCOUNTS = [
    ("demo.owner", "owner", "HS01", "Hotel manager (HS01)", "Everything for one hotel group"),
    ("demo.hr", "hr", None, "HR", "Retention pages, no roster or inventory"),
    ("demo.housekeeping", "dept_head", "HS02", "Housekeeping head (HS02)", "Roster, dispatch, inventory requests"),
    ("demo.frontoffice", "dept_head", "HS08", "Front office head (HS08)", "Guest services, late checkouts, dispatch"),
    ("demo.store", "storekeeper", None, "Storekeeper", "Inventory only"),
    ("HS05", "worker", "HS05", "Housekeeping attendant (HS05)", "Employee app: shifts, jobs, supplies"),
    ("HS09", "worker", "HS09", "Front office associate (HS09)", "Employee app: shifts, jobs, supplies"),
    ("HS12", "worker", "HS12", "Restaurant server (HS12)", "Employee app: shifts, jobs, supplies"),
    ("HS18", "worker", "HS18", "Maintenance technician (HS18)", "Employee app: shifts, jobs, supplies"),
    ("demo.homestay", "owner", None, "Homestay owner (Deodar Nest)", "Homestay mode: the simple app for a 6-room homestay"),
    ("DN03", "worker", "DN03", "Homestay helper (DN03)", "Homestay mode: a simple task list"),
]
LEGACY_DEMO_USERS = ("E134",)  # worker account of the former demo hotel: removed from the demo tenant

# Department heads are scoped to one department (e.g. GET /dispatch/performance). Stored on the user document.
DEMO_DEPARTMENTS = {"demo.housekeeping": "housekeeping", "demo.frontoffice": "front_office"}


def department_of(uid: str) -> str | None:
    """A user's department: the `department` field (department heads), else the staff record of their employee id."""
    u = _raw({"id": uid}) or {}
    if u.get("department"):
        return str(u["department"])
    if u.get("employee_id") and u.get("tenant_id"):
        s = mongo.col("staff").find_one({"tenant_id": u["tenant_id"], "employee_id": u["employee_id"]}, {"department": 1})
        return s.get("department") if s else None
    return None


def has_platform_admin() -> bool:
    return mongo.col("users").count_documents({"role": "platform_admin"}, limit=1) > 0


def ensure_demo_users(demo_tenant: str, admin_password: str | None, default_property: dict[str, str] | None = None) -> None:
    legacy = [
        u["id"]
        for u in mongo.col("users").find(
            {"tenant_id": demo_tenant, "_username_lc": {"$in": [x.lower() for x in LEGACY_DEMO_USERS]}}, {"id": 1}
        )
    ]
    if legacy:
        mongo.col("refresh_tokens").delete_many({"user_id": {"$in": legacy}})
        mongo.col("users").delete_many({"id": {"$in": legacy}})
    for username, role, emp, *_ in DEMO_ACCOUNTS:
        if not by_username(username):
            try:
                create(username, secrets.token_urlsafe(18), role, demo_tenant, emp)  # random password: one-click demo only
            except Invalid:  # created concurrently by another process
                pass
    for username, pid in (default_property or {}).items():  # e.g. the homestay owner opens the homestay first
        u = by_username(username)
        if u and not mongo.from_pairs(u.get("prefs")).get("property_id"):
            set_prefs(u["id"], {"property_id": pid})
    for username, dept in DEMO_DEPARTMENTS.items():  # idempotent: also fixes accounts created before departments existed
        mongo.col("users").update_one({"_username_lc": username, "department": {"$exists": False}}, {"$set": {"department": dept}})
    if not has_platform_admin():
        pw = admin_password if admin_password and len(admin_password) >= 6 else secrets.token_urlsafe(18)
        create("platform", pw, "platform_admin", None)
