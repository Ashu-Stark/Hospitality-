"""Tenants (hotel groups), properties, staff, invites, audit log, plans and modules."""

from __future__ import annotations

import uuid

from pymongo import DESCENDING

from .. import mongo
from .errors import Invalid, NotFound

PLANS = {
    "starter": {"label": "Starter", "properties": 1, "staff": 80, "modules": ["roster", "dispatch", "inventory"]},
    "growth": {"label": "Growth", "properties": 5, "staff": 400, "modules": ["roster", "dispatch", "inventory", "retention", "voice"]},
    "chain": {"label": "Chain", "properties": None, "staff": None, "modules": ["roster", "dispatch", "inventory", "retention", "voice"]},
}
MODULES = ["retention", "roster", "dispatch", "inventory", "voice"]
SENSITIVE_COLUMNS = [
    "name",
    "gender",
    "sex",
    "religion",
    "caste",
    "health",
    "medical",
    "family",
    "marital",
    "age",
    "dob",
    "birth",
    "phone",
    "mobile",
    "email",
    "address",
    "aadhaar",
    "pan",
]
DEPARTMENTS = ["housekeeping", "maintenance", "fnb_service", "front_office", "security", "kitchen"]
OPTIONAL_STAFF_FIELDS = ("role_title", "avatar", "property_id")
INVITE_ROLES = {"owner", "hr", "dept_head", "storekeeper", "worker"}


# ------------------------------------------------------------------ audit
def audit(tenant_id: str | None, actor: str | None, action: str, detail: str = "") -> None:
    mongo.col("audit_log").insert_one(
        {"id": mongo.next_id("audit_log"), "tenant_id": tenant_id, "actor": actor, "action": action, "detail": detail, "at": mongo.now()}
    )


def audit_log(tenant_id: str | None = None, limit: int = 300) -> list[dict]:
    flt = {"tenant_id": tenant_id} if tenant_id else {}
    return mongo.find("audit_log", flt, [("id", DESCENDING)], limit)


# ------------------------------------------------------------------ tenants
def _out(t: dict) -> dict:
    t = mongo.clean(t)
    t["settings"] = mongo.from_pairs(t.get("settings"))
    t["use_mocks"], t["is_demo"], t["onboarded"] = bool(t["use_mocks"]), bool(t["is_demo"]), bool(t["onboarded"])
    t["modules"] = t["settings"].get("modules") or PLANS.get(t["plan"], PLANS["starter"])["modules"]
    t["logo_url"] = same_origin_path(t.get("logo_url"))
    return t


def same_origin_path(v: object) -> str | None:
    """A logo the apps may load: only a same-origin absolute path (e.g. /shared/brand/x.svg), never another host."""
    s = str(v or "").strip()
    if not s.startswith("/") or s.startswith("//") or "\\" in s or ".." in s or len(s) > 200:
        return None
    return s


COUNTED = ("properties", "staff", "users", "jobs")


def list_tenants() -> list[dict]:
    rows = [_out(t) for t in mongo.col("tenants").find({}).sort([("is_demo", DESCENDING), ("created_at", 1), ("_id", 1)])]
    for t in rows:
        t["counts"] = {name: mongo.col(name).count_documents({"tenant_id": t["id"]}) for name in COUNTED}
    return rows


def get_tenant(tid: str) -> dict:
    r = mongo.col("tenants").find_one({"id": tid})
    if not r:
        raise NotFound(f"Hotel group {tid} not found")
    return _out(r)


def create_tenant(
    name: str,
    *,
    plan: str = "starter",
    brand_color: str = "#1f6fe5",
    api_base_url: str | None = None,
    use_mocks: bool = True,
    is_demo: bool = False,
    tid: str | None = None,
) -> dict:
    if not name.strip():
        raise Invalid("Name is required.")
    if plan not in PLANS:
        raise Invalid(f"Unknown plan {plan}")
    tid = tid or mongo.new_id("org")
    doc = {
        "id": tid,
        "name": name.strip(),
        "plan": plan,
        "brand_color": brand_color,
        "api_base_url": api_base_url,
        "use_mocks": int(use_mocks),
        "is_demo": int(is_demo),
        "status": "active",
        "onboarding_step": 0,
        "onboarded": 0,
        "settings": [],
        "created_at": mongo.now(),
    }
    mongo.col("tenants").update_one({"id": tid}, {"$setOnInsert": doc}, upsert=True)  # insert-or-ignore
    return get_tenant(tid)


UPDATABLE = {"name", "plan", "brand_color", "api_base_url", "use_mocks", "status", "onboarding_step", "onboarded", "settings"}


def update_tenant(tid: str, **fields) -> dict:
    get_tenant(tid)
    fields = {k: v for k, v in fields.items() if k in UPDATABLE and v is not None}
    if "plan" in fields and fields["plan"] not in PLANS:
        raise Invalid("Unknown plan")
    if "status" in fields and fields["status"] not in ("active", "suspended"):
        raise Invalid("Status must be active or suspended")
    if "settings" in fields:
        mods = fields["settings"].get("modules")
        if mods is not None and any(m not in MODULES for m in mods):
            raise Invalid(f"Unknown module in {mods}")
        fields["settings"] = mongo.to_pairs(fields["settings"])
    if not fields:
        return get_tenant(tid)
    mongo.col("tenants").update_one({"id": tid}, {"$set": {k: int(v) if isinstance(v, bool) else v for k, v in fields.items()}})
    return get_tenant(tid)


TENANT_COLLECTIONS = (
    "properties",
    "staff",
    "jobs",
    "photos",
    "photo_blobs",
    "invites",
    "dispatch_context",
    "inv_items",
    "inv_locations",
    "inv_suppliers",
    "inv_stock",
    "inv_moves",
    "inv_reqs",
    "inv_pos",
    "inv_counts",
    "rooms",
    "roster_snapshots",
    "hotel_profiles",
    "guest_checkouts",
    "late_checkouts",
    "guest_feedback",
    "staffing_requests",
)


def delete_tenant(tid: str) -> None:
    """Cascade delete: children first and the tenant last, so an interrupted delete can simply be retried. Audit is kept."""
    t = get_tenant(tid)
    if t["is_demo"]:
        raise Invalid("The demo workspace cannot be deleted.")
    d = mongo.db()
    for name in TENANT_COLLECTIONS:
        d[name].delete_many({"tenant_id": tid})
    uids = [u["id"] for u in d.users.find({"tenant_id": tid}, {"id": 1})]
    if uids:
        d.refresh_tokens.delete_many({"user_id": {"$in": uids}})
    d.users.delete_many({"tenant_id": tid})
    d.tenants.delete_one({"id": tid})


# ------------------------------------------------------------------ properties / staff
# Property mode: "homestay" shows a small, plain-language app (few rooms, a host family team, no dispatch details);
# "hotel" shows everything. ASSUMED: properties with up to HOMESTAY_MAX_ROOMS rooms start as homestays (owner can switch).
MODES = ("hotel", "homestay")
HOMESTAY_MAX_ROOMS = 10
PROPERTY_SETTINGS = ("mode", "incentive_monthly_budget_cap", "recognition_leaderboard_opt_in")


def default_mode(rooms: int) -> str:
    return "homestay" if int(rooms or 0) <= HOMESTAY_MAX_ROOMS else "hotel"


def _prop_out(p: dict) -> dict:
    """API copy of a property. The portal API key is stored as `_portal_key` (never returned; mongo.clean drops `_` fields)."""
    p = dict(p)
    p["mode"] = p.get("mode") if p.get("mode") in MODES else default_mode(p.get("rooms") or 0)
    p["incentive_monthly_budget_cap"] = int(p.get("incentive_monthly_budget_cap") or 0)
    p["recognition_leaderboard_opt_in"] = bool(p.get("recognition_leaderboard_opt_in"))
    p["recognition"] = p.get("recognition") or {}
    return p


def _key_set(tid: str) -> set[str]:
    return {r["id"] for r in mongo.col("properties").find({"tenant_id": tid, "_portal_key": {"$nin": [None, ""]}}, {"id": 1})}


def properties(tid: str) -> list[dict]:
    keyed = _key_set(tid)
    return [
        {**_prop_out(p), "portal_key_set": p["id"] in keyed}
        for p in mongo.find("properties", {"tenant_id": tid}, [("created_at", 1), ("_id", 1)])
    ]


def get_property(tid: str, property_id: str | None = None) -> dict:
    """One property of the tenant; without an id (or an unknown one) the first property. NotFound when there is none."""
    props = properties(tid)
    if not props:
        raise NotFound("This hotel group has no property yet.")
    if property_id:
        hit = next((p for p in props if p["id"] == property_id), None)
        if hit is None:
            raise NotFound("Property not found.")
        return hit
    return props[0]


def update_property(tid: str, property_id: str, **fields) -> dict:
    """Owner settings per property: mode, incentive budget cap, leaderboard opt-in, and the tourism-portal API key
    (write-only: stored as `_portal_key`, never returned or logged; an empty string removes it)."""
    get_property(tid, property_id)
    sets: dict = {}
    if fields.get("mode") is not None:
        if fields["mode"] not in MODES:
            raise Invalid(f"Mode must be one of {MODES}")
        sets["mode"] = fields["mode"]
    if fields.get("incentive_monthly_budget_cap") is not None:
        cap = int(fields["incentive_monthly_budget_cap"])
        if not 0 <= cap <= 10_000_000:
            raise Invalid("The monthly incentive budget must be between 0 and 1,00,00,000.")
        sets["incentive_monthly_budget_cap"] = cap
    if fields.get("recognition_leaderboard_opt_in") is not None:
        sets["recognition_leaderboard_opt_in"] = bool(fields["recognition_leaderboard_opt_in"])
    if fields.get("recognition") is not None:  # validated by services.recognition.validate_config in the router
        sets["recognition"] = fields["recognition"]
    if fields.get("portal_api_key") is not None:
        key = str(fields["portal_api_key"]).strip()
        if key and (len(key) > 200 or not all(c.isalnum() or c in "-_." for c in key)):
            raise Invalid("That does not look like a portal API key (letters, digits, - _ . only).")
        sets["_portal_key"] = key or None
    if sets:
        mongo.col("properties").update_one({"tenant_id": tid, "id": property_id}, {"$set": sets})
    return get_property(tid, property_id)


def portal_key(tid: str, property_id: str) -> str | None:
    """The property's tourism-portal business API key (secret: callers must never log or return it)."""
    r = mongo.col("properties").find_one({"tenant_id": tid, "id": property_id}, {"_portal_key": 1})
    return (r or {}).get("_portal_key") or None


def property_of_staff(tid: str, employee_id: str | None) -> dict | None:
    """The property an employee works at: the staff record's property_id, else the tenant's first property."""
    props = properties(tid)
    if not props:
        return None
    s = mongo.col("staff").find_one({"tenant_id": tid, "employee_id": employee_id}, {"property_id": 1}) if employee_id else None
    pid = (s or {}).get("property_id")
    return next((p for p in props if p["id"] == pid), props[0])


def staff_property_map(tid: str) -> dict[str, str | None]:
    """employee_id -> property id (first property when the staff record has none)."""
    props = mongo.find("properties", {"tenant_id": tid}, [("created_at", 1), ("_id", 1)])
    first = props[0]["id"] if props else None
    return {
        s["employee_id"]: s.get("property_id") or first
        for s in mongo.col("staff").find({"tenant_id": tid}, {"employee_id": 1, "property_id": 1})
    }


def add_property(tid: str, name: str, region: str, rooms: int, floors: int = 3, mode: str | None = None) -> dict:
    t = get_tenant(tid)
    limit = PLANS[t["plan"]]["properties"]
    if limit and mongo.col("properties").count_documents({"tenant_id": tid}) >= limit:
        raise Invalid(f"The {PLANS[t['plan']]['label']} plan allows {limit} propert{'y' if limit == 1 else 'ies'}.")
    if not name.strip() or rooms < 1:
        raise Invalid("Property needs a name and at least one room.")
    doc = {
        "id": mongo.new_id("prop"),
        "tenant_id": tid,
        "name": name.strip(),
        "region": region,
        "rooms": int(rooms),
        "floors": int(floors),
        "mode": mode if mode in MODES else default_mode(rooms),
        "created_at": mongo.now(),
    }
    mongo.col("properties").insert_one(doc)
    return _prop_out(mongo.clean(doc))


def staff(tid: str) -> list[dict]:
    return mongo.find("staff", {"tenant_id": tid}, [("employee_id", 1)])


def import_staff(tid: str, rows: list[dict]) -> int:
    """Upsert staff by ID. Rejects any personal / sensitive column (privacy guard, enforced server-side)."""
    cols = {k.lower() for r in rows for k in r}
    bad = sorted(c for c in cols if any(s in c for s in SENSITIVE_COLUMNS) and c not in ("employee_id",))
    if bad:
        raise Invalid(f"Rejected: personal columns {bad}. Import employee IDs only.")
    for r in rows:
        if not str(r.get("employee_id", "")).strip() or not str(r.get("department", "")).strip():
            raise Invalid("Every row needs employee_id and department.")
    t = get_tenant(tid)
    pids = {p["id"] for p in mongo.col("properties").find({"tenant_id": tid}, {"id": 1})}
    bad_props = sorted({str(r["property_id"]) for r in rows if str(r.get("property_id") or "").strip() and r["property_id"] not in pids})
    if bad_props:
        raise Invalid(f"Unknown property {bad_props[0]} for this hotel group.")
    limit = PLANS[t["plan"]]["staff"]
    after = {s["employee_id"] for s in staff(tid)} | {str(r["employee_id"]).strip().upper() for r in rows}
    if limit and len(after) > limit:
        raise Invalid(f"The {PLANS[t['plan']]['label']} plan allows {limit} staff; this import would make {len(after)}.")
    for r in rows:  # each upsert is atomic and idempotent (unique tenant_id + employee_id): a retried import converges
        emp = str(r["employee_id"]).strip().upper()
        fields = {
            "department": str(r["department"]).strip().lower().replace(" ", "_"),
            "skills": str(r.get("skills") or ""),
            "contract_type": str(r.get("contract_type") or "permanent"),
        }
        for opt in OPTIONAL_STAFF_FIELDS:  # job title and avatar key (role slug): no personal data
            if str(r.get(opt) or "").strip():
                fields[opt] = str(r[opt]).strip()[:60]
        mongo.col("staff").update_one({"tenant_id": tid, "employee_id": emp}, {"$set": fields}, upsert=True)
    return len(rows)


# ------------------------------------------------------------------ invites
def create_invite(tid: str, role: str) -> dict:
    if role not in INVITE_ROLES:
        raise Invalid(f"Role must be one of {sorted(INVITE_ROLES)}")
    get_tenant(tid)
    code = uuid.uuid4().hex[:10].upper()
    mongo.col("invites").insert_one({"code": code, "tenant_id": tid, "role": role, "created_at": mongo.now()})
    return {"code": code, "role": role, "tenant_id": tid}


def invites(tid: str) -> list[dict]:
    return mongo.find("invites", {"tenant_id": tid}, [("created_at", DESCENDING), ("_id", DESCENDING)])
