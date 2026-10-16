"""Live staff signals -> attrition features (ml/attrition/live_signals.py). All records here are
SYNTHETIC test values written for the test; staff are ids only."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from ml.attrition import api, guarded
from ml.attrition import features as F
from ml.attrition.features import MODEL_FEATURES
from ml.attrition.live_signals import (
    LiveSignals,
    StaffProfile,
    WeekRecord,
    live_week_frame,
    load_live_config,
    role_code,
    task_score,
    training_means,
)

HOTEL = Path(__file__).resolve().parents[1] / "data" / "hotels" / "himsagar" / "hotel.json"
W0 = date(2026, 8, 3)  # a Monday


def _profile(e: str = "HS05", **kw) -> StaffProfile:
    base = {"employee_id": e, "department": "housekeeping", "role_title": "Housekeeping attendant",
            "joining_date": date(2024, 3, 1), "pay_band": "at", "last_raise_date": date(2025, 9, 1)}
    return StaffProfile(**{**base, **kw})


def _week(e: str, k: int, days: list[int] | None = None, **kw) -> WeekRecord:
    days = [0, 1, 2, 3, 4, 5] if days is None else days
    base = {"employee_id": e, "week_start": W0 + timedelta(weeks=k), "roster_published": True,
            "worked_days": days, "shift_hours": 9.0 * len(days), "jobs_done": 4,
            "jobs_on_time": 4, "jobs_offered": 4, "median_response_seconds": 8, "pulse": "ok"}
    return WeekRecord(**{**base, **kw})


def _team(weeks: int = 6) -> LiveSignals:
    people = [_profile("HS04"), _profile("HS05"), _profile("HS06", contract_type="seasonal",
                                                            contract_end_date=date(2026, 10, 31))]
    recs = [_week(p.employee_id, k) for p in people for k in range(weeks)]
    return LiveSignals(profiles=people, records=recs, leave_marks_used=True, festival_dates=[])


def _row(frame, e: str) -> pd.Series:
    return frame.rows.set_index("employee_id").loc[e]


def test_role_titles_of_the_demo_hotel_map_to_its_role_codes():
    lc = load_live_config()
    for s in json.loads(HOTEL.read_text("utf-8"))["staff"]:
        if s["department"] in lc["role_keywords"]:
            assert role_code(s["department"], s["role_title"], lc) == s["role"], s


def test_same_feature_columns_and_no_gaps():
    frame = live_week_frame(_team())
    assert frame.week_start == W0 + timedelta(weeks=5)
    assert set(MODEL_FEATURES) <= set(frame.rows.columns)
    assert not frame.rows[MODEL_FEATURES].isna().any().any()
    assert sorted(frame.rows["employee_id"]) == ["HS04", "HS05", "HS06"]


def test_roster_counters_overtime_and_load():
    seven = list(range(7))
    live = LiveSignals(profiles=[_profile()], records=[
        _week("HS05", 0, [0, 1, 2, 3, 4]),  # weekend off
        _week("HS05", 1, seven), _week("HS05", 2, seven, late_finish_minutes=120)],
        leave_marks_used=True, festival_dates=[])
    r = _row(live_week_frame(live), "HS05")
    assert r["weeks_since_weekend_off"] == 2
    assert r["consecutive_days_worked"] == 14
    assert r["weekly_off_skipped_4w"] == 2
    assert r["overtime_hours"] == pytest.approx(7 * 9 + 2 - 48)
    assert r["load_ratio"] == pytest.approx((7 * 9 + 2) / 48, abs=1e-3)


def test_leave_mark_breaks_the_run_and_counts_as_leave():
    live = LiveSignals(profiles=[_profile()], records=[
        _week("HS05", 0, list(range(7)), leave_days=[5, 6])], leave_marks_used=True,
        festival_dates=[W0 + timedelta(days=9)])
    r = _row(live_week_frame(live), "HS05")
    assert r["leave_days"] == 2 and r["weeks_since_weekend_off"] == 0
    assert r["consecutive_days_worked"] == 0
    assert r["festival_leave_days_12w"] == 2


def test_task_score_and_pulse_mapping():
    lc = load_live_config()
    best = _week("HS05", 0, jobs_done=5, jobs_on_time=5, jobs_offered=5, median_response_seconds=5)
    assert task_score(best, lc) == pytest.approx(lc["task_score_high"])
    worst = _week("HS05", 0, jobs_done=5, jobs_on_time=0, jobs_offered=5, jobs_declined=5,
                  median_response_seconds=60)
    assert task_score(worst, lc) == pytest.approx(lc["task_score_low"])
    assert pd.isna(task_score(_week("HS05", 0, jobs_done=0), lc))
    live = LiveSignals(profiles=[_profile()], records=[_week("HS05", 0, pulse="hard")],
                       leave_marks_used=True, festival_dates=[])
    assert _row(live_week_frame(live), "HS05")["pulse_score"] == lc["pulse_values"]["hard"]


def test_missing_signals_are_imputed_with_training_means_and_listed():
    means = training_means()
    live = LiveSignals(profiles=[_profile(joining_date=None, pay_withheld=True)], records=[
        _week("HS05", k, pulse=None, jobs_done=0, jobs_on_time=0, jobs_offered=0)
        for k in range(2)], leave_marks_used=False)
    frame = live_week_frame(live)
    r = _row(frame, "HS05")
    for f in ("pulse_score", "task_score_roll4_mean", "tenure_days", "pay_ratio", "leave_days"):
        assert r[f] == pytest.approx(means[f]), f
    signals = {m["signal"] for m in frame.people["HS05"].missing}
    assert {"weekly answers", "jobs", "joining date", "pay (owner / HR only)",
            "leave marks"} <= signals
    assert all("SYNTHETIC" in m["imputed_with"] for m in frame.people["HS05"].missing)


def test_departments_without_a_model_and_people_without_records_are_skipped():
    live = _team(2)
    live.profiles.append(_profile("HS01", department="management", role_title="Hotel manager"))
    live.profiles.append(_profile("HS99"))
    frame = live_week_frame(live)
    assert "management" in frame.skipped["HS01"]
    assert frame.skipped["HS99"] == "no live records yet"


def test_peer_exits_from_leavers():
    live = _team(3)
    live.profiles.append(_profile("HS07", left_on=W0 + timedelta(weeks=1, days=2)))
    live.records.append(_week("HS07", 0))
    r = _row(live_week_frame(live), "HS05")
    assert r["peer_exits"] == 1


def test_score_live_is_live_only_and_short_history_is_low_confidence(monkeypatch):
    def boom(*a, **k):  # the synthetic CSVs must never be read for a live score
        raise AssertionError("synthetic tables read during a live score")

    monkeypatch.setattr(F, "load_tables", boom)
    monkeypatch.setattr(api, "tables_with_heroes", boom)
    scores, skipped = guarded.score_live(_team(2))
    assert len(scores) == 3 and not skipped
    for s in scores:
        assert s.data_source == "live" and s.weeks_of_history == 2
        assert s.confidence == "low"
        assert any(c.name == "short_history" for c in s.checks)
        assert "shifts" in s.data_sources and "jobs" in s.data_sources
        assert 0 <= s.risk <= 1
    long, _ = guarded.score_live(_team(6))
    assert all(not any(c.name == "short_history" for c in s.checks) for s in long)


def test_demo_scores_say_they_are_synthetic():
    s = guarded.score(employee_ids=None)[0]
    assert s.data_source == "demo_synthetic" and s.weeks_of_history is None
