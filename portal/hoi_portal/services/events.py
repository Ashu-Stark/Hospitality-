"""Festivals & events calendar: curated festivals (usual months) plus officer-posted dated events.

Curated festival dates follow the lunar calendar and are announced annually: they carry a `date_note`.
"""

from __future__ import annotations

import secrets
from datetime import date

from .. import catalog, mongo
from ..errors import Invalid, NotFound
from ..seed.destinations import BY_ID_DEST
from ..seed.districts import BY_ID as DISTRICTS
from . import search

FIELDS = (
    "id",
    "name",
    "kind",
    "months",
    "window",
    "districts",
    "destination_ids",
    "crowd_impact",
    "description",
    "date_note",
    "start_date",
    "end_date",
    "curated",
    "sample",
)


def public(e: dict) -> dict:
    out = {k: e.get(k) for k in FIELDS}
    out["district_names"] = [DISTRICTS[x]["name"] for x in e.get("districts", []) if x in DISTRICTS]
    out["destination_names"] = [BY_ID_DEST[x]["name"] for x in e.get("destination_ids", []) if x in BY_ID_DEST]
    out["statewide"] = len(e.get("districts", [])) == len(DISTRICTS)
    out["updated_at"] = mongo.iso(e.get("updated_at"))
    return out


def search_text(e: dict) -> str:
    return search.normalize(
        e["name"],
        e.get("description"),
        e.get("window"),
        " ".join(DISTRICTS[x]["name"] for x in e.get("districts", []) if x in DISTRICTS),
        " ".join(BY_ID_DEST[x]["name"] for x in e.get("destination_ids", []) if x in BY_ID_DEST),
    )


def _months_between(start: str, end: str) -> list[int]:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    months, y, m = [], s.year, s.month
    while (y, m) <= (e.year, e.month) and len(months) < 12:
        months.append(m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return sorted(set(months))


def _current(docs) -> list[dict]:
    today = date.today().isoformat()
    return [e for e in docs if not e.get("end_date") or e["end_date"] >= today]


def list_events(month: int | None = None, district: str | None = None, destination: str | None = None, q: str | None = None) -> dict:
    f: dict = {}
    if month is not None:
        if not 1 <= month <= 12:
            raise Invalid("Month must be 1-12.")
        f["months"] = month
    if district:
        if district not in DISTRICTS:
            raise Invalid("Unknown district.")
        f["districts"] = district
    if destination:
        if destination not in BY_ID_DEST:
            raise Invalid("Unknown destination.")
        f["$or"] = [{"destination_ids": destination}, {"districts": BY_ID_DEST[destination]["district"]}]
    f.update(search.regex_filter(q))
    docs = _current(mongo.db().events.find(f))
    items = sorted((public(e) for e in docs), key=lambda e: (e["start_date"] or "", min(e["months"] or [13]), e["name"]))
    by_month = {str(m): [e["id"] for e in items if m in (e["months"] or [])] for m in range(1, 13)}
    return {
        "items": items,
        "total": len(items),
        "by_month": by_month,
        "note": "Usual timing only. Lunar-calendar dates are announced annually; check the official notice.",
    }


def for_destination(dest_id: str) -> list[dict]:
    dest = BY_ID_DEST[dest_id]
    docs = _current(mongo.db().events.find({"$or": [{"destination_ids": dest_id}, {"districts": dest["district"]}]}))
    # Statewide festivals are listed too, but those naming this destination come first.
    return sorted((public(e) for e in docs), key=lambda e: (dest_id not in e["destination_ids"], e["statewide"], e["name"]))


def active_on(events: list[dict], dest_id: str, day: date) -> list[dict]:
    """Events affecting a destination on a day (used by the crowd estimate)."""
    district = BY_ID_DEST[dest_id]["district"]
    iso_day = day.isoformat()
    out = []
    for e in events:
        if dest_id not in e.get("destination_ids", []) and district not in e.get("districts", []):
            continue
        if e.get("start_date"):
            if e["start_date"] <= iso_day <= (e.get("end_date") or e["start_date"]):
                out.append(e)
        elif day.month in e.get("months", []):
            out.append(e)
    return out


def _validate(body: dict, district: str) -> dict:
    start, end = body.get("start_date"), body.get("end_date") or body.get("start_date")
    try:
        if date.fromisoformat(end) < date.fromisoformat(start):
            raise Invalid("End date is before start date.")
    except (TypeError, ValueError):
        raise Invalid("Dates must be YYYY-MM-DD.") from None
    dests = body.get("destination_ids") or []
    for d in dests:
        if d not in BY_ID_DEST or BY_ID_DEST[d]["district"] != district:
            raise Invalid(f"Destination {d} is not in this district.")
    impact = body.get("crowd_impact") or "low"
    if impact not in catalog.CROWD_IMPACTS:
        raise Invalid("crowd_impact must be low, medium or high.")
    return {
        "name": body["name"].strip(),
        "description": (body.get("description") or "").strip(),
        "start_date": start,
        "end_date": end,
        "months": _months_between(start, end),
        "window": f"{start} to {end}" if end != start else start,
        "destination_ids": dests,
        "crowd_impact": impact,
    }


def create(body: dict, district: str, actor: str) -> dict:
    if district not in DISTRICTS:
        raise Invalid("Unknown district.")
    doc = _validate(body, district) | {
        "id": "evt_" + secrets.token_hex(5),
        "kind": "event",
        "districts": [district],
        "date_note": "Posted by the district tourism office.",
        "curated": False,
        "sample": bool(body.get("sample", False)),
        "posted_by": actor,
        "created_at": mongo.now(),
        "updated_at": mongo.now(),
    }
    doc["search_text"] = search_text(doc)
    mongo.db().events.insert_one(doc)
    _changed()
    mongo.audit(actor, "event.created", doc["id"], doc["name"], district)
    return public(doc)


def get_scoped(event_id: str, district: str | None) -> dict:
    f: dict = {"id": event_id, "curated": False}
    if district:
        f["districts"] = district
    e = mongo.db().events.find_one(f)
    if not e:
        raise NotFound("Event not found (curated festivals cannot be edited here).")
    return e


def update(event_id: str, body: dict, district: str | None, actor: str) -> dict:
    e = get_scoped(event_id, district)
    merged = {**e, **{k: v for k, v in body.items() if v is not None}}
    doc = _validate(merged, e["districts"][0]) | {"updated_at": mongo.now()}
    doc["search_text"] = search_text({**e, **doc})
    mongo.db().events.update_one({"id": event_id}, {"$set": doc})
    _changed()
    mongo.audit(actor, "event.updated", event_id, doc["name"], e["districts"][0])
    return public(mongo.db().events.find_one({"id": event_id}))


def delete(event_id: str, district: str | None, actor: str) -> None:
    e = get_scoped(event_id, district)
    mongo.db().events.delete_one({"id": event_id})
    _changed()
    mongo.audit(actor, "event.deleted", event_id, e["name"], e["districts"][0])


def list_scoped(district: str | None) -> dict:
    f: dict = {"curated": False}
    if district:
        f["districts"] = district
    items = [public(e) for e in mongo.db().events.find(f).sort("start_date", -1)]
    return {"items": items, "total": len(items)}


def _changed() -> None:
    from . import destinations

    destinations.invalidate_list()
