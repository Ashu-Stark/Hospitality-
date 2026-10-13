"""Experiences, circuits, sample itineraries, nearby destinations, map points, official links and district offices."""

import re
from datetime import date, timedelta

from hoi_portal.seed.destinations import BY_ID_DEST, DESTINATIONS
from hoi_portal.seed.experiences import validate
from hoi_portal.services.plan import haversine_km

BANDS = {"low", "moderate", "high", "very_high"}
# Itinerary text must not invent distances, times or prices (spec section 5 only).
INVENTED = re.compile(r"\b\d+(\.\d+)?\s*(km|kms|kilomet|hour|hrs|hr|min|minutes|rs\.?|inr|₹)", re.I)


def test_curated_content_is_consistent():
    validate()
    assert all("themes" in d for d in DESTINATIONS)
    assert "spiritual" in BY_ID_DEST["kedarnath"]["themes"] and "wildlife" in BY_ID_DEST["jim-corbett-ramnagar"]["themes"]
    assert {"spiritual", "wellness", "adventure"} <= set(BY_ID_DEST["rishikesh"]["themes"])


def test_destinations_expose_themes(client):
    items = client.get("/api/v1/destinations").json()["items"]
    assert len(items) == 24 and all(isinstance(d["themes"], list) for d in items)


def test_experiences_list_and_detail(client):
    r = client.get("/api/v1/experiences").json()
    assert r["total"] == 6 and {e["id"] for e in r["items"]} == {"spiritual", "adventure", "wildlife", "wellness", "leisure", "culture"}
    for e in r["items"]:
        assert e["destination_count"] > 0
        d = client.get(f"/api/v1/experiences/{e['id']}").json()
        assert d["intro"] and len(d["destinations"]) == e["destination_count"]
        for x in d["destinations"]:
            assert e["id"] in x["themes"] and x["crowd_today"]["band"] in BANDS and x["crowd_today"]["label"] == "estimate"
            assert "weather_now" in x  # cache only: None until the destination's weather was loaded once
        assert d["festivals"] and all(f["name"] for f in d["festivals"])
        assert d["terms"] and all(t["term"] for t in d["terms"])
    assert client.get("/api/v1/experiences/nope").status_code == 404


def test_experience_shows_cached_weather_after_a_destination_load(client):
    client.get("/api/v1/destinations/auli/weather")
    d = client.get("/api/v1/experiences/adventure").json()
    auli = next(x for x in d["destinations"] if x["id"] == "auli")
    assert auli["weather_now"]["available"] is True and auli["weather_now"]["temperature_c"] is not None


def test_circuits_are_ordered_curated_lists(client):
    r = client.get("/api/v1/circuits").json()
    ids = {c["id"] for c in r["items"]}
    assert {"char-dham", "kumaon-hills", "corbett-foothills", "garhwal-hill-stations", "rishikesh-haridwar"} == ids
    cd = next(c for c in r["items"] if c["id"] == "char-dham")
    assert cd["destination_ids"] == ["yamunotri", "gangotri", "kedarnath", "badrinath"]
    assert all(x["id"] in BY_ID_DEST for c in r["items"] for x in c["destinations"])


def test_itineraries_are_samples_without_invented_numbers(client):
    r = client.get("/api/v1/itineraries").json()
    assert 6 <= r["total"] <= 8 and "Verify" in r["note"]
    for i in r["items"]:
        assert i["sample"] is True and "planning suggestion" in i["note"]
        assert all(s["destination_id"] in BY_ID_DEST and s["suggested_days"] >= 1 for s in i["stops"])
        assert i["suggested_days_total"] == sum(s["suggested_days"] for s in i["stops"])
        assert not INVENTED.search(" ".join([i["name"], i["summary"], i["note"]]))
    only = client.get("/api/v1/itineraries", params={"theme": "spiritual"}).json()
    assert only["total"] >= 2 and all(i["theme"] == "spiritual" for i in only["items"])


def test_itinerary_detail_has_live_status_per_stop_and_best_start(client):
    d = client.get("/api/v1/itineraries/char-dham-yatra").json()
    assert [s["order"] for s in d["stops"]] == list(range(1, len(d["stops"]) + 1))
    for s in d["stops"]:
        assert s["crowd_today"]["band"] in BANDS
        assert s["weather"]["available"] is True and s["weather"]["warning"]["kind"] == "heavy_rain"  # fake forecast has heavy rain
        assert s["road"] is None or s["road"]["status"] in {"open", "caution", "closed"}
    assert any(s["road"] for s in d["stops"])  # seeded sample road advisories exist on the Char Dham route
    b = d["best_start"]
    start = date.fromisoformat(b["date"])
    assert date.today() <= start < date.today() + timedelta(days=14) and b["label"] == "estimate"
    assert b["avg_index"] <= b["if_start_today"]["avg_index"] and b["band"] in BANDS
    assert client.get("/api/v1/itineraries/nope").status_code == 404


def test_nearby_by_straight_line_distance(client):
    r = client.get("/api/v1/destinations/kedarnath/nearby", params={"limit": 5}).json()
    assert r["total"] == 5 and "not road distance" in r["distance_note"]
    dists = [x["distance_km"] for x in r["items"]]
    assert dists == sorted(dists) and "kedarnath" not in {x["id"] for x in r["items"]}
    assert r["items"][0]["id"] == "chopta"  # closest curated point to Kedarnath by coordinates
    assert 15 < haversine_km(BY_ID_DEST["haridwar"], BY_ID_DEST["rishikesh"]) < 25  # sanity check of the formula
    assert client.get("/api/v1/destinations/nope/nearby").status_code == 404
    assert client.get("/api/v1/destinations/kedarnath/nearby", params={"limit": 0}).status_code == 422


def test_map_points_and_official_links_and_offices(client):
    m = client.get("/api/v1/map").json()
    assert len(m["items"]) == 24 and "not to scale" in m["note"] and "no boundaries" in m["note"]
    assert any("char-dham" in p["circuits"] for p in m["items"])
    o = client.get("/api/v1/official-services").json()
    urls = {s["url"] for s in o["items"]}
    assert urls == {"https://registrationandtouristcare.uk.gov.in/", "https://uttarastays.com/"}
    assert "opens in a new tab" in o["note"] and "not part of this concept" in o["note"]
    meta = client.get("/api/v1/meta").json()
    assert meta["official_services"]["items"] and len(meta["experiences"]) == 6
    off = client.get("/api/v1/district-offices").json()
    assert off["total"] == 13 and all(x["contact"] is None and "to be filled" in x["note"] for x in off["items"])
