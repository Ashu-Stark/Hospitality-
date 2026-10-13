"""Business registry (A-Z directory), verification by registration number, registration-number issuing.

Registration number: UK-<TYPE CODE>-<DISTRICT CODE>-<NNNNN>, NNNNN from a per (type, district) counter.
Status is stored, but an `active` record past its `valid_until` date is shown as `expired`.
"""

from __future__ import annotations

import re
from datetime import date

from .. import catalog, mongo
from ..errors import Invalid, NotFound
from ..seed.destinations import BY_ID_DEST
from ..seed.districts import BY_ID as DISTRICTS
from . import search

REG_RE = re.compile(r"^UK-([A-Z]{3})-([A-Z]{3})-(\d{5})$")
PUBLIC_FIELDS = (
    "id",
    "reg_no",
    "name",
    "type",
    "district",
    "destination_id",
    "status",
    "verified",
    "rating",
    "capacity",
    "beds",
    "languages",
    "registered_on",
    "valid_until",
    "hoi_connected",
)
CONTACT_PLACEHOLDER = "Contact details are shown to verified visitors in the full product (placeholder in this prototype)."


def issue_reg_no(btype: str, district: str) -> str:
    code = catalog.BUSINESS_TYPES[btype][1]
    dcode = DISTRICTS[district]["code"]
    n = mongo.next_seq(f"reg:{code}:{dcode}")
    return f"UK-{code}-{dcode}-{n:05d}"


def effective_status(b: dict, today: str | None = None) -> str:
    today = today or date.today().isoformat()
    if b.get("status") == "active" and b.get("valid_until") and b["valid_until"] < today:
        return "expired"
    return b.get("status", "pending")


def search_text(b: dict) -> str:
    dest = BY_ID_DEST.get(b.get("destination_id"), {})
    return search.normalize(
        b["name"],
        b["reg_no"],
        catalog.BUSINESS_TYPES[b["type"]][0],
        DISTRICTS[b["district"]]["name"],
        dest.get("name"),
        " ".join(b.get("languages", [])),
    )


def public(b: dict) -> dict:
    out = {k: b.get(k) for k in PUBLIC_FIELDS}
    label, _code, unit = catalog.BUSINESS_TYPES[b["type"]]
    out["status"] = effective_status(b)
    out["verified"] = bool(b.get("verified")) and out["status"] == "active"
    out["type_label"] = label
    out["capacity_unit"] = unit
    out["district_name"] = DISTRICTS[b["district"]]["name"]
    dest = BY_ID_DEST.get(b.get("destination_id"))
    out["destination_name"] = dest["name"] if dest else None
    out["letter"] = (b["name"][:1] or "#").upper()
    out["contact"] = CONTACT_PLACEHOLDER
    out["synthetic"] = bool(b.get("synthetic"))
    return out


def list_businesses(
    *,
    type: str | None = None,
    district: str | None = None,
    destination: str | None = None,
    status: str | None = None,
    letter: str | None = None,
    q: str | None = None,
    verified: bool | None = None,
    page: int = 1,
    page_size: int = 24,
    sort: str = "name",
) -> dict:
    """`type` may be a comma list (e.g. "hotel,homestay"); `sort` is "name" (A-Z) or "rating" (best first)."""
    f: dict = {}
    today = date.today().isoformat()
    if type:
        types = [t for t in type.split(",") if t]
        if not types or any(t not in catalog.BUSINESS_TYPES for t in types):
            raise Invalid("Unknown business type.")
        f["type"] = types[0] if len(types) == 1 else {"$in": types}
    if district:
        if district not in DISTRICTS:
            raise Invalid("Unknown district.")
        f["district"] = district
    if destination:
        f["destination_id"] = destination
    if status:
        if status not in catalog.BUSINESS_STATUSES:
            raise Invalid("Unknown status.")
        if status == "active":
            f["status"], f["valid_until"] = "active", {"$gte": today}
        elif status == "expired":
            f["$or"] = [{"status": "expired"}, {"status": "active", "valid_until": {"$lt": today}}]
        else:
            f["status"] = status
    if letter:
        letter = letter.strip().upper()[:1]
        if not letter.isalpha():
            raise Invalid("Letter must be A-Z.")
        f["name_lc"] = {"$regex": "^" + re.escape(letter.lower())}
    if verified:  # the badge only shows on active registrations
        f.update({"verified": True, "status": "active", "valid_until": {"$gte": today}})
    f.update(search.regex_filter(q))
    page, page_size = max(1, page), min(max(1, page_size), 100)
    col = mongo.db().businesses
    total = col.count_documents(f)
    order = [("rating", -1), ("name_lc", 1)] if sort == "rating" else [("name_lc", 1)]
    docs = col.find(f).sort(order).skip((page - 1) * page_size).limit(page_size)
    items = [public(b) for b in docs]
    return {"items": items, "total": total, "page": page, "page_size": page_size, "letters": letters(), "synthetic": True}


def letters() -> list[str]:
    return sorted({(n or "#")[:1].upper() for n in mongo.db().businesses.distinct("name")})


def get(business_id_or_reg: str) -> dict:
    key = business_id_or_reg.strip()
    b = mongo.db().businesses.find_one({"$or": [{"id": key}, {"reg_no": key.upper()}]})
    if not b:
        raise NotFound("Business not found.")
    return mongo.clean(b)


def verify(reg_no: str) -> dict:
    reg = re.sub(r"\s+", "", (reg_no or "").upper())[:30]
    if not REG_RE.match(reg):
        return {
            "reg_no": reg,
            "found": False,
            "valid": False,
            "message": "That does not look like a registration number. Format: UK-<TYPE>-<DISTRICT>-<5 digits>, e.g. UK-HMS-RUD-00001.",
        }
    b = mongo.db().businesses.find_one({"reg_no": reg})
    if not b:
        return {"reg_no": reg, "found": False, "valid": False, "message": "No business with this registration number is on the register."}
    pub = public(mongo.clean(b))
    status = pub["status"]
    messages = {
        "active": "Registration is active.",
        "expired": "Registration has expired. The business should renew before operating.",
        "suspended": "Registration is suspended.",
        "pending": "Renewal is pending review.",
    }
    return {
        "reg_no": reg,
        "found": True,
        "valid": status == "active",
        "status": status,
        "message": messages.get(status, status),
        "business": pub,
        "note": "Prototype register with SYNTHETIC businesses.",
    }


def nearby(destination_id: str, limit: int = 6) -> dict:
    today = date.today().isoformat()
    docs = mongo.db().businesses.find({"destination_id": destination_id, "status": "active", "valid_until": {"$gte": today}})
    items = sorted((public(mongo.clean(b)) for b in docs), key=lambda x: (not x["verified"], -(x["rating"] or 0), x["name"]))
    groups = {"stays": [], "guides": [], "transport": [], "other": []}
    for i in items:
        key = (
            "stays"
            if i["type"] in catalog.STAY_TYPES
            else "guides"
            if i["type"] in ("guide", "adventure_operator", "tour_operator")
            else "transport"
            if i["type"] == "transport"
            else "other"
        )
        groups[key].append(i)
    return {k: {"items": v[:limit], "total": len(v)} for k, v in groups.items()}
