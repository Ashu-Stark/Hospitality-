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
    "logo_url",
    "cover_photo_url",
    "cover_photo_credit",
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
        "logo_url": None,
        "cover_photo_url": None,
        "cover_photo_credit": "",
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


def put(tid: str, data: dict, actor: str, property_id: str | None = None) -> dict:
    prop = _property(tid, property_id)
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
    return get(tid, prop["id"])


def public(tid: str, property_id: str | None = None) -> dict:
    """The guest-facing subset: no tenant id, no editor, no timestamps."""
    p = get(tid, property_id)
    return {k: p.get(k) for k in PUBLIC_FIELDS}


# ------------------------------------------------------------------ demo (SYNTHETIC)
DEMO_PROFILE = {
    "display_name": "Himsagar Ridge Resort, Mussoorie (fictional)",
    "logo_url": "/shared/brand/himsagar-logo.svg",
    "cover_photo_url": "/shared/photos/mussoorie.jpg",
    "cover_photo_credit": "Photo of Mussoorie (the town, not the fictional resort): Robertyadav44, CC BY-SA 4.0, Wikimedia Commons",
    "welcome": (
        "Namaste and welcome to Himsagar Ridge (a fictional demo resort)! Wrap up warm, enjoy the valley views and "
        "ask me anything about your stay."
    ),
    "checkin_time": "12:00",
    "checkout_time": "11:00",
    "late_checkout": {
        "allowed": True,
        "latest": "14:00",
        "note": "Free until 12:00 and charged after that, subject to availability; the duty manager approves.",
    },
    "wifi": {"network": "Himsagar-Guest", "password_hint": "Printed on the card at your bedside; or ask the front desk (ext. 9)."},
    "contacts": [
        {"label": "Front desk", "extension": "9"},
        {"label": "Room service", "extension": "4"},
        {"label": "Housekeeping", "extension": "5"},
        {"label": "Maintenance", "extension": "6"},
    ],
    "amenities": [
        {"name": "Restaurant (Ridge Kitchen)", "hours": "07:00-22:30", "where": "Ground floor", "note": "Breakfast buffet 07:30-10:30"},
        {"name": "Sun deck (valley view)", "hours": "06:00-19:00", "where": "Terrace, floor 3", "note": "Sunrise tea on request"},
        {"name": "Bonfire", "hours": "19:00-22:00", "where": "Lawn", "note": "Winter evenings, weather permitting; book at the front desk"},
        {"name": "Room service", "hours": "07:00-23:00", "where": "Dial 4", "note": ""},
        {"name": "Room heaters", "hours": "24 hours", "where": "In every room", "note": "Extra blankets via housekeeping"},
        {"name": "Parking", "hours": "24 hours", "where": "Below the main gate", "note": "Free for guests; limited spaces"},
        {"name": "Laundry", "hours": "09:00-18:00", "where": "Via housekeeping", "note": "Same-day if given before 10:00"},
    ],
    "dining": [
        {"item": "Aloo paratha with curd", "price_inr": 180, "veg": True, "hours": "07:00-11:00"},
        {"item": "Poha", "price_inr": 140, "veg": True, "hours": "07:00-11:00"},
        {"item": "Masala omelette with toast", "price_inr": 170, "veg": False, "hours": "07:00-11:00"},
        {"item": "Masala chai", "price_inr": 60, "veg": True, "hours": "07:00-23:00"},
        {"item": "Filter coffee", "price_inr": 90, "veg": True, "hours": "07:00-23:00"},
        {"item": "Maggi noodles", "price_inr": 120, "veg": True, "hours": "07:00-23:00"},
        {"item": "Veg momos (8 pcs)", "price_inr": 160, "veg": True, "hours": "12:00-22:30"},
        {"item": "Chicken momos (8 pcs)", "price_inr": 200, "veg": False, "hours": "12:00-22:30"},
        {"item": "Dal tadka with jeera rice", "price_inr": 320, "veg": True, "hours": "12:00-22:30"},
        {"item": "Kadhai paneer", "price_inr": 380, "veg": True, "hours": "12:00-22:30"},
        {"item": "Garhwali thali", "price_inr": 420, "veg": True, "hours": "12:00-15:00"},
        {"item": "Chicken curry with rice", "price_inr": 450, "veg": False, "hours": "12:00-22:30"},
        {"item": "Tandoori roti", "price_inr": 40, "veg": True, "hours": "12:00-22:30"},
        {"item": "Gulab jamun (2 pcs)", "price_inr": 110, "veg": True, "hours": "12:00-22:30"},
    ],
    "policies": [
        {"title": "Quiet hours", "text": "22:00-07:00. Please keep music and voices low on the balconies and the lawn."},
        {"title": "Smoking", "text": "No smoking inside rooms. A smoking spot is next to the parking."},
        {"title": "Pets", "text": "Pets are not allowed, except service animals."},
        {"title": "Bonfire safety", "text": "Only the staff light and put out the bonfire; children must be with an adult."},
        {
            "title": "Roads in the monsoon",
            "text": "Hill roads can close after heavy rain (July-September); ask the front desk before driving out.",
        },
        {"title": "ID at check-in", "text": "Every guest shows a government photo ID at check-in, as required for hotels."},
    ],
    "nearby": [
        {"name": "Mall Road", "distance_note": "", "tip": "Mussoorie's main promenade; walk it early morning or after sunset."},
        {"name": "Gun Hill", "distance_note": "", "tip": "A ropeway goes up from Mall Road; clear mornings give the best Himalayan views."},
        {"name": "Kempty Falls", "distance_note": "approx. 15 km from Mussoorie town", "tip": "Crowded on summer weekends; go early."},
        {"name": "Landour and Lal Tibba", "distance_note": "", "tip": "Quiet walks and a viewpoint above town; wear good shoes."},
        {"name": "Company Garden", "distance_note": "", "tip": "Gardens and a small lake; easy with children."},
        {"name": "Camel's Back Road", "distance_note": "", "tip": "A level walking road, lovely at sunset."},
    ],
    "faq": [
        {
            "q": "Is breakfast included?",
            "a": "Breakfast is included in room rates booked with breakfast. Please check your booking or ask the front desk.",
        },
        {"q": "Can I get an extra bed?", "a": "Yes, on request, subject to availability. The front desk will confirm the charge."},
        {"q": "Do you arrange taxis?", "a": "Yes. Ask the front desk at least one hour ahead; in snow or heavy rain allow extra time."},
        {"q": "Will it snow?", "a": "Snow is possible on some winter days but never certain; the front desk shares the day's forecast."},
        {"q": "Is there a doctor on call?", "a": "Yes, the front desk can arrange a doctor on call at any hour."},
        {
            "q": "Can I check out late?",
            "a": "Late checkout is possible until 14:00, subject to availability: request it here and the duty manager approves.",
        },
    ],
    "languages": ["en", "hi"],
    "synthetic": True,
}


HOMESTAY_DEMO_PROFILE = {
    "display_name": "Deodar Nest Homestay, Dhanaulti (fictional)",
    "logo_url": None,
    "cover_photo_url": "/shared/photos/dhanaulti.jpg",
    "cover_photo_credit": "Photo of Dhanaulti (the area, not the fictional homestay): SHUVADIP, CC BY-SA 4.0, Wikimedia Commons",
    "welcome": "Namaste! Welcome to Deodar Nest (a fictional demo homestay). We are a small family-run home: just ask for anything.",
    "checkin_time": "12:00",
    "checkout_time": "10:30",
    "late_checkout": {"allowed": True, "latest": "12:00", "note": "If the room is not booked the same day; your host confirms."},
    "wifi": {"network": "DeodarNest", "password_hint": "Ask your host."},
    "contacts": [{"label": "Host", "extension": "1"}, {"label": "Kitchen", "extension": "2"}],
    "amenities": [
        {"name": "Home kitchen", "hours": "07:30-21:30", "where": "Ground floor", "note": "Home-style meals; tell us a few hours ahead"},
        {"name": "Garden and bonfire", "hours": "18:30-21:30", "where": "Back garden", "note": "Winter evenings, weather permitting"},
        {"name": "Parking", "hours": "24 hours", "where": "Beside the gate", "note": "Two cars"},
    ],
    "dining": [
        {"item": "Breakfast (paratha, curd, tea)", "price_inr": 150, "veg": True, "hours": "07:30-10:00"},
        {"item": "Home-style thali", "price_inr": 250, "veg": True, "hours": "12:30-14:30"},
        {"item": "Masala chai", "price_inr": 40, "veg": True, "hours": "07:00-21:00"},
        {"item": "Maggi noodles", "price_inr": 90, "veg": True, "hours": "08:00-21:00"},
    ],
    "policies": [
        {"title": "Quiet hours", "text": "22:00-07:00. This is a family home; please keep voices low."},
        {"title": "Smoking", "text": "No smoking inside the house. The garden is fine."},
        {"title": "ID at check-in", "text": "Every guest shows a government photo ID at check-in."},
    ],
    "nearby": [
        {"name": "Eco Park", "distance_note": "", "tip": "Deodar forest walk; go in the morning."},
        {"name": "Surkanda Devi temple trek", "distance_note": "", "tip": "A steep walk; start early and carry water."},
    ],
    "faq": [
        {"q": "Is breakfast included?", "a": "Only if your booking says so. Otherwise it is charged as on the menu."},
        {"q": "Can you arrange a taxi?", "a": "Yes, ask your host a few hours ahead."},
    ],
    "languages": ["en", "hi"],
    "synthetic": True,
}


def seed_demo(tid: str, property_id: str | None = None, profile: dict | None = None) -> None:
    """Idempotent: creates the SYNTHETIC demo profile only if the property has none."""
    prop = _property(tid, property_id)
    if not prop:
        return
    doc = {**(profile or DEMO_PROFILE), "tenant_id": tid, "property_id": prop["id"], "updated_at": mongo.now(), "updated_by": "seed"}
    mongo.col("hotel_profiles").update_one({"tenant_id": tid, "property_id": prop["id"]}, {"$setOnInsert": doc}, upsert=True)
    src = profile or DEMO_PROFILE
    mongo.col("hotel_profiles").update_one(
        {"tenant_id": tid, "property_id": prop["id"], "cover_photo_url": {"$exists": False}},
        {"$set": {"cover_photo_url": src["cover_photo_url"], "cover_photo_credit": src["cover_photo_credit"]}},
    )
