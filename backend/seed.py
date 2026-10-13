"""Rebuild the hoi_ops MongoDB database (drop every collection, recreate the indexes) and load
the employee snapshot from the SYNTHETIC ml data. python run.py seed

Uses MONGODB_URI / HOI_OPS_DB like the app; with no MONGODB_URI it seeds an in-memory mongomock
database that disappears when this process exits (only useful as a dry run).
"""

from __future__ import annotations

from backend.config import default_settings
from backend.db import drop_all, ensure_indexes, seed
from backend.mongo import database_kind, get_database


def main() -> int:
    settings = default_settings()
    db = get_database(settings)
    drop_all(db)
    ensure_indexes(db)
    n = seed(db, settings.config.data_source)
    print(
        f"seeded {n} employee snapshot documents (SYNTHETIC) into "
        f"{database_kind(settings)} database {settings.database_name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
