"""Curated hospitality & tourism skills taxonomy for the hiring board (job seekers and job posts pick from this list).

Keys are stable ids used in MongoDB documents; labels are display text. Categories group related skills (a related
skill in the same category earns partial match credit, see hiring.yaml). This list is our own working taxonomy for
the prototype, not an official occupational classification.
"""

from __future__ import annotations

CATEGORIES: dict[str, str] = {
    "front_office": "Front office & sales",
    "housekeeping": "Housekeeping & laundry",
    "food_beverage": "Food & beverage service",
    "kitchen": "Kitchen",
    "maintenance": "Maintenance",
    "transport": "Transport",
    "adventure": "Guiding & adventure",
    "wellness": "Wellness",
    "operations": "Tours & homestays",
    "admin": "Accounts & admin",
    "security": "Security",
}

# key, label, category, job title used by the seed
_RAW = [
    ("front_office", "Front office / reception", "front_office", "Front office associate"),
    ("reservations_sales", "Sales / reservations", "front_office", "Reservations executive"),
    ("guest_relations", "Guest relations", "front_office", "Guest relations associate"),
    ("housekeeping", "Housekeeping", "housekeeping", "Housekeeping attendant"),
    ("laundry", "Laundry", "housekeeping", "Laundry attendant"),
    ("fb_service", "F&B service (steward / waiter)", "food_beverage", "F&B steward"),
    ("barista", "Barista", "food_beverage", "Barista"),
    ("cook_indian", "Cook / chef: Indian", "kitchen", "Cook (Indian)"),
    ("cook_continental", "Cook / chef: continental", "kitchen", "Cook (continental)"),
    ("cook_pahadi", "Cook / chef: Garhwali / Kumaoni cuisine", "kitchen", "Cook (pahadi cuisine)"),
    ("kitchen_helper", "Kitchen helper", "kitchen", "Kitchen helper"),
    ("baker", "Baker", "kitchen", "Baker"),
    ("maintenance", "Maintenance (general)", "maintenance", "Maintenance technician"),
    ("electrician", "Electrician", "maintenance", "Electrician"),
    ("plumber", "Plumber", "maintenance", "Plumber"),
    ("driver_taxi", "Driver: taxi", "transport", "Taxi driver"),
    ("driver_tempo", "Driver: tempo traveller", "transport", "Tempo traveller driver"),
    ("trek_guide", "Trek guide", "adventure", "Trek guide"),
    ("mountaineering_guide", "Mountaineering guide", "adventure", "Mountaineering guide"),
    ("rafting_guide", "Rafting guide", "adventure", "Rafting guide"),
    ("paragliding_pilot", "Paragliding pilot", "adventure", "Paragliding pilot"),
    ("yoga_instructor", "Yoga instructor", "wellness", "Yoga instructor"),
    ("spa_therapist", "Spa therapist", "wellness", "Spa therapist"),
    ("tour_coordinator", "Tour coordinator", "operations", "Tour coordinator"),
    ("homestay_host", "Homestay host / caretaker", "operations", "Homestay caretaker"),
    ("accountant", "Accountant", "admin", "Accountant"),
    ("security_guard", "Security", "security", "Security guard"),
]

SKILLS: list[dict] = [{"key": k, "label": lbl, "category": c, "title": t} for k, lbl, c, t in _RAW]
BY_KEY: dict[str, dict] = {s["key"]: s for s in SKILLS}

# Languages a job seeker can list (free "Other" for anything else).
LANGUAGES = ("Hindi", "English", "Garhwali", "Kumaoni", "Nepali", "Punjabi", "Bengali", "Jaunsari", "Other")

JOB_TYPES: dict[str, str] = {"seasonal": "Seasonal", "permanent": "Permanent", "part_time": "Part-time"}

# Suggestions shown in the profile form (free text is allowed; everything is self-declared, not verified).
CERTIFICATION_SUGGESTIONS = (
    "Food safety training",
    "First aid",
    "Wilderness first aid",
    "Basic mountaineering course",
    "Swift-water rescue",
    "Commercial driving licence",
    "Yoga teacher training (200 h)",
    "Housekeeping skills course",
    "Accounting software course",
)
