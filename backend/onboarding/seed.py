"""The three SYNTHETIC demo properties (onboarding.yaml demo_properties), created through the
real template path: start (hotel type) -> owner edits (name, rooms, location) -> confirm with
every legal field acknowledged. Run by /demo/reset and at startup when no demo property exists.
"""

from __future__ import annotations

from pymongo.database import Database

from backend.db import PROPERTIES
from backend.onboarding import service
from backend.onboarding.config import OnboardingConfig
from backend.onboarding.schema import LEGAL_FIELDS

DEMO_SOURCE = "demo_seed (SYNTHETIC)"


def seed_demo_properties(db: Database, cfg: OnboardingConfig) -> list[str]:
    """Create the demo properties; returns their property ids."""
    ids = []
    for d in cfg.demo_properties:
        s = service.start(db, service.StartRequest(hotel_type=d.hotel_type, language="en",
                                                   hotel_name=d.hotel_name), cfg, DEMO_SOURCE)
        for field, value in (("rooms", d.rooms), ("location", d.location)):
            service.edit(db, service.FieldEdit(session_id=s.session_id, field=field,
                                               value=value), cfg, DEMO_SOURCE)
        out = service.confirm(db, service.ConfirmRequest(
            session=s.session_id, acknowledged_legal_fields=list(LEGAL_FIELDS)), cfg,
            DEMO_SOURCE, demo=True)
        ids.append(out.property_id)
    return ids


def ensure_demo_properties(db: Database, cfg: OnboardingConfig) -> list[str]:
    if db[PROPERTIES].find_one({"demo": True}, {"_id": 1}) is not None:
        return []
    return seed_demo_properties(db, cfg)
