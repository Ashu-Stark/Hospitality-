"""Reseed the REAL cluster's demo data with the FICTIONAL Himsagar Ridge Resort (SYNTHETIC data).

    .venv\\Scripts\\python.exe scripts\\reseed_atlas.py --yes              # hoi_ops + hoi_platform
    .venv\\Scripts\\python.exe scripts\\reseed_atlas.py --yes --platform   # only hoi_platform (e.g. after live tests)

- hoi_ops: the same path as POST /demo/reset (drop every hoi_ops collection, indexes, seed the employee snapshot of the
  hotel dataset HOI_HOTEL_DATA=himsagar, the three onboarding demo properties).
- hoi_platform: deletes ONLY the demo tenant's documents (org_demo; the old "Riverside Retreat" demo hotel) and seeds the
  new demo hotel (hoi_platform.seed.reset_demo + ensure_demo). Other tenants, the platform admin and the audit log stay.
- hoi_portal is never touched.
MONGODB_URI comes from the environment or the root .env and is never printed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "platform_api")]


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def reseed_ops(uri: str) -> None:
    from backend.config import make_settings
    from backend.db import EMPLOYEES, audit, drop_all, ensure_indexes, seed
    from backend.mongo import database_kind, get_database
    from backend.onboarding.config import load_config
    from backend.onboarding.seed import seed_demo_properties

    s = make_settings("hoi_ops", mock=False, mongodb_uri=uri, hotel="himsagar")
    db = get_database(s)
    drop_all(db)
    ensure_indexes(db)
    n = seed(db, s.config.data_source, hotel=s.hotel)
    props = seed_demo_properties(db, load_config())
    audit(db, "demo.reset", {"rows": n, "demo_properties": props, "hotel": s.hotel}, "reseed_atlas")
    ids = sorted(db[EMPLOYEES].distinct("employee_id"))
    print(f"hoi_ops on {database_kind(s)}: {n} employees ({ids[0]}..{ids[-1]}), demo properties {props}")


def reseed_platform(uri: str) -> None:
    os.environ["MONGODB_URI"] = uri
    os.environ["HOI_PLATFORM_DB"] = "hoi_platform"
    os.environ["HOI_SEED_DEMO"] = "true"
    os.environ["HOI_DEMO_LOGIN"] = "true"
    os.environ.pop("HOI_ADMIN_PASSWORD", None)  # never create or change the admin from here
    from hoi_platform import config

    config.reload()
    from hoi_platform import seed

    seed.main(["--reset-demo"])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Reseed hoi_ops / hoi_platform demo data (never hoi_portal).")
    ap.add_argument("--yes", action="store_true", help="really write to the cluster")
    ap.add_argument("--ops", action="store_true")
    ap.add_argument("--platform", action="store_true")
    args = ap.parse_args(argv)
    load_env()
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri or uri.startswith("mongomock"):
        print("MONGODB_URI is not set (or is mongomock://): nothing to reseed.")
        return 1
    if not args.yes:
        print("dry run: add --yes to reseed (hoi_ops and/or hoi_platform demo tenant; never hoi_portal)")
        return 2
    both = not (args.ops or args.platform)
    if both or args.ops:
        reseed_ops(uri)
    if both or args.platform:
        reseed_platform(uri)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
