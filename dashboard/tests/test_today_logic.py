"""Pure logic behind the Today page (no Streamlit run, no network). SYNTHETIC ids only.

Run: cd dashboard; ..\\.venv\\Scripts\\python.exe -m pytest -q tests/test_today_logic.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import api_client, today  # noqa: E402


def test_uncovered_flags_waiting_jobs_with_nobody_of_that_team_on_shift():
    working = {"HS19": "security", "HS20": "security"}
    jobs = [
        {"department": "housekeeping", "status": "unassigned"},
        {"department": "housekeeping", "status": "new"},
        {"department": "security", "status": "unassigned"},  # security is on shift: not a gap
        {"department": "maintenance", "status": "in_progress"},  # someone already has it
    ]
    assert today.uncovered(working, jobs) == [("housekeeping", 2)]
    assert today.uncovered({"HS05": "housekeeping", "HS19": "security"}, jobs) == []
    assert today.on_shift_mix(working) == "security only"
    assert today.on_shift_mix({"a": "housekeeping", "b": "housekeeping", "c": "security"}) == "housekeeping 2, security 1"


def test_action_result_says_when_a_staffing_request_is_still_not_sent():
    msg, ok = today.action_result({"status": "pending_send", "openings": 1, "last_error": "The tourism portal could not be reached (ReadTimeout)."})
    assert not ok and msg.startswith("Still not sent: ") and "ReadTimeout" in msg
    assert today.action_result({"status": "sent", "openings": 1}) == ("Sent to the tourism portal.", True)
    assert today.action_result(None) == ("Done", True)


def test_ops_key_is_sent_only_to_our_own_ops_api(monkeypatch):
    monkeypatch.setenv("HOI_OPS_API_KEY", "test-only-key")
    monkeypatch.setenv("API_BASE_URL", "https://ops.example.test")
    assert api_client._auth_headers("https://ops.example.test") == {"X-HOI-Key": "test-only-key"}
    assert api_client._auth_headers("https://hoi-ops.onrender.com") == {"X-HOI-Key": "test-only-key"}
    assert api_client._auth_headers("http://127.0.0.1:8000") == {"X-HOI-Key": "test-only-key"}
    assert api_client._auth_headers("https://someone-else.example.org") == {}  # a workspace's own "Server address"
    monkeypatch.delenv("HOI_OPS_API_KEY")
    assert api_client._auth_headers("https://ops.example.test") == {}
