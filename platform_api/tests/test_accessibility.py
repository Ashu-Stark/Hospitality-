"""Accessibility gate for the guest QR page and the staff app: axe-core (WCAG 2.1 A/AA) in headless Chrome/Edge at phone
size, 44 x 44 px touch targets, Hindi text marked lang="hi" (WCAG 3.1.2) and the "Request sent" status message reaching
screen readers (WCAG 4.1.3). tests/a11y/audit.mjs does the browser work; this test serves the app on a free port and
fails if any page has a problem.

Skipped (not failed) where it cannot run: no Node 22+, no `npm ci --prefix tests/a11y`, or no Chrome/Edge.
"""

import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
from conftest import auth

A11Y = Path(__file__).resolve().parent / "a11y"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(client):
    """The same app and in-memory database as the other tests, served over real HTTP for the browser."""
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def test_guest_and_staff_pages_have_no_accessibility_violations(client, live_server):
    node = shutil.which("node")
    if not node or not (A11Y / "node_modules" / "axe-core").exists():
        pytest.skip("needs Node 22+ and `npm ci --prefix platform_api/tests/a11y`")
    owner = auth(client, "demo.owner")
    token = next(r["guest_token"] for r in client.get("/rooms", headers=owner).json()["rooms"] if r["status"] == "occupied")
    run = subprocess.run(
        [node, "audit.mjs", live_server, f"guest:{token}", "worker-login", "worker-demo"],
        cwd=A11Y,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if run.returncode == 2:
        pytest.skip(run.stderr.strip())
    assert run.returncode == 0, run.stderr[-2000:]
    pages = json.loads(run.stdout)

    assert {"guest/ask", "guest/explore", "guest/requests", "guest/checkout", "worker/sign-in", "worker/jobs"} <= set(pages)
    problems = {
        page: {
            "axe": [f"{v['id']} x{v['nodes']}: {v['targets'][:3]}" for v in r["violations"]],
            "small": r["small_targets"],
            "hindi_without_lang": r["wrong_lang"],
        }
        for page, r in pages.items()
        if r.get("violations") or r.get("small_targets") or r.get("wrong_lang")
    }
    assert not problems, json.dumps(problems, indent=1, ensure_ascii=False)
    assert "Request sent" in pages["guest/request sent"]["announced"]
