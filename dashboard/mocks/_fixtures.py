"""Frontend mock fixtures.

    python mocks/_fixtures.py            # rebuild derived files only
    python mocks/_fixtures.py --refresh  # re-capture every mock from the live API first

Captured files (exact live response shapes, from API_BASE_URL):
  health.json, forecast_week.json, attrition_scores.json, rescore_sunita.json,
  loop_run.json, roster_baseline.json, roster_protected.json, tasks.json,
  metrics_overview.json, demo_clock.json, voice_ingest.json

Derived files (no endpoint serves these):
  hero_display_names.json  H90x -> scripted demo name (confirmed by each hero's driver pattern)
  playbook.json            driver -> actions, collected from the live `actions` field
  heroes.json              12-week trajectories ILLUSTRATIVE, anchored to the live current score.
                           Replace with the repo's ml/data/mocks/heroes.json when available
                           (api_client prefers that file automatically).
  roster_infeasible.json   example of an infeasible solve, to rehearse the honest-solver UI.

--refresh side effects on the backend: POST /loop/run (idempotent task keys) and
reads only otherwise. It never calls /demo/reset.
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent
BASE = os.getenv("API_BASE_URL", "https://hospitality-management-9jdk.onrender.com").rstrip("/")
HERO_NAMES = {"H901": "Sunita", "H902": "Rajesh", "H903": "Meena", "H904": "Arun", "H905": "Deepak"}
HERO_STORIES = {
    "H901": "Senior housekeeper with sustained overtime and weeks without a weekend off; risk has been rising.",
    "H902": "Strong performer whose progression has stalled: a long time since a raise or new responsibility.",
    "H903": "Paid noticeably below the role average for comparable work.",
    "H904": "Seasonal staff whose contract is ending: a renewal decision, not a resignation prediction.",
    "H905": "Healthy control case: balanced hours, regular offs, no active risk drivers.",
}
DRIVER_EXPLANATIONS = {
    "overtime_overload": ("Overtime overload", "supported",
                          "Sustained overtime over recent weeks, often without a weekend off."),
    "stalled_progression": ("Stalled progression", "supported",
                            "A long time since the last raise or new responsibility while task scores stay good."),
    "low_engagement": ("Low engagement", "supported", "Pulse scores are low or falling against the person's own baseline."),
    "pay_gap": ("Pay gap", "supported", "Pay is below the average for the same role at this property."),
    "clustered_leave_burnout": ("Clustered-leave burnout", "weakly_supported",
                                "Little leave or short clustered leave and no weekend offs. Weakly supported: the data "
                                "encodes this only partially, so treat it as a hint, not a finding."),
    "season_end_exit": ("Season-end exit", "supported",
                        "Seasonal contract is ending. Banded by a contract-date rule, not by the resignation model."),
    "manager_relationship": ("Manager relationship", "unsupported",
                             "Unsupported: the current data has no manager signal, so this driver cannot be detected."),
}


def write(name: str, data) -> None:
    (OUT / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("wrote", name)


def refresh() -> None:
    import requests

    s = requests.Session()

    def call(method: str, path: str, **kw):
        r = s.request(method, BASE + path, timeout=120, **kw)
        r.raise_for_status()
        return r.json()

    write("health.json", call("GET", "/health"))
    scores = call("POST", "/attrition/score", json={})
    write("attrition_scores.json", scores)
    week = date.fromisoformat(scores[0]["week_start"])
    write("forecast_week.json", call("GET", "/forecast", params={"from": week.isoformat(), "to": (week + timedelta(days=7)).isoformat()}))
    write("rescore_sunita.json", call("POST", "/attrition/rescore", json={"employee_id": "H901", "protected_weekends_off": 2}))
    loop = call("POST", "/loop/run")
    write("loop_run.json", loop)
    write("roster_baseline.json", call("GET", f"/roster/{loop['baseline_roster_id']}"))
    write("roster_protected.json", call("GET", f"/roster/{loop['protected_roster_id']}"))
    write("tasks.json", call("GET", "/tasks"))
    write("metrics_overview.json", call("GET", "/metrics/overview"))
    write("demo_clock.json", call("GET", "/demo/clock"))
    write("voice_ingest.json", call("POST", "/voice/ingest", json={"file": "clip_01.wav", "create_task": False}))


def build_derived() -> None:
    scores = json.loads((OUT / "attrition_scores.json").read_text(encoding="utf-8"))
    roster = json.loads((OUT / "roster_baseline.json").read_text(encoding="utf-8"))
    dept = {p["employee_id"]: p["department"] for p in roster.get("people", [])}
    by_id = {s["employee_id"]: s for s in scores}
    write("hero_display_names.json", HERO_NAMES)

    actions: dict[str, list[dict]] = {}
    for s in scores:
        for a in s.get("actions", []):
            lst = actions.setdefault(a["driver"], [])
            if all(x["action"] != a["action"] for x in lst):
                lst.append({k: a[k] for k in ("action", "owner", "check_after_weeks", "expected_effect")})
    write("playbook.json", {"source": "collected from live /attrition/score actions", "drivers": {
        cat: {"title": t, "support_level": sup, "explanation": expl, "actions": actions.get(cat, [])}
        for cat, (t, sup, expl) in DRIVER_EXPLANATIONS.items()}})

    week = date.fromisoformat(scores[0]["week_start"])
    heroes = []
    for hid, name in HERO_NAMES.items():
        cur = by_id.get(hid)
        if not cur:
            continue
        g = cur["group_size"]
        weeks = []
        for k in range(12):
            t = k / 11
            ws = week - timedelta(weeks=11 - k)
            if hid == "H901":
                risk, ot, wso = 0.035 + (cur["risk"] - 0.035) * t ** 1.4, 4 + 9.1 * t, 0 if k < 6 else k - 6
            elif hid == "H902":
                risk, ot, wso = cur["risk"] * (0.85 + 0.15 * t), 3.0, 1
            elif hid == "H903":
                risk, ot, wso = cur["risk"] * (1 + 0.04 * math.sin(k)), 2.5, 1
            elif hid == "H904":
                risk, ot, wso = 0.25 + (cur["risk"] - 0.25) * t, 4.0, 2
            else:
                risk, ot, wso = cur["risk"] * (1 + 0.05 * math.sin(k)), 1.0, 1
            if k == 11:
                risk = cur["risk"]
            weeks.append({"week_start": ws.isoformat(), "risk": round(risk, 4), "overtime_hours": round(ot, 1),
                          "weeks_since_weekend_off": wso})
        ranked = sorted(weeks, key=lambda w: w["week_start"])
        for k, w in enumerate(ranked):
            if k == 11:
                w["rank"], w["band"] = cur["rank"], cur["band"]
                continue
            if cur["segment"] == "contract_end":
                w["rank"] = max(1, round(cur["rank"] + 3 * (1 - k / 11)))
                w["band"] = "high" if k >= 9 else "low"
            else:  # approximate rank from the current score table
                others = sorted((s["risk"] for s in scores if s["segment"] == cur["segment"] and s["employee_id"] != hid), reverse=True)
                w["rank"] = 1 + sum(1 for x in others if x > w["risk"])
                w["band"] = "high" if w["rank"] <= math.ceil(0.10 * g) else "watch" if w["rank"] <= math.ceil(0.25 * g) else "low"
        notes = {"H901": {5: "Weekend offs stop", 10: "Christmas / New Year rush begins"},
                 "H904": {9: "Contract end inside 30-day window"}}
        for k, txt in notes.get(hid, {}).items():
            ranked[k]["note"] = txt
        heroes.append({"employee_id": hid, "display_name": name, "story": HERO_STORIES[hid], "department": dept.get(hid),
                       "segment": cur["segment"], "weeks": ranked})
    write("heroes.json", {"week_start": week.isoformat(), "illustrative": True,
                          "note": "Trajectory is an illustrative fixture anchored to the live current score; "
                                  "replace with ml/data/mocks/heroes.json from the repo.", "heroes": heroes})

    inf = {k: v for k, v in roster.items()}
    inf.update(id=0, status="infeasible", objective=None, assignments=[], people=[], coverage=[], violated_soft_goals=[],
               cost={}, causes=[
                   {"department": "security", "date": (week + timedelta(days=5)).isoformat(), "shift": "night", "required": 1, "available": 0,
                    "reason": "No rested guard: both are on approved leave or inside the minimum-rest window."},
                   {"department": "front_office", "date": (week + timedelta(days=6)).isoformat(), "shift": "morning", "required": 2, "available": 1,
                    "reason": "Only one employee with the fo_system skill is available; skill coverage is a hard rule."}])
    write("roster_infeasible.json", inf)


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
    build_derived()
