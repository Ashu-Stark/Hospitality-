"""B4: closed loop. Flags come from the scores (nothing hard-coded); tasks are idempotent; every
flagged person gets a baseline-vs-protected comparison; everything is audited."""

from datetime import date

from backend.db import AUDIT, INTERVENTIONS, ROSTERS
from backend.loop import roster_overrides


def test_roster_overrides_follow_the_roster() -> None:
    import pandas as pd

    hist = pd.DataFrame({"employee_id": ["A"] * 4, "week_start": ["w1", "w2", "w3", "w4"],
                         "overtime_hours": [10.0, 10.0, 10.0, 10.0],
                         "weekly_off_skipped": [True, False, True, False],
                         "weeks_since_weekend_off": [1, 2, 3, 4]})
    person = {"employee_id": "A", "overtime_hours": 2.0, "full_weekend_off": True,
              "worked_days": {0, 1, 2, 3}}
    ov = roster_overrides(person, hist, window=10, carry=3)
    assert ov["overtime_hours"] == 2.0
    assert ov["overtime_roll4_mean"] == (10 + 10 + 10 + 2) / 4
    assert ov["overtime_window_mean"] == (40 + 2) / 5
    assert ov["weeks_since_weekend_off"] == 0.0
    assert ov["consecutive_days_worked"] == 3 + 4  # carried-in run continues on Monday
    assert ov["weekly_off_skipped_4w"] == 1.0  # last 3 weeks: F, T, F; this week has an off
    worked_all = {**person, "full_weekend_off": False, "worked_days": {1, 2}}
    assert roster_overrides(worked_all, hist, 10, 3)["weeks_since_weekend_off"] == 5.0


def test_loop_end_to_end(client) -> None:
    r = client.post("/loop/run")
    assert r.status_code == 200, r.text
    b = r.json()
    scores = client.post("/attrition/score", json={}).json()
    expected = sorted(s["employee_id"] for s in scores
                      if s["band"] == "high" and s["segment"] == "resignation")
    assert sorted(b["flagged"]) == expected and expected
    assert len(b["interventions"]) == 2 * len(expected)
    assert {p["employee_id"] for p in b["people"]} == set(expected)
    for p in b["people"]:
        for side in ("baseline", "protected"):
            assert 0 <= p[side]["risk"] <= 1 and p[side]["band"] in {"high", "watch", "low"}
        assert abs(p["risk_change"] - (p["protected"]["risk"] - p["baseline"]["risk"])) < 1e-3
    assert b["totals"]["baseline"]["hard_violations"] == 0
    assert b["totals"]["protected"]["hard_violations"] == 0
    assert "SIMULATION" in b["note"]
    # a rerun never duplicates intervention tasks
    again = client.post("/loop/run").json()
    assert [i["task_id"] for i in again["interventions"]] == [
        i["task_id"] for i in b["interventions"]]
    # deterministic; the rerun is served from the MongoDB roster cache (method cached_db)
    same = lambda t: {k: {x: y for x, y in v.items() if x != "method"} for k, v in t.items()}  # noqa: E731
    assert again["people"] == b["people"] and same(again["totals"]) == same(b["totals"])
    assert {v["method"] for v in again["totals"].values()} == {"cached_db"}
    db = client.app.state.db
    assert db[INTERVENTIONS].count_documents({}) == len(b["interventions"])
    assert db[ROSTERS].count_documents({}) == 4
    actions = set(db[AUDIT].distinct("action"))
    assert {"loop.start", "loop.result", "roster.generate", "task.create"} <= actions
    assert all(date.fromisoformat(i["due_date"]) > date.fromisoformat(b["week_start"])
               for i in b["interventions"])
