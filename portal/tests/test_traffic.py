"""Traffic prediction model, calibration and live providers (fake HTTP; no network, no real keys)."""

import dataclasses
from datetime import datetime, timedelta

import pytest
from hoi_portal import config, miniyaml, mongo
from hoi_portal.scripts import traffic_calibrate
from hoi_portal.services import destinations, traffic, traffic_live

IST = traffic.IST
SAT_NOON = datetime(2026, 10, 17, 12, tzinfo=IST)  # a Saturday
TUE_NOON = datetime(2026, 10, 13, 12, tzinfo=IST)  # a Tuesday


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def tt_incident(icon, desc, delay=None):
    return {
        "type": "Feature",
        "properties": {
            "iconCategory": icon,
            "magnitudeOfDelay": 2,
            "events": [{"description": desc, "code": 1, "iconCategory": icon}],
            "startTime": "2026-10-13T05:00:00Z",
            "from": "Gaurikund",
            "to": "Sonprayag",
            "delay": delay,
            "roadNumbers": ["NH107"],
            "lastReportTime": "2026-10-13T06:00:00Z",
        },
    }


TT_BODY = {"incidents": [tt_incident(6, "Stationary traffic", 600), tt_incident(8, "Closed"), tt_incident(6, "Queuing traffic")]}
FLOW = {"flowSegmentData": {"currentSpeed": 20, "freeFlowSpeed": 40, "roadClosure": False}}


@pytest.fixture
def db(client):
    d = mongo.db()
    for c in ("traffic_cache", "traffic_observations", "traffic_calibration", "weather_cache"):
        d[c].delete_many({})
    d.advisories.delete_many({"destination_id": {"$in": ["kedarnath", "rishikesh", "haridwar", "mussoorie"]}})
    traffic.invalidate_calibration()
    yield d
    traffic.reload_config()


@pytest.fixture
def keys(monkeypatch):
    def set_keys(tomtom=("k1",), here="", providers=()):
        monkeypatch.setattr(
            config,
            "settings",
            dataclasses.replace(config.settings, tomtom_keys=tuple(tomtom), here_key=here, traffic_providers=tuple(providers)),
        )

    return set_keys


def at(dest, when, hours=24, **kw):
    return traffic.predict(dest, hours, now=when, use_live=kw.pop("use_live", False), **kw)


def put_weather(db, dest, when, mm=0.0, snow=0.0, daily_mm=0.0):
    hrs = [(when + timedelta(hours=k)).strftime("%Y-%m-%dT%H:00") for k in range(72)]
    days = sorted({h[:10] for h in hrs})
    data = {
        "hourly": {"time": hrs, "precip_mm": [mm] * 72, "snow_cm": [snow] * 72},
        "daily": [{"date": d, "precip_mm": daily_mm, "snow_cm": 0} for d in days],
        "current": {},
    }
    db.weather_cache.update_one(
        {"destination_id": dest},
        {"$set": {"ok": True, "data": data, "fetched_at": mongo.now(), "expires_at": mongo.now() + timedelta(hours=1)}},
        upsert=True,
    )


# ------------------------------------------------------------------ config
def test_config_reader_matches_pyyaml():
    yaml = pytest.importorskip("yaml")  # PyYAML is only in the dev venv, not a portal dependency
    assert miniyaml.load(traffic.CONFIG_PATH) == yaml.safe_load(traffic.CONFIG_PATH.read_text(encoding="utf-8"))
    assert miniyaml.loads("a: [1, 'x', [2.5, true]]\nb:\n  - q\n  - 3\nc: ~  # note") == {
        "a": [1, "x", [2.5, True]],
        "b": ["q", 3],
        "c": None,
    }
    with pytest.raises(ValueError):
        miniyaml.loads("a: {b: 1}")


def test_bands_and_shape(db):
    assert [traffic.band(v) for v in (0, 34, 35, 59, 60, 79, 80, 100)] == [
        "free",
        "free",
        "moderate",
        "moderate",
        "heavy",
        "heavy",
        "severe",
        "severe",
    ]
    p = at("kedarnath", TUE_NOON, 72)
    assert len(p["hours"]) == 72 and all(0 <= h["index"] <= 100 and h["band"] == traffic.band(h["index"]) for h in p["hours"])
    assert p["label"] == "Predicted, not measured; for planning" and p["corridor"]["type"] == "hill_pilgrim"
    assert p["now"]["delay"] in traffic.CFG["delay_text"].values()
    assert "km/h" not in str(p) and " min" not in p["now"]["delay"]
    bt = p["best_time"]
    assert bt and 6 <= datetime.fromisoformat(bt["start"]).hour <= 16 and "–" in bt["label"]


def test_monotonic_rain_weekend_festival(db):
    dry = at("mussoorie", TUE_NOON)["hours"]
    put_weather(db, "mussoorie", TUE_NOON, mm=6.0, snow=1.0)
    wet = at("mussoorie", TUE_NOON)["hours"]
    assert all(w["index"] >= d["index"] for w, d in zip(wet, dry)) and sum(w["index"] for w in wet) > sum(d["index"] for d in dry)
    db.weather_cache.delete_many({})
    # weekend never lowers: same corridor, Saturday vs Tuesday, hour by hour, with crowd/season held equal
    inp = traffic.Inputs("mussoorie")
    inp.crowd_index = lambda day: 50
    for h in range(24):
        sat = traffic.hour_terms(inp, SAT_NOON.replace(hour=h), None)[0]
        tue = traffic.hour_terms(inp, SAT_NOON.replace(hour=h) - timedelta(days=4), None)[0]
        assert sat >= tue
    # festival: adding a high-impact event the same day never lowers the index
    base = traffic.hour_terms(inp, TUE_NOON, None)[0]
    inp.ctx.events.append(
        {
            "id": "test-fest",
            "name": "Test fair",
            "destination_ids": ["mussoorie"],
            "districts": [],
            "start_date": "2026-10-13",
            "end_date": "2026-10-13",
            "crowd_impact": "high",
        }
    )
    terms = traffic.hour_terms(inp, TUE_NOON, None)
    assert terms[0] >= base and any(k == "event" for k, _, _ in terms[1])


def test_factors_explained(db):
    may_sat = SAT_NOON.replace(month=5, day=16)  # a Saturday in Char Dham season
    put_weather(db, "kedarnath", may_sat + timedelta(hours=4), mm=8.0)
    p = at("kedarnath", may_sat)
    assert "rain expected 4–" in p["factors_text"].lower()  # rain from 4 pm, in plain words
    assert any("char dham" in f["text"].lower() for f in p["factors"]) and len(p["factors"]) <= 4
    assert all(f["text"] and f["text"][0].isupper() for f in p["factors"])


def test_config_driven_weights(db):
    before = at("haridwar", TUE_NOON)["now"]["index"]
    traffic.CFG["season_weight"] = 0
    traffic.CFG["crowd_weight"] = 0
    lower = at("haridwar", TUE_NOON)["now"]["index"]
    traffic.CFG["weekend"]["plains_pilgrim"]["tuesday"] = [[0, 24, 20]]
    assert lower < before and at("haridwar", TUE_NOON)["now"]["index"] == min(100, lower + 20)


def test_kanwar_on_haridwar_corridor(db):
    july = datetime(2026, 7, 21, 12, tzinfo=IST)
    p = at("haridwar", july)
    assert "kanwar" in p["factors_text"].lower()
    assert "kanwar" not in at("mussoorie", july)["factors_text"].lower()


def test_posted_closure_sets_floor(db):
    now = mongo.now()
    db.advisories.insert_one(
        {
            "id": 99001,
            "kind": "road",
            "status": "closed",
            "district": "rudraprayag",
            "destination_id": "kedarnath",
            "title": "Closed",
            "posted_at": now,
            "expires_at": now + timedelta(hours=6),
        }
    )
    p = traffic.predict("kedarnath", 12, use_live=False)
    assert p["hours"][0]["index"] >= traffic.CFG["advisories"]["closed_floor"] and p["hours"][0]["band"] == "severe"
    assert p["hours"][-1]["index"] < p["hours"][0]["index"]  # the closure expires after 6 hours


# ------------------------------------------------------------------ calibration
def test_calibration_needs_enough_observations(db):
    cfg = traffic.CFG
    few = [{"destination_id": "haridwar", "hour": 9, "observed_index": 80, "predicted_index": 40}] * 5
    assert traffic_calibrate.fit(few, cfg)["haridwar"] == {"n": 5, "enough": False}
    many = [{"destination_id": "haridwar", "hour": 9, "observed_index": 80, "predicted_index": 40}] * 40
    r = traffic_calibrate.fit(many, cfg)["haridwar"]
    assert r["enough"] and r["bias"][1] == pytest.approx(
        min(cfg["calibration"]["max_bias"], 40 * 40 / (40 + cfg["calibration"]["ridge_lambda"]))
    )
    assert r["mae_after"] < r["mae_before"]
    # a saved correction is applied to the prediction
    before = at("haridwar", datetime(2026, 10, 13, 9, tzinfo=IST), 1)["now"]["index"]
    db.traffic_calibration.insert_one({"destination_id": "haridwar", "n": 40, "bias": r["bias"]})
    traffic.invalidate_calibration()
    after = at("haridwar", datetime(2026, 10, 13, 9, tzinfo=IST), 1)
    assert after["now"]["index"] > before and after["model"]["calibrated"]


# ------------------------------------------------------------------ live providers
def test_live_tomtom_nowcast_observation_and_cache(db, keys):
    keys()
    calls = []

    def fake(url, params, timeout):
        calls.append((url, params["key"]))
        return FakeResp(200, FLOW if "flowSegment" in url else TT_BODY)

    traffic_live.set_http(fake)
    p = traffic.predict("kedarnath", 24)
    live = p["live"]
    assert live["source"] == "TomTom" and live["credit"] == "Traffic data © TomTom" and live["status"] == "closed"
    assert live["summary"] == "1 road closure, 2 jams" and live["flow"]["ratio"] == 0.5
    assert p["hours"][0]["nowcast"] and p["hours"][0]["index"] >= traffic.CFG["nowcast"]["closed_floor"] and not p["hours"][5]["nowcast"]
    assert "k1" not in str(p)
    obs = db.traffic_observations.find_one({"destination_id": "kedarnath"})
    assert obs["observed_index"] == traffic.CFG["observed_index"]["closed"] and "base" in obs["features"]
    traffic.predict("kedarnath", 24)
    assert len(calls) == 2 and db.traffic_observations.count_documents({}) == 1  # cache hit: no call, no new observation
    det = destinations.detail("kedarnath")["roads"]
    assert det["worst"] == {"status": "closed", "source": "TomTom"} and det["traffic"]["live"]["total"] == 3


def test_failover_on_401_next_key(db, keys):
    keys(tomtom=("bad", "good"))
    used = []

    def fake(url, params, timeout):
        used.append(params["key"])
        return FakeResp(401, {}) if params["key"] == "bad" else FakeResp(200, FLOW if "flowSegment" in url else TT_BODY)

    traffic_live.set_http(fake)
    doc, fresh = traffic_live.get("kedarnath")
    assert fresh and doc["provider"] == "tomtom" and used[:2] == ["bad", "good"]
    assert used[2:] == ["good"]  # the failed key is skipped afterwards (flow call)


def test_no_rotation_on_429_and_breaker(db, keys):
    keys(tomtom=("k1", "k2"))
    used = []
    traffic_live.set_http(lambda url, params, timeout: used.append(params["key"]) or FakeResp(429, {}))
    doc, _ = traffic_live.get("kedarnath")
    assert doc is None and used == ["k1"]  # 429: no second key
    assert any(s["state"] == "paused after a failure" for s in traffic_live.provider_status())
    db.traffic_cache.delete_many({})
    traffic_live.get("kedarnath")
    assert used == ["k1"]  # circuit breaker: TomTom skipped for breaker_minutes


def test_failover_to_here_then_all_down(db, keys):
    keys(tomtom=("k1",), here="h1", providers=("tomtom", "here"))

    def fake(url, params, timeout):
        if "tomtom" in url:
            raise TimeoutError("timed out")
        return FakeResp(
            200,
            {
                "results": [
                    {
                        "incidentDetails": {
                            "type": "construction",
                            "roadClosed": False,
                            "description": {"value": "Road works"},
                            "criticality": "minor",
                        }
                    }
                ]
            },
        )

    traffic_live.set_http(fake)
    p = traffic.predict("rishikesh", 24)
    assert p["live"]["source"] == "HERE" and p["live"]["summary"] == "1 roadworks"
    # every provider down -> prediction alone, never an error
    traffic_live.set_http(lambda url, params, timeout: (_ for _ in ()).throw(OSError("self-signed certificate")))
    db.traffic_cache.delete_many({})
    p = traffic.predict("haridwar", 24)
    assert p["live"] is None and len(p["hours"]) == 24


def test_mapbox_stub_never_active(keys):
    keys(tomtom=(), providers=("mapbox",))
    assert traffic_live.get("kedarnath") == (None, False)
    assert traffic_live.provider_status() == [{"name": "Mapbox", "state": "stub"}]


# ------------------------------------------------------------------ API
def test_api_and_destination_and_itinerary(client, db):
    r = client.get("/api/v1/traffic/kedarnath", params={"hours": 72})
    assert r.status_code == 200 and len(r.json()["hours"]) == 72 and r.json()["live"] is None
    assert client.get("/api/v1/traffic/kedarnath", params={"hours": 100}).status_code == 422
    assert client.get("/api/v1/traffic/nowhere").status_code == 404
    roads = client.get("/api/v1/destinations/kedarnath").json()["roads"]
    assert roads["traffic"]["label"].startswith("Predicted") and len(roads["traffic"]["hours"]) == 24 and roads["live"] is None
    itin = client.get("/api/v1/itineraries").json()["items"][0]["id"]
    stops = client.get(f"/api/v1/itineraries/{itin}").json()["stops"]
    assert all(s["traffic"]["band"] in ("free", "moderate", "heavy", "severe") for s in stops)
