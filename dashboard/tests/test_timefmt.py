"""Hotel local time (IST) for API timestamps on the Jobs, Guest requests and Stock pages. No network.

Run: cd dashboard; ..\\.venv\\Scripts\\python.exe -m pytest -q tests/test_timefmt.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import timefmt  # noqa: E402


def test_utc_server_clock_is_shown_in_ist(monkeypatch):
    monkeypatch.setenv("HOI_API_UTC_OFFSET_MINUTES", "0")  # the API runs in UTC (e.g. Render)
    assert timefmt.hhmm("2026-10-14T00:55:12") == "06:25"
    assert timefmt.hhmm("2026-10-14T00:55:12", seconds=True) == "06:25:12"
    assert timefmt.stamp("2026-10-13T20:00:00") == "2026-10-14 01:30"  # crosses midnight into the hotel's next day


def test_offsets_and_plain_clock_values(monkeypatch):
    monkeypatch.setenv("HOI_API_UTC_OFFSET_MINUTES", "0")
    assert timefmt.hhmm("2026-10-14T06:25:00+05:30") == "06:25"  # already local: unchanged
    assert timefmt.hhmm("2026-10-14T00:55:00Z") == "06:25"
    assert timefmt.hhmm("10:45") == "10:45"  # a wall-clock time (checkout time) is not converted
    assert timefmt.hhmm(None) == "" and timefmt.stamp("") == ""


def test_api_in_ist_is_not_shifted(monkeypatch):
    monkeypatch.setenv("HOI_API_UTC_OFFSET_MINUTES", "330")
    assert timefmt.hhmm("2026-10-14T06:25:00") == "06:25"
