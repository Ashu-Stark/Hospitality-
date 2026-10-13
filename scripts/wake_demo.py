"""Wake every deployed HOI service before a demo and wait until each one answers.

    python scripts/wake_demo.py

Render's free plan puts a service to sleep after about 15 minutes without visitors; the first request then takes
30-60 s. Run this 2-3 minutes before showing anything. It does not keep services awake afterwards (that would use up
the free plan's monthly hours), so run it again if the demo starts much later.
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SERVICES = [
    ("Ops and ML API", "https://hoi-ops.onrender.com/health"),
    ("Platform API (staff app, guest pages)", "https://hoi-platform-api.onrender.com/health"),
    ("Hotel portal", "https://hoi-dashboard.onrender.com/_stcore/health"),
    ("Super-admin portal", "https://hoi-platform-admin.onrender.com/_stcore/health"),
    ("Tourism site", "https://hoi-portal.vercel.app/health"),
    ("Marketing website", "https://hoi-website.vercel.app/"),
]
DEADLINE_S = 180


def wake(name: str, url: str) -> tuple[str, bool, float]:
    start = time.monotonic()
    while time.monotonic() - start < DEADLINE_S:
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                if r.status == 200:
                    return name, True, time.monotonic() - start
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(5)
    return name, False, time.monotonic() - start


def main() -> int:
    print(f"Waking {len(SERVICES)} services (up to {DEADLINE_S} s each)...")
    with ThreadPoolExecutor(len(SERVICES)) as pool:
        results = list(pool.map(lambda s: wake(*s), SERVICES))
    for name, ok, secs in results:
        print(f"  {'ready ' if ok else 'NO ANSWER'}  {secs:5.1f} s  {name}")
    failed = [n for n, ok, _ in results if not ok]
    print("All awake. Start the demo within about 10 minutes." if not failed else f"Not answering: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
