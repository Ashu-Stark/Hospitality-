"""Fixed vocabularies shared by services, seed and the public /meta endpoint."""

from __future__ import annotations

# type key -> (label, code used in UK-<TYPE>-<DISTRICT>-<NNNNN>, capacity unit). Codes are prototype codes, not official.
BUSINESS_TYPES: dict[str, tuple[str, str, str]] = {
    "hotel": ("Hotel", "HTL", "rooms"),
    "homestay": ("Homestay", "HMS", "rooms"),
    "guide": ("Guide", "GDE", "guests per group"),
    "travel_agent": ("Travel agent", "TRA", "staff"),
    "tour_operator": ("Tour operator", "TOP", "guests per departure"),
    "transport": ("Taxi / transport", "TRN", "vehicles"),
    "adventure_operator": ("Adventure operator", "ADV", "guests per day"),
    "restaurant": ("Restaurant", "RST", "seats"),
}
STAY_TYPES = ("hotel", "homestay")
BUSINESS_STATUSES = ("active", "expired", "suspended", "pending")

APPLICATION_STATUSES = ("submitted", "changes_requested", "approved", "rejected")
APPLICATION_KINDS = ("new", "renewal")

# Documents checklist (ticks only, no upload in the prototype). Orientation only, verify with the issuing authority.
CHECKLIST: dict[str, str] = {
    "identity_proof": "Identity proof of the owner or operator",
    "address_proof": "Address proof of the premises or office",
    "property_papers": "Ownership or lease papers",
    "trade_licence": "Trade licence from the local body",
    "fssai": "FSSAI registration / licence (food service)",
    "fire_noc": "Fire safety NOC (larger premises)",
    "guide_training": "Guide licence / training certificate (verify)",
    "adventure_permit": "Adventure activity permit (verify)",
    "vehicle_papers": "Vehicle registration and permits",
}
_COMMON = ["identity_proof", "address_proof", "property_papers"]
REQUIRED_DOCS: dict[str, list[str]] = {
    "hotel": _COMMON + ["trade_licence", "fssai"],
    "homestay": _COMMON,
    "guide": ["identity_proof", "guide_training"],
    "travel_agent": _COMMON + ["trade_licence"],
    "tour_operator": _COMMON + ["trade_licence"],
    "transport": ["identity_proof", "vehicle_papers"],
    "adventure_operator": _COMMON + ["adventure_permit"],
    "restaurant": _COMMON + ["trade_licence", "fssai"],
}

GRIEVANCE_CATEGORIES: dict[str, str] = {
    "overcharging": "Overcharging / price not as displayed",
    "cleanliness": "Cleanliness / hygiene",
    "safety": "Safety concern",
    "misbehaviour": "Misbehaviour by staff or operator",
    "booking": "Booking / cancellation / refund",
    "transport": "Taxi / transport",
    "guide": "Guide / trek services",
    "unregistered": "Unregistered business",
    "other": "Other",
}
GRIEVANCE_STATUSES = ("received", "assigned", "in_progress", "resolved", "closed")
GRIEVANCE_OPEN = ("received", "assigned", "in_progress")
GRIEVANCE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "received": ("assigned", "in_progress", "resolved", "closed"),
    "assigned": ("in_progress", "resolved", "closed"),
    "in_progress": ("resolved", "closed"),
    "resolved": ("closed", "in_progress"),
    "closed": (),
}
GRIEVANCE_SLA_DAYS = 7  # ASSUMED service level for the prototype

ADVISORY_KINDS = ("road", "weather", "general")
ROAD_STATUSES = ("open", "caution", "closed")
CROWD_IMPACTS = ("low", "medium", "high")
ROLES = {"state_admin": "State admin", "district_officer": "District tourism officer", "business": "Business", "job_seeker": "Job seeker"}
LANGUAGES = ("Hindi", "English", "Garhwali", "Kumaoni", "Punjabi", "Bengali", "Nepali")
WORKFORCE_ROLES = ("housekeeping", "front_office", "food_beverage", "maintenance", "other")

# Hiring board.
JOB_APPLICATION_STATUSES = ("applied", "viewed", "shortlisted", "contacted", "not_selected", "withdrawn")
# Business-side transitions (the seeker can only withdraw).
JOB_APPLICATION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "applied": ("viewed", "shortlisted", "contacted", "not_selected"),
    "viewed": ("shortlisted", "contacted", "not_selected"),
    "shortlisted": ("contacted", "not_selected"),
    "contacted": ("not_selected",),
    "not_selected": ("shortlisted",),
    "withdrawn": (),
}
INTEREST_STATUSES = ("pending", "accepted", "declined", "withdrawn")
JOB_STATUSES = ("open", "closed")
JOB_CLOSE_REASONS = ("filled", "withdrawn", "expired")

SYNTHETIC_NOTE = "SYNTHETIC data generated for a hackathon concept prototype. Not official statistics."
