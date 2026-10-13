"""MongoDB access (docs/MONGODB.md): one cached client per process, database `hoi_portal`, mongomock fallback for dev/tests.

Never log the URI. Never return `_id` to clients (use `clean()`).
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from pymongo import ASCENDING, DESCENDING, ReturnDocument

from . import config

log = logging.getLogger("hoi.portal.mongo")
_LOCK = threading.Lock()
_CLIENT = None
# Bumped by reset(); in-process caches include it in their key so they never serve data from a previous database.
generation = 0


def client():
    global _CLIENT
    with _LOCK:
        if _CLIENT is None:
            s = config.settings
            if s.uses_mongomock:
                import mongomock

                log.warning("MONGODB_URI is not set (or is mongomock://): using an in-memory mongomock database. Data is lost on restart.")
                _CLIENT = mongomock.MongoClient(tz_aware=True, tzinfo=UTC)
            else:
                from pymongo import MongoClient

                _CLIENT = MongoClient(s.mongodb_uri, tz_aware=True, tzinfo=UTC, serverSelectionTimeoutMS=8000, appname="hoi-portal")
        return _CLIENT


def db():
    return client()[config.settings.db_name]


def reset() -> None:
    """Drop the cached client (tests: next call gets a fresh mongomock database)."""
    global _CLIENT, generation
    with _LOCK:
        if _CLIENT is not None:
            try:
                _CLIENT.close()
            except Exception:  # noqa: BLE001
                pass
        _CLIENT = None
        generation += 1


def now() -> datetime:
    return datetime.now(UTC)


def aware(dt: datetime | None) -> datetime | None:
    """mongomock may hand back naive or fixed-offset datetimes; normalise to aware UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def iso(dt: datetime | None) -> str | None:
    dt = aware(dt)
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def clean(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def next_seq(name: str) -> int:
    r = db().counters.find_one_and_update({"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return int(r["seq"])


def audit(actor: str, action: str, target: str = "", detail: str = "", district: str | None = None) -> None:
    db().audit_log.insert_one(
        {"ts": now(), "actor": actor, "action": action, "target": target, "detail": detail[:500], "district": district}
    )


def ensure_indexes(d=None) -> None:
    d = d if d is not None else db()
    d.users.create_index("id", unique=True)
    d.users.create_index("username_lc", unique=True)
    d.refresh_tokens.create_index("token_hash", unique=True)
    d.refresh_tokens.create_index("user_id")
    d.districts.create_index("id", unique=True)
    d.destinations.create_index("id", unique=True)
    d.destinations.create_index("district")
    d.businesses.create_index("id", unique=True)
    d.businesses.create_index("reg_no", unique=True)
    d.businesses.create_index([("district", ASCENDING), ("type", ASCENDING), ("status", ASCENDING)])
    d.businesses.create_index("destination_id")
    d.businesses.create_index("owner_user_id")
    d.businesses.create_index("name_lc")
    d.occupancy.create_index([("business_id", ASCENDING), ("month", ASCENDING)], unique=True)
    d.occupancy_agg.create_index([("destination_id", ASCENDING), ("stay_type", ASCENDING), ("month", ASCENDING)], unique=True)
    d.workforce.create_index([("business_id", ASCENDING), ("month", ASCENDING)], unique=True)
    d.workforce.create_index([("district", ASCENDING), ("month", ASCENDING)])
    d.applications.create_index("id", unique=True)
    d.applications.create_index([("district", ASCENDING), ("status", ASCENDING)])
    d.applications.create_index("owner_user_id")
    d.grievances.create_index("ticket_id", unique=True)
    d.grievances.create_index([("district", ASCENDING), ("status", ASCENDING)])
    d.advisories.create_index("id", unique=True)
    d.advisories.create_index([("district", ASCENDING), ("expires_at", DESCENDING)])
    d.events.create_index("id", unique=True)
    d.dictionary.create_index("id", unique=True)
    d.rules.create_index("id", unique=True)
    d.helplines.create_index("id", unique=True)
    d.api_keys.create_index("id", unique=True)
    d.api_keys.create_index("key_hash", unique=True)
    d.api_keys.create_index("business_id")
    d.arrivals.create_index([("district", ASCENDING), ("year", ASCENDING)], unique=True)
    d.weather_cache.create_index("destination_id", unique=True)
    d.crowd_forecasts.create_index("key", unique=True)
    d.crowd_forecasts.create_index("destination_id")
    d.map_tiles.create_index("key", unique=True)
    d.traffic_cache.create_index("destination_id", unique=True)
    d.traffic_observations.create_index([("destination_id", ASCENDING), ("ts", DESCENDING)])
    d.traffic_calibration.create_index("destination_id", unique=True)
    d.places_cache.create_index([("destination_id", ASCENDING), ("category", ASCENDING)], unique=True)
    d.audit_log.create_index([("ts", DESCENDING)])
    # Hiring board.
    d.seeker_profiles.create_index("code", unique=True)
    d.seeker_profiles.create_index("user_id", unique=True, sparse=True)  # synthetic seed profiles have no user_id
    d.seeker_profiles.create_index([("visibility", ASCENDING), ("skill_keys", ASCENDING)])
    d.job_posts.create_index("id", unique=True)
    d.job_posts.create_index([("status", ASCENDING), ("closes_on", ASCENDING), ("district", ASCENDING)])
    d.job_posts.create_index("owner_user_id")
    d.job_applications.create_index("id", unique=True)
    d.job_applications.create_index([("job_id", ASCENDING), ("candidate_id", ASCENDING)], unique=True)
    d.job_applications.create_index("seeker_user_id")
    d.job_applications.create_index([("owner_user_id", ASCENDING), ("candidate_id", ASCENDING)])
    d.interest_requests.create_index("id", unique=True)
    d.interest_requests.create_index([("owner_user_id", ASCENDING), ("candidate_id", ASCENDING)], unique=True)
    d.interest_requests.create_index("seeker_user_id")
    d.job_shortlist.create_index([("owner_user_id", ASCENDING), ("candidate_id", ASCENDING)], unique=True)
    d.job_messages.create_index([("thread_id", ASCENDING), ("created_at", ASCENDING)])
    d.job_posts.create_index([("business_id", ASCENDING), ("staffing_request.source_id", ASCENDING)])
    # Community: local experiences + join requests, staffing agencies' offers, responses and notifications.
    d.local_experiences.create_index("id", unique=True)
    d.local_experiences.create_index([("status", ASCENDING), ("destination_id", ASCENDING)])
    d.local_experiences.create_index("host_business_id")
    d.experience_requests.create_index("id", unique=True)
    d.experience_requests.create_index([("owner_user_id", ASCENDING), ("status", ASCENDING)])
    d.staffing_offers.create_index("id", unique=True)
    d.staffing_offers.create_index([("status", ASCENDING), ("available_to", ASCENDING)])
    d.staffing_responses.create_index("id", unique=True)
    d.staffing_responses.create_index([("job_id", ASCENDING), ("agency_business_id", ASCENDING)], unique=True)
    d.notifications.create_index("id", unique=True)
    d.notifications.create_index([("user_id", ASCENDING), ("read", ASCENDING), ("created_at", DESCENDING)])
