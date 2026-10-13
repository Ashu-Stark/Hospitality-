"""Accounts (state admin, district officers, business owners, job seekers), lockout, refresh-token sessions.

No personal data is stored: a username, role, optional district, password hash. Refresh tokens are stored only as
SHA-256, rotated on every use, with reuse detection (a reused rotated token revokes all the user's sessions).
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta

from pymongo.errors import DuplicateKeyError

from .. import catalog, config, mongo, security
from ..errors import Conflict, Invalid, NotFound, Unauthorized
from ..seed.districts import BY_ID as DISTRICTS

MAX_FAILED, LOCK_MINUTES = 5, 5
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,40}$")
PUBLIC_FIELDS = ("id", "username", "role", "district", "label", "active", "created_at", "last_login")

DEMO_ACCOUNTS = [
    # username, role, district, label, description
    ("demo.admin", "state_admin", None, "State admin (demo)", "All districts: officers, analytics, approvals"),
    (
        "demo.officer.rudraprayag",
        "district_officer",
        "rudraprayag",
        "District tourism officer, Rudraprayag (demo)",
        "Applications, grievances, advisories and analytics for Rudraprayag only",
    ),
    ("demo.business", "business", None, "Business owner (demo)", "Registered homestay and hotel, renewals, occupancy, API key, hiring"),
    ("demo.seeker", "job_seeker", None, "Job seeker (demo)", "Hiring board: own profile, job search, applications, interest requests"),
]
ADMIN_USERNAME = "admin"


def public(u: dict) -> dict:
    out = {k: u.get(k) for k in PUBLIC_FIELDS}
    out["created_at"] = mongo.iso(u.get("created_at"))
    out["last_login"] = mongo.iso(u.get("last_login"))
    out["role_label"] = catalog.ROLES.get(u["role"], u["role"])
    out["district_name"] = DISTRICTS[u["district"]]["name"] if u.get("district") in DISTRICTS else None
    return out


def get(uid: str) -> dict:
    u = mongo.db().users.find_one({"id": uid})
    if not u:
        raise NotFound("User not found.")
    return mongo.clean(u)


def by_username(username: str) -> dict | None:
    return mongo.clean(mongo.db().users.find_one({"username_lc": username.strip().lower()}))


def create(username: str, password: str | None, role: str, district: str | None = None, label: str | None = None) -> dict:
    username = username.strip()
    if role not in catalog.ROLES:
        raise Invalid(f"Unknown role {role}.")
    if not USERNAME_RE.match(username):
        raise Invalid("Username: 3-40 characters, letters, digits, dot, dash or underscore.")
    if role == "district_officer" and district not in DISTRICTS:
        raise Invalid("District officers need a valid district.")
    if role != "district_officer":
        district = None
    if password is None:  # demo accounts: unusable random password (demo login only)
        password = secrets.token_urlsafe(24)
    if len(password) < 10:
        raise Invalid("Password must be at least 10 characters.")
    pw_hash, salt = security.hash_password(password)
    doc = {
        "id": "usr_" + secrets.token_hex(6),
        "username": username,
        "username_lc": username.lower(),
        "role": role,
        "district": district,
        "label": label,
        "pw_hash": pw_hash,
        "salt": salt,
        "active": True,
        "failed": 0,
        "locked_until": None,
        "created_at": mongo.now(),
        "last_login": None,
    }
    try:
        mongo.db().users.insert_one(doc)
    except DuplicateKeyError:  # mongomock's DuplicateKeyError subclasses pymongo's
        raise Conflict("That username is taken.") from None
    mongo.audit(username, "user.created", doc["id"], f"role={role}", district)
    return mongo.clean(doc)


def authenticate(username: str, password: str) -> dict:
    d = mongo.db()
    u = d.users.find_one({"username_lc": username.strip().lower()})
    if not u:
        security.burn_time(password)
        raise Unauthorized("Wrong username or password.")
    if not u.get("active"):
        raise Unauthorized("This account is disabled.")
    locked = mongo.aware(u.get("locked_until"))
    if locked and locked > mongo.now():
        raise Unauthorized("Too many failed attempts. Try again in a few minutes.")
    if not security.verify_password(password, u["pw_hash"], u["salt"]):
        failed = int(u.get("failed", 0)) + 1
        lock = mongo.now() + timedelta(minutes=LOCK_MINUTES) if failed >= MAX_FAILED else None
        d.users.update_one({"id": u["id"]}, {"$set": {"failed": 0 if lock else failed, "locked_until": lock}})
        mongo.audit(u["username"], "login.failed", u["id"], "locked" if lock else f"attempt {failed}", u.get("district"))
        raise Unauthorized("Wrong username or password.")
    d.users.update_one({"id": u["id"]}, {"$set": {"failed": 0, "locked_until": None, "last_login": mongo.now()}})
    mongo.audit(u["username"], "login.ok", u["id"], "", u.get("district"))
    return get(u["id"])


def set_active(uid: str, active: bool, actor: str) -> dict:
    r = mongo.db().users.update_one({"id": uid}, {"$set": {"active": active}})
    if not r.matched_count:
        raise NotFound("User not found.")
    if not active:
        revoke_all(uid)
    mongo.audit(actor, "user.activated" if active else "user.disabled", uid)
    return public(get(uid))


def list_users(role: str | None = None) -> list[dict]:
    q = {"role": role} if role else {}
    return [public(mongo.clean(u)) for u in mongo.db().users.find(q).sort("username_lc", 1)]


def ensure_admin() -> None:
    """Create the state admin `admin` from PORTAL_ADMIN_PASSWORD (production path) if it does not exist."""
    pw = config.settings.admin_password
    if pw and not by_username(ADMIN_USERNAME):
        create(ADMIN_USERNAME, pw, "state_admin", label="State admin")


def ensure_demo_users() -> None:
    for username, role, district, label, _desc in DEMO_ACCOUNTS:
        if not by_username(username):
            create(username, None, role, district, label)


# ------------------------------------------------------------------ refresh sessions
def issue_refresh(user_id: str) -> str:
    raw, digest = security.new_refresh_token()
    mongo.db().refresh_tokens.insert_one(
        {
            "id": "rt_" + secrets.token_hex(8),
            "user_id": user_id,
            "token_hash": digest,
            "expires_at": mongo.now() + timedelta(days=config.settings.refresh_ttl_days),
            "created_at": mongo.now(),
            "revoked": False,
            "replaced_by": None,
        }
    )
    return raw


def rotate_refresh(raw: str) -> tuple[str, str]:
    """Return (user_id, new_raw). Raises Unauthorized for unknown, expired, revoked or reused tokens."""
    d = mongo.db()
    t = d.refresh_tokens.find_one({"token_hash": security.sha256(raw)})
    if not t:
        raise Unauthorized("Session expired. Sign in again.")
    if t["revoked"]:
        if t.get("replaced_by"):  # reuse of a rotated token: probably stolen, revoke the whole family
            revoke_all(t["user_id"])
        raise Unauthorized("Session expired. Sign in again.")
    if mongo.aware(t["expires_at"]) <= mongo.now():
        raise Unauthorized("Session expired. Sign in again.")
    # Atomic claim: only one concurrent refresh can rotate this token.
    claimed = d.refresh_tokens.find_one_and_update({"token_hash": t["token_hash"], "revoked": False}, {"$set": {"revoked": True}})
    if not claimed:
        raise Unauthorized("Session expired. Sign in again.")
    new_raw = issue_refresh(t["user_id"])
    d.refresh_tokens.update_one({"token_hash": t["token_hash"]}, {"$set": {"replaced_by": security.sha256(new_raw)[:16]}})
    return t["user_id"], new_raw


def revoke_refresh(raw: str) -> None:
    mongo.db().refresh_tokens.update_one({"token_hash": security.sha256(raw)}, {"$set": {"revoked": True}})


def revoke_all(user_id: str) -> None:
    mongo.db().refresh_tokens.update_many({"user_id": user_id}, {"$set": {"revoked": True}})
