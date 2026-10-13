r"""Fetch BestTime foot-traffic forecasts for the venues in seed/besttime_venues.py into MongoDB (`crowd_forecasts`).

    cd portal
    ..\.venv\Scripts\python.exe -m hoi_portal.scripts.besttime_refresh            # fetch what is missing or older than 7 days
    ..\.venv\Scripts\python.exe -m hoi_portal.scripts.besttime_refresh --dry-run  # show what would be fetched, spend nothing

Reads BESTTIME_API_KEY_PRIVATE and MONGODB_URI from the environment, or from the root .env (values already in the
environment win). Never prints keys or the URI. Each new forecast spends BestTime credits (2 when found, 1 when not):
venues fetched in the last 7 days and venues BestTime could not find are skipped (use --retry-not-found / --force).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


def load_env(path: Path = ROOT_ENV) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched; no credits spent")
    ap.add_argument("--force", action="store_true", help="re-fetch even venues fetched in the last 7 days")
    ap.add_argument("--retry-not-found", action="store_true", help="try venues BestTime did not find before")
    ap.add_argument("--only", action="append", default=[], help="venue key (repeatable)")
    ap.add_argument("--no-env-file", action="store_true", help="do not read the root .env")
    a = ap.parse_args(argv)
    if not a.no_env_file:
        load_env()

    from .. import config, mongo
    from ..seed import besttime_venues
    from ..services import besttime

    besttime_venues.validate()
    s = config.reload()
    if not s.besttime_key:
        print("BESTTIME_API_KEY_PRIVATE is not set: nothing to do.")
        return 1
    mongo.reset()  # connect with the settings just loaded
    print(f"database: {s.db_name} ({'mongomock, in-memory' if s.uses_mongomock else 'MongoDB cluster from MONGODB_URI'})")
    venues = [v for v in besttime_venues.VENUES if not a.only or v["key"] in a.only]
    before = besttime.credits()
    print(f"credits before: {before}")
    mongo.ensure_indexes()
    try:
        counts = besttime.refresh(venues, force=a.force, retry_not_found=a.retry_not_found, dry_run=a.dry_run, say=print)
    except besttime.KeyRejected as e:
        print(f"stopped: {e}")
        return 2
    print(f"result: {counts}")
    print(f"credits after: {besttime.credits()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
