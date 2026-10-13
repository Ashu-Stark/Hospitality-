"""MongoDB storage for onboarding (docs/MONGODB.md conventions; collections in backend/db.py).

onboarding_session: one per onboarding run. session_id (random, public), property_id (reserved
at start, so every onboarding record carries it), language, status (in_progress |
ready_for_summary | confirmed), draft (the HotelProfile as a dict), flow (asked / answered /
skipped / current), answers (transcript, input kind, extractor, fields filled; NEVER audio),
created_at, updated_at, source. Every read and write filters by session_id or property_id.
"""

from __future__ import annotations

import secrets

from pymongo import ReturnDocument
from pymongo.database import Database

from backend.db import NO_ID, ONBOARDING_SESSIONS, insert, next_ids, utcnow
from backend.onboarding.flow import FlowState
from backend.onboarding.schema import HotelProfile

PROPERTY_COUNTER = "property_id"
PROPERTY_ID_FORMAT = "prop_{:04d}"     # string ids: readable in demos, stable across resets
SESSION_TOKEN_BYTES = 16


class NotFound(LookupError):
    """No onboarding session (or property) with that id."""


def new_property_id(db: Database) -> str:
    return PROPERTY_ID_FORMAT.format(next_ids(db, PROPERTY_COUNTER)[0])


def create_session(db: Database, language: str, draft: HotelProfile, flow: FlowState,
                   source: str, hotel_type_given: bool) -> dict:
    doc = {"session_id": secrets.token_hex(SESSION_TOKEN_BYTES),
           "property_id": new_property_id(db), "language": language, "status": "in_progress",
           "hotel_type_given": hotel_type_given, "draft": draft.model_dump(mode="json"),
           "flow": flow.model_dump(), "answers": [], "updated_at": utcnow()}
    return insert(db, ONBOARDING_SESSIONS, doc, source)


def get_session(db: Database, session_id: str) -> dict:
    doc = db[ONBOARDING_SESSIONS].find_one({"session_id": session_id}, NO_ID)
    if doc is None:
        raise NotFound(f"no onboarding session {session_id!r}")
    return doc


def save_session(db: Database, session: dict, **changes: object) -> dict:
    """Single-document update, filtered by session_id AND property_id; returns the new doc."""
    out = db[ONBOARDING_SESSIONS].find_one_and_update(
        {"session_id": session["session_id"], "property_id": session["property_id"]},
        {"$set": {**changes, "updated_at": utcnow()}}, projection=NO_ID,
        return_document=ReturnDocument.AFTER)
    if out is None:
        raise NotFound(f"no onboarding session {session['session_id']!r}")
    return out


def draft_of(session: dict) -> HotelProfile:
    return HotelProfile.model_validate(session["draft"])


def flow_of(session: dict) -> FlowState:
    return FlowState.model_validate(session["flow"])
