"""Ping the MongoDB cluster in MONGODB_URI (from the environment or the root .env) and list the HOI databases.

    python scripts/check_mongo.py

Never prints the URI or the password.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASES = ("hoi_ops", "hoi_platform", "hoi_portal")


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    load_env()
    uri = os.getenv("MONGODB_URI", "")
    if not uri or uri.startswith("mongomock"):
        print("MONGODB_URI is not set (or is mongomock://): nothing to check.")
        return 1
    from pymongo import MongoClient

    client = MongoClient(uri, serverSelectionTimeoutMS=8000, appname="hoi-check")
    try:
        client.admin.command("ping")
    except Exception as exc:  # report the failure class without the URI
        print(f"FAIL: cannot reach the cluster ({type(exc).__name__}: {str(exc)[:200]})")
        return 1
    host = uri.split("@")[-1].split("/")[0]
    print(f"OK: connected to {host}")
    names = set(client.list_database_names())
    for db in DATABASES:
        if db in names:
            cols = client[db].list_collection_names()
            print(f"  {db}: {len(cols)} collections ({', '.join(sorted(cols)[:12])}{' ...' if len(cols) > 12 else ''})")
        else:
            print(f"  {db}: not created yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
