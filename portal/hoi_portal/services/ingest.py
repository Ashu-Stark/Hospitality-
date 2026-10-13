"""Occupancy write path shared by HOI ingest (X-API-Key, daily) and the business monthly submission form.

Each write updates the business-month document (`occupancy`) and the destination aggregate (`occupancy_agg`) by
the delta from the previous value, so repeating the same (business, date) is idempotent. No transactions: the two
single-document updates run in order; if the second fails the first is rolled back (compensating write).
Precedence per day: HOI ingest ("i") > monthly submission ("m") > seed ("s"). A monthly submission never
overwrites ingested days.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from pymongo import ReturnDocument

from .. import catalog, mongo, security
from ..errors import Forbidden, Invalid, Unauthorized
from . import crowd

MAX_BACKDATE_DAYS = 400
WRITABLE_STATUSES = ("active", "pending")


def _month_arrays(n: int) -> dict:
    return {"avail": [None] * n, "occ": [None] * n, "src": [None] * n}


def _check_business(b: dict) -> None:
    from .registry import effective_status

    if b["type"] not in catalog.STAY_TYPES:
        raise Invalid("Occupancy is reported only by hotels and homestays.")
    if effective_status(b) not in WRITABLE_STATUSES:
        raise Forbidden("This registration is not active, so occupancy cannot be reported. Renew first.")


def write_day(b: dict, day: date, avail: int, occ: int, source: str) -> str:
    """Set one day's figures. Returns 'created', 'replaced' or 'unchanged'."""
    d = mongo.db()
    month, i = day.strftime("%Y-%m"), day.day - 1
    n = calendar.monthrange(day.year, day.month)[1]
    key = {"business_id": b["id"], "month": month}
    d.occupancy.update_one(
        key,
        {
            "$setOnInsert": {
                **_month_arrays(n),
                "destination_id": b["destination_id"],
                "district": b["district"],
                "stay_type": b["type"],
                "synthetic": False,
            }
        },
        upsert=True,
    )
    before = d.occupancy.find_one_and_update(
        key,
        {"$set": {f"avail.{i}": avail, f"occ.{i}": occ, f"src.{i}": source, "updated_at": mongo.now()}},
        projection={"avail": 1, "occ": 1, "src": 1},
        return_document=ReturnDocument.BEFORE,
    )
    old_a, old_o, old_src = before["avail"][i], before["occ"][i], before["src"][i]
    da, do = avail - (old_a or 0), occ - (old_o or 0)
    if da or do:
        akey = {"destination_id": b["destination_id"], "stay_type": b["type"], "month": month}
        try:
            d.occupancy_agg.update_one(akey, {"$setOnInsert": {"avail": [0] * n, "occ": [0] * n, "district": b["district"]}}, upsert=True)
            d.occupancy_agg.update_one(akey, {"$inc": {f"avail.{i}": da, f"occ.{i}": do}})
        except Exception:
            d.occupancy.update_one(key, {"$set": {f"avail.{i}": old_a, f"occ.{i}": old_o, f"src.{i}": old_src}})
            raise
        crowd.invalidate()
    if old_a is None:
        return "created"
    return "replaced" if (da or do or old_src != source) else "unchanged"


def business_for_key(raw_key: str | None) -> tuple[dict, dict]:
    if not raw_key or not raw_key.startswith(security.API_KEY_PREFIX) or len(raw_key) > 100:
        raise Unauthorized("Missing or invalid API key.")
    d = mongo.db()
    k = d.api_keys.find_one({"key_hash": security.sha256(raw_key), "revoked": False})
    if not k:
        raise Unauthorized("Missing or invalid API key.")
    b = d.businesses.find_one({"id": k["business_id"]})
    if not b:
        raise Unauthorized("Missing or invalid API key.")
    d.api_keys.update_one({"id": k["id"]}, {"$set": {"last_used_at": mongo.now()}})
    return mongo.clean(b), k


def ingest(raw_key: str | None, body: dict) -> dict:
    b, k = business_for_key(raw_key)
    _check_business(b)
    try:
        day = date.fromisoformat(body["date"])
    except (TypeError, ValueError):
        raise Invalid("date must be YYYY-MM-DD.") from None
    today = date.today()
    if day > today:
        raise Invalid("date cannot be in the future.")
    if day < today - timedelta(days=MAX_BACKDATE_DAYS):
        raise Invalid(f"date is more than {MAX_BACKDATE_DAYS} days old.")
    avail, occ = int(body["rooms_available"]), int(body["rooms_occupied"])
    if avail > b["capacity"]:
        raise Invalid(f"rooms_available ({avail}) exceeds the registered capacity ({b['capacity']}).")
    if occ > avail:
        raise Invalid("rooms_occupied cannot exceed rooms_available.")
    staff, flagged = body.get("staff_count"), body.get("staff_flagged")
    if flagged is not None and (staff is None or flagged > staff):
        raise Invalid("staff_flagged needs staff_count and cannot exceed it.")
    result = write_day(b, day, avail, occ, "i")
    d = mongo.db()
    if staff is not None:
        d.workforce.update_one(
            {"business_id": b["id"], "month": day.strftime("%Y-%m")},
            {
                "$set": {"staff_count": staff, "flagged": flagged or 0, "source": "ingest", "updated_at": mongo.now()},
                "$setOnInsert": {
                    "district": b["district"],
                    "type": b["type"],
                    "destination_id": b["destination_id"],
                    "roles": {},
                    "separations": 0,
                    "synthetic": False,
                },
            },
            upsert=True,
        )
    if not b.get("hoi_connected"):
        d.businesses.update_one({"id": b["id"]}, {"$set": {"hoi_connected": True}})
    if result != "unchanged":
        mongo.audit(f"apikey:{k['prefix']}", "occupancy.ingested", b["id"], f"{day.isoformat()} {result}", b["district"])
    return {
        "business_id": b["id"],
        "reg_no": b["reg_no"],
        "date": day.isoformat(),
        "result": result,
        "occupancy_pct": round(100 * occ / avail, 1) if avail else None,
    }


def submit_month(b: dict, month: str, rooms_available: int, occupied_room_nights: int, actor: str) -> dict:
    """Monthly form: spread occupied room nights evenly over the month's days that were not ingested by HOI."""
    _check_business(b)
    try:
        y, m = (int(x) for x in month.split("-"))
        first = date(y, m, 1)
    except (ValueError, AttributeError):
        raise Invalid("month must be YYYY-MM.") from None
    today = date.today()
    if first > today:
        raise Invalid("month cannot be in the future.")
    if first < today.replace(day=1) - timedelta(days=MAX_BACKDATE_DAYS):
        raise Invalid("month is too old.")
    if rooms_available > b["capacity"]:
        raise Invalid(f"rooms_available exceeds the registered capacity ({b['capacity']}).")
    n = calendar.monthrange(y, m)[1]
    last_day = min(n, (today - first).days + 1) if (y, m) == (today.year, today.month) else n
    existing = mongo.db().occupancy.find_one({"business_id": b["id"], "month": month}) or {}
    src = existing.get("src") or [None] * n
    days = [i for i in range(last_day) if src[i] != "i"]
    if not days:
        raise Invalid("Every day of this month was already reported automatically by HOI.")
    if occupied_room_nights > rooms_available * len(days):
        raise Invalid(f"occupied_room_nights cannot exceed rooms_available x {len(days)} days.")
    base, extra = divmod(occupied_room_nights, len(days))
    counts = {"created": 0, "replaced": 0, "unchanged": 0}
    for j, i in enumerate(days):
        occ = base + (1 if j < extra else 0)
        counts[write_day(b, first + timedelta(days=i), rooms_available, occ, "m")] += 1
    mongo.audit(actor, "occupancy.monthly", b["id"], f"{month} {occupied_room_nights}/{rooms_available}", b["district"])
    return {
        "business_id": b["id"],
        "month": month,
        "days_written": len(days),
        "days_skipped_ingested": last_day - len(days),
        "occupancy_pct": round(100 * occupied_room_nights / (rooms_available * len(days)), 1) if rooms_available else None,
        **counts,
    }


def monthly_history(business_id: str, months: int = 12) -> list[dict]:
    out = []
    for doc in mongo.db().occupancy.find({"business_id": business_id}).sort("month", -1).limit(months):
        a = sum(x for x in doc["avail"] if x)
        o = sum(x for x in doc["occ"] if x is not None)
        src = [s for s in doc["src"] if s]
        out.append(
            {
                "month": doc["month"],
                "days_reported": len(src),
                "rooms_available_nights": a,
                "occupied_room_nights": o,
                "occupancy_pct": round(100 * o / a, 1) if a else None,
                "sources": {k: src.count(k) for k in ("s", "m", "i") if src.count(k)},
            }
        )
    return out
