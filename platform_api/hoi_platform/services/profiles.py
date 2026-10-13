"""Hotel profile (one per property): what the guest concierge knows. Collection `hotel_profiles`, `{tenant_id, property_id}`.

The profile is the ONLY hotel knowledge the concierge may use (plus the room's own requests and the time), so the
assistant cannot invent timings, prices or policies. It holds no personal data: contacts are desk extensions.
"""

from __future__ import annotations

from .. import mongo
from . import tenants
from .errors import Invalid

PUBLIC_FIELDS = (
    "property_id",
    "display_name",
    "welcome",
    "checkin_time",
    "checkout_time",
    "late_checkout",
    "wifi",
    "contacts",
    "amenities",
    "dining",
    "policies",
    "nearby",
    "faq",
    "languages",
    "synthetic",
)


def _property(tid: str, property_id: str | None = None) -> dict | None:
    props = tenants.properties(tid)
    if property_id:
        return next((p for p in props if p["id"] == property_id), None) or (props[0] if props else None)
    return props[0] if props else None


def default_profile(tid: str, prop: dict | None) -> dict:
    t = tenants.get_tenant(tid)
    name = prop["name"] if prop else t["name"]
    if prop and prop.get("region"):
        name = f"{name}, {prop['region'].split(',')[0]}"
    return {
        "property_id": prop["id"] if prop else None,
        "display_name": name[:80],
        "welcome": "",
        "checkin_time": "12:00",
        "checkout_time": "11:00",
        "late_checkout": {"allowed": True, "latest": "14:00", "note": "Subject to availability; manager approves"},
        "wifi": {"network": "", "password_hint": ""},
        "contacts": [],
        "amenities": [],
        "dining": [],
        "policies": [],
        "nearby": [],
        "faq": [],
        "languages": ["en", "hi"],
        "synthetic": bool(t.get("is_demo")),
        "updated_at": None,
        "updated_by": None,
    }


def get(tid: str, property_id: str | None = None) -> dict:
    """The profile of the tenant's (first) property; a default skeleton (`exists: false`) when none is saved yet."""
    prop = _property(tid, property_id)
    pid = prop["id"] if prop else None
    doc = mongo.find_one("hotel_profiles", {"tenant_id": tid, "property_id": pid})
    if not doc:
        return {**default_profile(tid, prop), "exists": False}
    doc.pop("tenant_id", None)
    return {**default_profile(tid, prop), **doc, "exists": True}


def put(tid: str, data: dict, actor: str) -> dict:
    prop = _property(tid)
    if not prop:
        raise Invalid("Add a property first (Workspace > Properties).")
    fields = {k: v for k, v in data.items() if k in PUBLIC_FIELDS and k != "property_id"}
    fields.update(updated_at=mongo.now(), updated_by=actor)
    mongo.col("hotel_profiles").update_one(
        {"tenant_id": tid, "property_id": prop["id"]},
        {"$set": fields, "$setOnInsert": {"tenant_id": tid, "property_id": prop["id"]}},
        upsert=True,
    )
    tenants.audit(tid, actor, "hotel_profile.updated", prop["id"])
    return get(tid)


def public(tid: str, property_id: str | None = None) -> dict:
    """The guest-facing subset: no tenant id, no editor, no timestamps."""
    p = get(tid, property_id)
    return {k: p.get(k) for k in PUBLIC_FIELDS}


# ------------------------------------------------------------------ demo (SYNTHETIC)
DEMO_PROFILE = {
    "display_name": "Riverside Retreat, Rishikesh (demo)",
    "welcome": "Namaste and welcome! We hope the river breeze helps you rest. Ask me anything about your stay.",
    "checkin_time": "12:00",
    "checkout_time": "11:00",
    "late_checkout": {"allowed": True, "latest": "14:00", "note": "Subject to availability; the duty manager approves."},
    "wifi": {"network": "Riverside-Guest", "password_hint": "Printed on the card at your bedside; or ask the front desk (ext. 9)."},
    "contacts": [
        {"label": "Front desk", "extension": "9"},
        {"label": "Room service", "extension": "4"},
        {"label": "Housekeeping", "extension": "5"},
    ],
    "amenities": [
        {"name": "Restaurant (Ganga View)", "hours": "07:00-22:30", "where": "Ground floor", "note": "Breakfast buffet 07:30-10:30"},
        {"name": "Yoga deck", "hours": "06:00-08:00", "where": "Terrace", "note": "Free morning class at 06:30; mats provided"},
        {"name": "Room service", "hours": "07:00-23:00", "where": "Dial 4", "note": ""},
        {"name": "Parking", "hours": "24 hours", "where": "Behind the main gate", "note": "Free for guests"},
        {"name": "Laundry", "hours": "09:00-18:00", "where": "Via housekeeping", "note": "Same-day if given before 10:00"},
    ],
    "dining": [
        {"item": "Aloo paratha with curd", "price_inr": 180, "veg": True, "hours": "07:00-11:00"},
        {"item": "Poha", "price_inr": 140, "veg": True, "hours": "07:00-11:00"},
        {"item": "Masala chai", "price_inr": 60, "veg": True, "hours": "07:00-23:00"},
        {"item": "Filter coffee", "price_inr": 90, "veg": True, "hours": "07:00-23:00"},
        {"item": "Dal tadka with jeera rice", "price_inr": 320, "veg": True, "hours": "12:00-22:30"},
        {"item": "Paneer butter masala", "price_inr": 380, "veg": True, "hours": "12:00-22:30"},
        {"item": "Tandoori roti", "price_inr": 40, "veg": True, "hours": "12:00-22:30"},
    ],
    "policies": [
        {"title": "Quiet hours", "text": "22:00-07:00. Please keep music and voices low on the balconies."},
        {"title": "Vegetarian property", "text": "The hotel serves vegetarian food only and no alcohol."},
        {"title": "Smoking", "text": "No smoking inside rooms. A smoking spot is near the parking."},
        {"title": "Pets", "text": "Pets are not allowed, except service animals."},
    ],
    "nearby": [
        {"name": "Laxman Jhula", "distance_note": "approx. 2 km", "tip": "Walk across early morning for fewer crowds."},
        {
            "name": "Triveni Ghat (Ganga aarti)",
            "distance_note": "approx. 3 km",
            "tip": "Evening aarti around sunset; reach 30 minutes early.",
        },
        {"name": "Beatles Ashram", "distance_note": "approx. 2.5 km", "tip": "Open daytime; carry water."},
    ],
    "faq": [
        {
            "q": "Is breakfast included?",
            "a": "Breakfast is included in room rates booked with breakfast. Please check your booking or ask the front desk.",
        },
        {"q": "Can I get an extra bed?", "a": "Yes, on request, subject to availability. The front desk will confirm the charge."},
        {"q": "Do you arrange taxis?", "a": "Yes. Ask the front desk at least one hour ahead."},
        {"q": "Is there a doctor on call?", "a": "Yes, the front desk can arrange a doctor on call at any hour."},
    ],
    "languages": ["en", "hi"],
    "synthetic": True,
}


def seed_demo(tid: str) -> None:
    """Idempotent: creates the SYNTHETIC demo profile only if the property has none."""
    prop = _property(tid)
    if not prop:
        return
    doc = {**DEMO_PROFILE, "tenant_id": tid, "property_id": prop["id"], "updated_at": mongo.now(), "updated_by": "seed"}
    mongo.col("hotel_profiles").update_one({"tenant_id": tid, "property_id": prop["id"]}, {"$setOnInsert": doc}, upsert=True)
