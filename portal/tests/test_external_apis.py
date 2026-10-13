"""BestTime foot traffic and LocationIQ map / nearby places, with fake HTTP (no network, no real keys)."""

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
from hoi_portal import config, mongo
from hoi_portal.scripts import besttime_refresh
from hoi_portal.seed import besttime_venues
from hoi_portal.services import besttime, locationiq

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
KEDARNATH = besttime_venues.BY_KEY["kedarnath-temple"]


def day_raw(di: int) -> list[int]:
    # 6 am .. 5 am: busy afternoon, closed 9 pm - 3 am, quiet early morning (values differ per day)
    return [55, 60, 60, 60, 60, 60, 60, 55, 60, 60, 65, 75, 80, 85, 90 + di, 0, 0, 0, 0, 0, 0, 0, 40, 45]


def ok_body(name="Shri Kedarnath Jyotirlinga Temple") -> dict:
    return {
        "status": "OK",
        "api_key_private": "pri_secret_echo",
        "venue_info": {
            "venue_id": "ven_1",
            "venue_name": name,
            "venue_address": "Kedarnath, Uttarakhand 246445 India",
            "venue_lat": 30.73,
            "venue_lon": 79.07,
        },
        "analysis": [
            {
                "day_info": {"day_int": i, "day_text": "x", "day_mean": 50 + (10 if i == 2 else i)},
                "day_raw": day_raw(i),
                "peak_hours": [],
                "quiet_hours": [],
            }
            for i in range(7)
        ],
    }


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(
        config, "settings", dataclasses.replace(config.settings, besttime_key="pri_secret_echo", locationiq_key="liq_test_key")
    )
    monkeypatch.setattr(locationiq, "MIN_INTERVAL_S", 0.0)


@pytest.fixture
def clean_cache(client):
    d = mongo.db()
    for c in ("crowd_forecasts", "map_tiles", "places_cache"):
        d[c].delete_many({})
    yield d


class FakeResp:
    def __init__(self, status=200, body=None, content=b"", ctype="application/json"):
        self.status_code, self._body, self.content, self.headers = status, body, content, {"content-type": ctype}

    def json(self):
        return self._body


# ------------------------------------------------------------------ BestTime
def test_venue_list_is_valid():
    besttime_venues.validate()
    assert len(besttime_venues.VENUES) <= 20


def test_parse_maps_6am_based_raw_to_clock_hours():
    p = besttime.parse(ok_body())
    assert len(p["by_hour"]) == 7 and all(len(h) == 24 for h in p["by_hour"])
    tue = p["by_hour"][1]
    assert tue[6] == 55 and tue[20] == 91  # 6 am and 8 pm of Tuesday
    assert tue[4] == 40 and tue[5] == 45  # 4-5 am come from Monday's tail
    assert "api_key_private" not in str(p)


def test_summarize_best_window_peak_quiet():
    by_hour = [0] * 4 + [40, 45, 55, 60, 60, 60, 60, 60, 55, 60, 60, 65, 75, 80, 85, 90, 0, 0, 0, 0]
    s = besttime.summarize(by_hour)
    assert s["best_window"] == {"start_hour": 4, "end_hour": 6, "label": "4–6 am"}
    assert s["peak_hours"] == [18, 19] and s["quiet_hours"] == [4, 5]
    assert besttime.window_label(11, 13) == "11 am–1 pm" and besttime.summarize([0] * 24)["best_window"] is None


def test_refresh_fetches_skips_fresh_and_stores_not_found(clean_cache, keys):
    calls = []

    def fake(name, address, key):
        calls.append(name)
        assert key == "pri_secret_echo"
        return (200, ok_body()) if name == "Kedarnath Temple" else (200, {"status": "Error", "message": "Venue not found pri_secret_echo"})

    besttime.set_fetcher(fake)
    venues = [KEDARNATH, besttime_venues.BY_KEY["bhulla-tal"]]
    assert besttime.refresh(venues) == {"fetched": 1, "not_found": 1, "skipped": 0, "errors": 0, "planned": 0}
    docs = {d["key"]: d for d in clean_cache.crowd_forecasts.find()}
    assert docs["kedarnath-temple"]["status"] == "ok" and docs["bhulla-tal"]["status"] == "not_found"
    assert "pri_secret_echo" not in str(docs)  # the echoed key is never stored
    # second run: fresh forecast and the not-found venue are both skipped (no credits spent)
    assert besttime.refresh(venues)["skipped"] == 2 and len(calls) == 2
    # after 7 days the forecast is fetched again; not-found stays skipped unless asked
    clean_cache.crowd_forecasts.update_one({"key": "kedarnath-temple"}, {"$set": {"fetched_at": mongo.now() - timedelta(days=8)}})
    r = besttime.refresh(venues)
    assert r["fetched"] == 1 and r["skipped"] == 1 and len(calls) == 3
    assert besttime.refresh(venues, retry_not_found=True)["not_found"] == 1 and len(calls) == 4


def test_refresh_errors_and_bad_key(clean_cache, keys):
    besttime.set_fetcher(lambda *a: (500, {}))
    assert besttime.refresh([KEDARNATH])["errors"] == 1 and clean_cache.crowd_forecasts.count_documents({}) == 0
    besttime.set_fetcher(lambda *a: (401, {"status": "Error", "message": "bad key"}))
    with pytest.raises(besttime.KeyRejected):
        besttime.refresh([KEDARNATH])
    assert besttime.refresh([KEDARNATH], dry_run=True)["planned"] == 1


def test_refresh_needs_key(clean_cache):
    with pytest.raises(besttime.KeyRejected):
        besttime.refresh([KEDARNATH])
    assert besttime_refresh.main(["--no-env-file", "--dry-run"]) == 1


def test_foot_traffic_in_crowd_response(client, clean_cache, keys):
    assert client.get("/api/v1/destinations/kedarnath/crowd").json()["foot_traffic"] is None  # null path
    besttime.set_fetcher(lambda *a: (200, ok_body()))
    besttime.refresh([KEDARNATH])
    crowd = client.get("/api/v1/destinations/kedarnath/crowd").json()
    ft = crowd["foot_traffic"]
    assert crowd["label"] == "estimate" and crowd["today"]["index"] >= 0  # our estimate is unchanged alongside
    assert ft["source"] == "BestTime" and ft["venue_name"] == "Shri Kedarnath Jyotirlinga Temple"
    assert len(ft["today_by_hour"]) == 24 and ft["note"] == "Forecast of typical foot traffic from BestTime; not a headcount"
    assert ft["best_window"]["label"] and ft["peak_hours"] and ft["quiet_hours"] and ft["busiest_day"] == "Wednesday" and ft["fetched_at"]
    det = client.get("/api/v1/destinations/kedarnath")
    assert "crowd" in det.json(), det.text[:300]
    assert det.json()["crowd"]["foot_traffic"]["venue_name"]
    assert client.get("/api/v1/destinations/badrinath/crowd").json()["foot_traffic"] is None


def test_foot_traffic_uses_ist_weekday(clean_cache, keys):
    besttime.set_fetcher(lambda *a: (200, ok_body()))
    besttime.refresh([KEDARNATH])
    # 2026-10-12 20:00 UTC is Tuesday 01:30 in India
    ft = besttime.foot_traffic("kedarnath", now=datetime(2026, 10, 12, 20, 0, tzinfo=UTC))
    assert ft["day"] == "Tuesday" and ft["today_by_hour"][20] == 91


# ------------------------------------------------------------------ LocationIQ static map
def test_static_map_no_key_is_503_and_map_says_unavailable(client, clean_cache):
    assert client.get("/api/v1/map").json()["static_map"]["available"] is False
    r = client.get("/api/v1/map/static")
    assert r.status_code == 503 and r.headers["content-type"].startswith("application/json")


def test_static_map_proxy_and_cache(client, clean_cache, keys):
    seen = []

    def fake(url, params):
        seen.append((url, params))
        return FakeResp(200, content=PNG, ctype="image/png")

    locationiq.set_http(fake)
    assert client.get("/api/v1/map").json()["static_map"] == {
        "available": True,
        "attribution": "© LocationIQ · © OpenStreetMap contributors",
    }
    r = client.get("/api/v1/map/static", params={"theme": "spiritual"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == PNG
    assert "liq_test_key" not in r.text and "max-age" in r.headers["cache-control"]
    url, params = seen[0]
    assert url == locationiq.STATIC_URL and ("key", "liq_test_key") in params
    markers = dict(params)["markers"]
    assert markers.startswith("icon:") and "30.735,79.067" in markers and "zoom" not in dict(params)  # auto zoom
    assert client.get("/api/v1/map/static", params={"theme": "spiritual"}).content == PNG and len(seen) == 1  # cache hit
    # one destination: explicit centre + zoom
    assert client.get("/api/v1/map/static", params={"district": "champawat", "circuit": ""}).status_code == 200
    assert len(seen) == 2 and dict(seen[1][1])["zoom"] == str(locationiq.MAP_SINGLE_ZOOM) and "center" in dict(seen[1][1])
    assert client.get("/api/v1/map/static", params={"theme": "nope"}).status_code == 422


def test_static_map_upstream_failure_falls_back(client, clean_cache, keys):
    locationiq.set_http(lambda url, params: FakeResp(401, {"error": "Invalid key"}))
    assert client.get("/api/v1/map/static").status_code == 503
    assert clean_cache.map_tiles.find_one({})["ok"] is False  # failure cached briefly
    calls = []
    locationiq.set_http(lambda url, params: calls.append(1) or FakeResp(200, content=PNG, ctype="image/png"))
    assert client.get("/api/v1/map/static").status_code == 503 and not calls  # not retried within the failure TTL


# ------------------------------------------------------------------ LocationIQ nearby places
def nearby_fake(calls):
    def fake(url, params):
        p = dict(params)
        calls.append(p["tag"])
        if p["tag"] == "atm":
            return FakeResp(404, {"error": "Unable to geocode"})
        if p["tag"] == "fuel":
            return FakeResp(500, {"error": "oops"})
        return FakeResp(
            200,
            [
                {"name": "Far " + p["tag"], "lat": "30.80", "lon": "79.10", "type": "x"},
                {"name": "Near " + p["tag"], "lat": "30.736", "lon": "79.068", "type": "x"},
                {"name": "", "lat": "30.74", "lon": "79.07"},
                {"name": "Near " + p["tag"], "lat": "30.736", "lon": "79.068"},
            ],
        )

    return fake


def test_places_no_key_is_graceful(client, clean_cache):
    r = client.get("/api/v1/destinations/kedarnath/places").json()
    assert r["available"] is False and r["groups"] == []


def test_places_grouping_cache_and_errors(client, clean_cache, keys):
    calls = []
    locationiq.set_http(nearby_fake(calls))
    r = client.get("/api/v1/destinations/kedarnath/places").json()
    assert r["available"] and r["attribution"] == "© LocationIQ · © OpenStreetMap contributors"
    cats = [g["category"] for g in r["groups"]]
    assert cats == ["hospital", "pharmacy", "police", "viewpoint", "place_of_worship"]  # atm: none found, fuel: failed
    g = r["groups"][0]
    assert [i["name"] for i in g["items"]] == ["Near hospital", "Far hospital"]  # sorted, unnamed + duplicates dropped
    assert g["items"][0]["distance_km"] < 1 and g["items"][1]["distance_km"] > 5
    assert len(calls) == 7 and "amenity:police" in calls and "tourism:viewpoint" in calls
    client.get("/api/v1/destinations/kedarnath/places")
    assert len(calls) == 7  # everything cached (the failure for 10 minutes, the rest for 7 days)
    assert clean_cache.places_cache.find_one({"category": "atm"})["ok"] is True
    one = client.get("/api/v1/destinations/kedarnath/places", params={"category": "hospital"}).json()
    assert [g["category"] for g in one["groups"]] == ["hospital"]
    assert client.get("/api/v1/destinations/kedarnath/places", params={"category": "casino"}).status_code == 422
    assert client.get("/api/v1/destinations/nowhere/places").status_code == 404


def test_places_budget_leaves_rest_pending(client, clean_cache, keys, monkeypatch):
    monkeypatch.setattr(locationiq, "PLACES_BUDGET_S", -1.0)
    calls = []
    locationiq.set_http(nearby_fake(calls))
    r = client.get("/api/v1/destinations/rishikesh/places").json()
    assert len(calls) == 1 and len(r["pending"]) == 6
