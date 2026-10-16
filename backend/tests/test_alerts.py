"""Hotel alerts (backend/alerts.py): every rule on hand-made inputs, dedup + cooldown, the
endpoint, and the guardrail fields on the predict endpoints. SYNTHETIC inputs; the weather
fetcher is a fake (tests never call the network)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import mongomock
import pytest

from backend import alerts as A
from backend.config import make_settings
from backend.weather import WeatherDay, WeatherUnavailable, parse

CFG = make_settings(mongodb_uri="mongomock://", hotel="original").config.alerts
SAT = date(2029, 12, 29)


def _day(d: date, mean: float, spread: float = 0.05) -> dict:
    return {"date": d, "mean": mean, "low": mean - spread, "high": mean + spread}


# ------------------------------------------------------------------ rush ahead
def test_rush_fires_on_high_forecast_and_says_why() -> None:
    out = A.rush_rule([_day(SAT, 0.875)], 24, {5: (SAT - timedelta(days=7), 14)}, CFG)
    assert len(out) == 1
    a = out[0]
    assert a.kind == "rush_ahead" and a.dates == [SAT]
    assert "about 21 of 24 rooms" in a.title
    assert "last Saturday 14" in a.reason
    assert a.action and a.severity in ("medium", "high")


def test_rush_fires_on_jump_against_last_week() -> None:
    out = A.rush_rule([_day(SAT, 0.70)], 24, {5: (SAT - timedelta(days=7), 10)}, CFG)
    assert out and "last Saturday 10" in out[0].reason  # 17 vs 10: jump of 7 >= 4


def test_rush_quiet_week_gives_nothing() -> None:
    assert A.rush_rule([_day(SAT, 0.50)], 24, {5: (SAT - timedelta(days=7), 12)}, CFG) == []


def test_rush_full_house_is_high() -> None:
    assert A.rush_rule([_day(SAT, 0.98)], 24, {}, CFG)[0].severity == "high"


# ------------------------------------------------------------------ staff short
def _roster(cov: float, hours: float) -> dict:
    return {"week_start": "2029-12-24", "summary": {
        "coverage": [{"department": "kitchen", "coverage": cov, "required_hours": 200,
                      "scheduled_hours": 200 * cov, "understaffed_hours": hours},
                     {"department": "security", "coverage": 1.0, "required_hours": 100,
                      "scheduled_hours": 100, "understaffed_hours": 0}],
        "violated_soft_goals": [{"goal": "understaffed", "department": "kitchen", "day": 5,
                                 "shift": "evening", "hours_short": hours}]}}


def test_staff_short_fires_below_coverage() -> None:
    out = A.staff_short_rule(_roster(0.85, 30), CFG)
    assert len(out) == 1
    a = out[0]
    assert a.kind == "staff_short" and a.severity == "high"  # 30 h >= two 9 h shifts
    assert "kitchen" in a.title and "kitchen 30 h short" in a.reason
    assert "Sat 29 Dec evening 30 h" in a.reason
    assert a.target == "pages/20_Extra_Staff.py"


def test_staff_short_quiet_when_covered_or_no_plan() -> None:
    assert A.staff_short_rule(_roster(0.99, 1), CFG) == []
    assert A.staff_short_rule(None, CFG) == []


# ------------------------------------------------------------------ cancellations
def _night(mean: float, exp: float, refs: list[str] | None = None) -> dict:
    return {"date": SAT, "mean": mean, "on_books": 20, "top_bookings": refs or [],
            "adjustment": {"expected_cancellations": exp, "expected_rooms": 20 - exp,
                           "low": 15, "high": 20, "source": "base_rate_table"}}


def test_cancellation_fires_on_peak_night() -> None:
    a = A.cancellation_rule([_night(0.9, 3.2)], 24, CFG)[0]
    assert a.kind == "high_cancellation" and "about 3 booked room" in a.title
    assert "waitlist" in a.action and "REAL" in a.data_note and a.confidence == "low"


def test_cancellation_ignores_quiet_nights_and_small_counts() -> None:
    assert A.cancellation_rule([_night(0.5, 5.0)], 24, CFG) == []  # not a peak night
    assert A.cancellation_rule([_night(0.9, 1.0)], 24, CFG) == []  # below 2 rooms


def test_cancellation_names_bookings_to_reconfirm() -> None:
    a = A.cancellation_rule([_night(0.9, 3.0, ["B7", "B2"])], 24, CFG)[0]
    assert "B7, B2" in a.action


# ------------------------------------------------------------------ weather
def test_weather_heavy_rain_is_high_with_impact_note() -> None:
    a = A.weather_rule([WeatherDay(date=SAT, rain_mm=80, snow_cm=0)], CFG)[0]
    assert a.severity == "high" and "heavy rain 80 mm" in a.reason
    assert "roads" in a.reason.lower() and "Mussoorie" in a.title


def test_weather_snow_medium_and_dry_nothing() -> None:
    assert A.weather_rule([WeatherDay(date=SAT, rain_mm=4, snow_cm=7)], CFG)[0].severity == "medium"
    assert A.weather_rule([WeatherDay(date=SAT, rain_mm=10, snow_cm=0)], CFG) == []


def test_weather_parse_open_meteo_payload() -> None:
    days = parse({"daily": {"time": ["2026-10-16"], "precipitation_sum": [12.5],
                            "snowfall_sum": [0.0], "precipitation_probability_max": [80],
                            "weather_code": [63]}})
    assert days[0].rain_mm == 12.5 and days[0].date == date(2026, 10, 16)


# ------------------------------------------------------------------ staff leaving
def _s(eid: str, band: str, hero: bool = False):  # noqa: ANN202
    return SimpleNamespace(employee_id=eid, band=band, is_demo_hero=hero,
                           week_start=date(2029, 12, 24))


def test_leaving_spike_lists_new_ids_only() -> None:
    now = [_s("HS05", "high"), _s("HS12", "high"), _s("H901", "high", hero=True)]
    a = A.leaving_rule(now, [_s("HS05", "high"), _s("HS12", "watch")], CFG)[0]
    assert "2 staff now at high risk" in a.title and "last week 1" in a.title
    assert "new: HS12" in a.reason and "H901" not in a.reason
    assert "not a warning" in a.action


def test_leaving_no_alert_when_flat() -> None:
    assert A.leaving_rule([_s("HS05", "high")], [_s("HS07", "high")], CFG) == []


# ------------------------------------------------------------------ stock out
def test_stock_runs_out_before_delivery() -> None:
    items = [{"id": "towel", "name": "Bath towels", "on_hand": 30, "on_order": 0,
              "per_occ_room": 1.0, "lead_days": 4},
             {"id": "soap", "name": "Soap", "on_hand": 5000, "on_order": 0,
              "per_occ_room": 1.0, "lead_days": 4},
             {"id": "bulb", "name": "Bulbs", "on_hand": 0, "per_occ_room": 0, "lead_days": 2}]
    a = A.stock_rule(items, [0.8] * 7, 24, CFG)[0]  # ~19 towels a day: out on day 1
    assert a.kind == "stock_out" and "Bath towels" in a.title and a.severity == "high"
    assert "Soap" not in a.reason and "Bulbs" not in a.reason


def test_stock_enough_gives_nothing() -> None:
    items = [{"id": "x", "name": "X", "on_hand": 1000, "per_occ_room": 1, "lead_days": 3}]
    assert A.stock_rule(items, [0.8] * 7, 24, CFG) == []


# ------------------------------------------------------------------ dedup + cooldown
def test_dedupe_keeps_the_most_severe() -> None:
    a = A.Alert(id="x", kind="k", severity="medium", title="t", reason="r", action="a")
    b = a.model_copy(update={"severity": "high"})
    assert [x.severity for x in A.dedupe([a, b, a])] == ["high"]


def test_cooldown_notifies_once_then_again_after_cooldown_or_escalation() -> None:
    db = mongomock.MongoClient()["cooldown_test"]
    a = A.Alert(id="rush_ahead:2029-12-29", kind="rush_ahead", severity="medium", title="t",
                reason="r", action="a")
    t0 = datetime(2029, 12, 24, 8, tzinfo=UTC)
    assert A.apply_cooldown(db, [a], 12, t0, "test")[0].notify
    assert not A.apply_cooldown(db, [a], 12, t0 + timedelta(hours=2), "test")[0].notify
    high = a.model_copy(update={"severity": "high"})
    assert A.apply_cooldown(db, [high], 12, t0 + timedelta(hours=3), "test")[0].notify
    assert A.apply_cooldown(db, [high], 12, t0 + timedelta(hours=16), "test")[0].notify
    doc = db[A.ALERT_LOG].find_one({"alert_id": a.id})
    assert doc["times_notified"] == 3 and doc["severity"] == "high" and "id" in doc


# ------------------------------------------------------------------ endpoint
@pytest.fixture()
def wet_client(client):  # noqa: ANN001, ANN201
    client.app.state.weather = lambda: [WeatherDay(date=date(2026, 10, 16), rain_mm=90,
                                                   snow_cm=0)]
    return client


def test_alerts_endpoint_plain_sentences_and_cooldown(wet_client) -> None:
    r = wet_client.get("/alerts")
    assert r.status_code == 200
    body = r.json()
    assert body["synthetic"] and "REAL" in body["note"]
    kinds = {a["kind"] for a in body["alerts"]}
    assert "weather_risk" in kinds
    for a in body["alerts"]:
        assert a["title"] and a["reason"] and a["action"] and a["severity"] in A.RANK
        assert a["notify"]
    assert any("stock-out" in s for s in body["not_checked"])
    again = wet_client.get("/alerts").json()["alerts"]
    assert again and not any(a["notify"] for a in again)  # same alerts inside the cooldown
    sev = [A.RANK[a["severity"]] for a in again]
    assert sev == sorted(sev)  # most severe first


def test_alerts_post_with_inventory_and_bookings(wet_client) -> None:
    items = [{"id": "towel", "name": "Bath towels", "on_hand": 10, "on_order": 0,
              "per_occ_room": 1.0, "lead_days": 5}]
    bookings = [{"booking_ref": f"B{i}", "arrival": "2029-12-28", "booked_on": "2029-12-01",
                 "nights": 2, "deposit_type": "No Deposit", "market_segment": "Online TA"}
                for i in range(3)]
    r = wet_client.post("/alerts", json={"inventory": items, "bookings": bookings})
    assert r.status_code == 200
    body = r.json()
    assert "stock_out" in {a["kind"] for a in body["alerts"]}
    assert not any("stock-out" in s for s in body["not_checked"])


def test_alerts_weather_unavailable_is_reported_not_raised(client) -> None:
    def broken():  # noqa: ANN202
        raise WeatherUnavailable("weather forecast not available (ConnectError)")

    client.app.state.weather = broken
    body = client.get("/alerts").json()
    assert any(s.startswith("weather:") for s in body["not_checked"])


# ------------------------------------------------------------------ guardrail fields
def test_predict_endpoints_carry_confidence_and_checks(client) -> None:
    f = client.get("/forecast", params={"from": "2029-12-24", "to": "2029-12-26"}).json()
    assert f["confidence"] in ("high", "medium", "low")
    names = {c["name"] for c in f["checks"]}
    assert {"model_age", "input_schema", "drift_rows", "output_clip"} <= names
    s = client.post("/attrition/score", json={"employee_ids": ["H901"]}).json()[0]
    assert s["confidence"] in ("medium", "low") and s["checks"] and s["source"] == "model"
    rr = client.post("/attrition/rescore", json={"employee_id": "H901",
                                                 "protected_weekends_off": 2}).json()
    assert rr["checks"] and "SIMULATION" in rr["note"]
    w = client.get("/workload/next-week").json()
    assert w["synthetic"] and w["departments"] and w["checks"]
    c = client.post("/cancellation/score", json={"bookings": [
        {"arrival": "2029-12-28", "booked_on": "2029-12-01", "deposit_type": "No Deposit",
         "market_segment": "Online TA"}, {"arrival": "2029-12-28"}]}).json()
    assert [b["source"] for b in c["bookings"]] == ["model", "base_rate"]
    assert c["fallback_used"] and 0 <= c["bookings"][0]["p_cancel"] <= 1


def test_mock_mode_marks_checks_as_not_run(mock_client) -> None:
    f = mock_client.get("/forecast", params={"from": "2029-12-24", "to": "2029-12-25"}).json()
    assert f["confidence"] == "low" and f["checks"][0]["name"] == "mock_mode"
