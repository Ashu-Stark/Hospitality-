"""The "Based on: ..." line under a staff-leaving estimate (no Streamlit run, no network). SYNTHETIC ids only.

Run: cd dashboard; ..\\.venv\\Scripts\\python.exe -m pytest -q tests/test_based_on.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import models  # noqa: E402

BASE = {"employee_id": "HS05", "week_start": "2026-09-07", "segment": "resignation", "model": "logistic", "risk": 0.1,
        "rank": 1, "group_size": 15, "band": "high", "band_basis": "model_rank", "rank_is_tied": False,
        "is_demo_hero": False, "drivers": [], "actions": []}


def test_live_score_names_its_sources_and_weeks():
    s = models.parse_score({**BASE, "data_source": "live", "weeks_of_history": 6,
                            "data_sources": ["shifts", "jobs", "thank-yous", "check-ins", "HR record"]})
    assert s.data_source == "live" and s.weeks_of_history == 6
    assert models.based_on(s) == "Based on: shifts, jobs, thank-yous, check-ins (6 weeks)"


def test_short_history_says_rough_guess():
    s = models.parse_score({**BASE, "data_source": "live", "weeks_of_history": 1, "data_sources": ["jobs"]})
    assert models.based_on(s) == "Based on: jobs (1 week); only a few weeks so far, so a rough guess"


def test_demo_scores_say_made_up():
    s = models.parse_score(BASE)  # an older API without data_source: treated as demo data
    assert s.data_source == "demo_synthetic"
    assert "made-up" in models.based_on(s)
