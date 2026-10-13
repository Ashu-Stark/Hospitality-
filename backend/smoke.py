"""Backend smoke test (B5): a fresh process, a fresh in-memory database, every main endpoint.

health -> forecast -> attrition score -> roster -> closed loop -> task with a reminder (demo
clock sped up so the 50% reminder fires within seconds) -> metrics. Prints each result and exits
1 on the first failure. Always offline: mongomock, never MONGODB_URI (Atlas).
Run from backend/:  python run.py backend-smoke
"""

from __future__ import annotations

import sys
import time
import traceback

from fastapi.testclient import TestClient

from backend.config import MONGOMOCK_URI, make_settings
from backend.main import create_app

REMINDER_WAIT_SECONDS = 8
DEMO_MULTIPLIER = 600


def check(label: str, response, expect: int = 200) -> dict | list:  # noqa: ANN001
    if response.status_code != expect:
        raise AssertionError(f"{label}: HTTP {response.status_code}: {response.text[:400]}")
    print(f"OK  {label}")
    return response.json()


def run() -> None:
    settings = make_settings("hoi_ops_smoke", mock=False, mongodb_uri=MONGOMOCK_URI)
    with TestClient(create_app(settings)) as c:
        h = check("GET /health", c.get("/health"))
        assert h["database"] == "mongomock", h["database"]
        print(f"    models: {[(m['name'], m['version']) for m in h['models']]}")
        f = check("GET /forecast", c.get("/forecast", params={"from": "2029-12-24",
                                                              "to": "2029-12-30"}))
        print(f"    {len(f['days'])} days, mean occupancy "
              f"{sum(d['mean'] for d in f['days']) / len(f['days']):.3f} ({f['band']})")
        s = check("POST /attrition/score", c.post("/attrition/score", json={}))
        high = [x["employee_id"] for x in s if x["band"] == "high"]
        print(f"    {len(s)} employees scored, high band: {high}")
        r = check("POST /roster/generate", c.post("/roster/generate", json={"use_cache": True}))
        print(f"    roster {r['id']} ({r['method']}, {r['status']}): hard violations "
              f"{len(r['hard_violations'])}, overtime {r['cost']['overtime_hours']} h, "
              f"understaffed shifts {r['cost']['understaffed_shifts']}")
        assert not r["hard_violations"], r["hard_violations"]
        loop = check("POST /loop/run", c.post("/loop/run"))
        for p in loop["people"]:
            print(f"    {p['employee_id']}: baseline risk {p['baseline']['risk']} "
                  f"({p['baseline']['band']}) -> protected {p['protected']['risk']} "
                  f"({p['protected']['band']}), change {p['risk_change']:+.4f}")
        check("POST /demo/clock", c.post("/demo/clock", json={"multiplier": DEMO_MULTIPLIER}))
        t = check("POST /tasks", c.post("/tasks", json={
            "idempotency_key": "smoke-1", "title": "AC not working in room 204",
            "assignee": "maintenance head", "supervisor": "general manager",
            "due_in_minutes": 2}), expect=201)
        deadline = time.time() + REMINDER_WAIT_SECONDS
        kinds: list[str] = []
        while time.time() < deadline and "reminder_50" not in kinds:
            time.sleep(0.25)
            task = next(x for x in c.get("/tasks").json() if x["id"] == t["id"])
            kinds = [e["kind"] for e in task["events"]]
        if "reminder_50" not in kinds:
            raise AssertionError(f"no 50% reminder within {REMINDER_WAIT_SECONDS}s: {kinds}")
        print(f"OK  task reminder fired: {kinds}")
        m = check("GET /metrics/overview", c.get("/metrics/overview"))
        print(f"    flagged {m['flagged_count']}, ROI {m['roi_inr']:.0f} INR (ASSUMPTION)")
    print("BACKEND SMOKE OK")


def main() -> int:
    try:
        run()
    except Exception:  # noqa: BLE001 - fail loudly with the traceback
        traceback.print_exc()
        print("BACKEND SMOKE FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
