"""MongoDB client for the backend (docs/MONGODB.md): one cached client per process.

MONGODB_URI unset or "mongomock://" -> an in-memory mongomock client (development and tests
only; data is lost on restart; one warning is logged). HOI_ENV=production refuses mongomock.
The URI is a secret: it is never logged, printed or returned by the API.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC
from functools import lru_cache

from pymongo.database import Database

from backend.config import MONGOMOCK_URI, Settings

log = logging.getLogger(__name__)
APP_NAME = "hoi-ops-backend"
ENV_VAR, PRODUCTION = "HOI_ENV", "production"


def is_mongomock(uri: str) -> bool:
    return uri.strip() in ("", MONGOMOCK_URI)


def database_kind(settings: Settings) -> str:
    """What /health reports: "mongomock" or "mongodb" (never the URI)."""
    return "mongomock" if is_mongomock(settings.mongodb_uri) else "mongodb"


@lru_cache(maxsize=4)
def client(uri: str):  # noqa: ANN201 - pymongo.MongoClient or mongomock.MongoClient
    if is_mongomock(uri):
        if os.environ.get(ENV_VAR, "").lower() == PRODUCTION:
            raise RuntimeError("HOI_ENV=production needs a real MONGODB_URI, not mongomock")
        import mongomock  # dev / test dependency only

        log.warning("MONGODB_URI not set: using in-memory mongomock (data lost on restart)")
        return mongomock.MongoClient(tz_aware=True)
    from pymongo import MongoClient

    return MongoClient(
        uri, tz_aware=True, tzinfo=UTC, serverSelectionTimeoutMS=8000, appname=APP_NAME
    )


def get_database(settings: Settings) -> Database:
    return client(settings.mongodb_uri)[settings.database_name]
