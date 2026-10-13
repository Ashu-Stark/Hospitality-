"""Public modules: search, registry, destinations (mocked weather), crowd bands, dictionary, rules, events."""

import re

import conftest
from conftest import fake_forecast
from hoi_portal import mongo
from hoi_portal.services import crowd, weather

REG = re.compile(r"^UK-[A-Z]{3}-[A-Z]{3}-\d{5}$")


def test_search_returns_grouped_results(client):
    r = client.get("/api/v1/search", params={"q": "kedarnath"})
    assert r.status_code == 200
    body = r.json()
    assert set(body["groups"]) == {"destinations", "businesses", "events", "dictionary", "rules", "advisories"}
    assert body["groups"]["destinations"][0]["id"] == "kedarnath"
    assert body["counts"]["businesses"] > 0 and all("Kedarnath" in b["destination_name"] for b in body["groups"]["businesses"])
    assert any("Char Dham" in e["name"] for e in body["groups"]["events"])
    assert body["total"] == sum(body["counts"].values())


def test_search_is_case_insensitive_multi_token_and_regex_safe(client):
    a = client.get("/api/v1/search", params={"q": "OCCUPANCY rate"}).json()
    assert any(t["id"] == "occupancy-rate" for t in a["groups"]["dictionary"])
    # Regex metacharacters are escaped: ".*" must not match everything.
    r = client.get("/api/v1/search", params={"q": ".* ((["})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get("/api/v1/search", params={"q": "k"}).status_code == 422
    assert client.get("/api/v1/search", params={"q": "x" * 300}).status_code == 422


def test_registry_filters_and_letter_index(client):
    r = client.get("/api/v1/registry", params={"type": "homestay", "district": "rudraprayag", "page_size": 100}).json()
    assert r["total"] > 0 and r["synthetic"] is True
    assert all(b["type"] == "homestay" and b["district"] == "rudraprayag" for b in r["items"])
    exp = client.get("/api/v1/registry", params={"status": "expired", "page_size": 100}).json()
    assert exp["total"] > 0 and all(b["status"] == "expired" for b in exp["items"])
    letter = r["letters"][0]
    by_letter = client.get("/api/v1/registry", params={"letter": letter}).json()
    assert all(b["name"].upper().startswith(letter) for b in by_letter["items"])
    p1 = client.get("/api/v1/registry", params={"page": 1, "page_size": 5}).json()
    p2 = client.get("/api/v1/registry", params={"page": 2, "page_size": 5}).json()
    assert p1["total"] >= 300 and {b["id"] for b in p1["items"]}.isdisjoint({b["id"] for b in p2["items"]})
    assert all("Sample" in b["name"] for b in p1["items"])  # obviously synthetic names
    assert client.get("/api/v1/registry", params={"district": "atlantis"}).status_code == 422


def test_verify_by_registration_number(client):
    b = client.get("/api/v1/registry", params={"status": "active", "page_size": 1}).json()["items"][0]
    assert REG.match(b["reg_no"])
    v = client.get("/api/v1/registry/verify", params={"reg_no": b["reg_no"].lower()}).json()
    assert v["found"] and v["valid"] and v["status"] == "active" and v["business"]["id"] == b["id"]
    assert client.get("/api/v1/registry/verify", params={"reg_no": "UK-HMS-RUD-99999"}).json()["found"] is False
    bad = client.get("/api/v1/registry/verify", params={"reg_no": "hello"}).json()
    assert bad["found"] is False and "Format" in bad["message"]
    detail = client.get(f"/api/v1/registry/{b['reg_no']}")
    assert detail.status_code == 200 and "owner_user_id" not in detail.json() and '"_id"' not in detail.text


def test_destination_detail_with_mocked_weather(client):
    mongo.db().weather_cache.delete_many({})
    conftest.CALLS["n"] = 0
    r = client.get("/api/v1/destinations/kedarnath")
    assert r.status_code == 200
    d = r.json()
    assert d["destination"]["district"] == "rudraprayag" and d["destination"]["altitude_m"] is None
    w = d["weather"]
    assert w["available"] and w["current"]["temperature_c"] == 8.4 and len(w["daily"]) == 7
    assert {x["kind"] for x in w["warnings"]} == {"heavy_rain", "snow"}
    assert "ASSUMED" in w["thresholds"]["note"]
    assert d["crowd"]["label"] == "estimate" and len(d["crowd"]["outlook"]) == 14 and len(d["crowd"]["usual_by_month"]) == 12
    assert any("Gaurikund" in f for f in d["roads"]["facts"]) and "verify" in d["roads"]["facts_note"]
    assert d["nearby"]["stays"]["total"] > 0
    assert any(e["id"] == "char-dham-closing" for e in d["events"])
    # Second call within 30 minutes is served from the weather cache.
    assert client.get("/api/v1/destinations/kedarnath/weather").json()["cached"] is True
    assert conftest.CALLS["n"] == 1
    assert client.get("/api/v1/destinations/atlantis").status_code == 404


def test_weather_unavailable_fallback(client):
    def broken(lat, lon):
        raise TimeoutError("upstream down")

    mongo.db().weather_cache.delete_many({})
    weather.set_fetcher(broken)
    w = client.get("/api/v1/destinations/auli/weather").json()
    assert w == {"available": False, "reason": "Live weather is unavailable right now. Try again later."}
    weather.set_fetcher(fake_forecast)


def test_weather_warning_thresholds_unit():
    days = weather.parse(fake_forecast(0, 0))["daily"]
    assert [w["kind"] for w in weather.warnings(days)] == ["heavy_rain", "snow"]
    calm = [dict(d, precip_mm=0, snow_cm=0) for d in days]
    assert weather.warnings(calm) == []


def test_crowd_index_bands():
    expected = {0: "low", 39: "low", 40: "moderate", 64: "moderate", 65: "high", 84: "high", 85: "very_high", 100: "very_high"}
    assert {i: crowd.band(i) for i in expected} == expected
    assert [b["min"] for b in crowd.BANDS] == [0, 40, 65, 85]


def test_crowd_endpoint_is_estimate_and_in_range(client):
    c = client.get("/api/v1/destinations/rishikesh/crowd").json()
    assert c["label"] == "estimate" and "Not a headcount" in c["note"]
    for x in c["outlook"] + c["usual_by_month"]:
        assert 0 <= x["index"] <= 100 and x["band"] == crowd.band(x["index"])
    kd = client.get("/api/v1/destinations/kedarnath/crowd").json()["usual_by_month"]
    assert kd[0]["band"] == "low"  # Char Dham closed season (January) is quiet in the synthetic pattern


def test_dictionary_has_80_plus_terms_with_valid_links(client):
    d = client.get("/api/v1/dictionary").json()
    assert d["total"] >= 80
    ids = {t["id"] for t in d["items"]}
    assert all(r in ids for t in d["items"] for r in t["related"])
    assert sum(1 for t in d["items"] if t["hindi"]) >= 30
    a = client.get("/api/v1/dictionary", params={"letter": "a"}).json()
    assert a["total"] > 0 and all(t["letter"] == "A" for t in a["items"])
    cat = client.get("/api/v1/dictionary", params={"category": "Trekking & safety"}).json()
    assert all(t["category"] == "Trekking & safety" for t in cat["items"])
    assert client.get("/api/v1/dictionary/revpar").json()["related_items"]


def test_rules_and_helplines_are_orientation_only(client):
    rules = client.get("/api/v1/rules").json()
    assert rules["total"] == 12 and all("verify" in r["verify_note"] for r in rules["items"])
    homestay = client.get("/api/v1/rules", params={"business_type": "homestay"}).json()
    assert any(r["id"] == "homestay-registration" for r in homestay["items"])
    h = client.get("/api/v1/helplines").json()["items"]
    numbers = {x["id"]: x["number"] for x in h}
    assert numbers["emergency-112"] == "112" and numbers["ambulance-108"] == "108"
    assert numbers["state-tourism-helpline"] is None and numbers["police-tourist-help"] is None  # placeholders, never invented


def test_events_calendar(client):
    oct_ = client.get("/api/v1/events", params={"month": 10}).json()
    ids = {e["id"] for e in oct_["items"]}
    assert {"char-dham-closing", "dussehra-diwali"} <= ids
    assert all(10 in e["months"] for e in oct_["items"])
    cd = next(e for e in oct_["items"] if e["id"] == "char-dham-closing")
    assert "announced annually" in cd["date_note"]
    assert set(oct_["by_month"]) == {str(m) for m in range(1, 13)}


def test_public_advisories_are_active_and_labelled(client):
    a = client.get("/api/v1/advisories").json()
    assert a["total"] > 0 and all(x["active"] for x in a["items"])
    assert all(x["sample"] and x["title"].startswith("SAMPLE") for x in a["items"])
    rud = client.get("/api/v1/advisories", params={"district": "rudraprayag"}).json()
    assert all(x["district"] == "rudraprayag" for x in rud["items"])
