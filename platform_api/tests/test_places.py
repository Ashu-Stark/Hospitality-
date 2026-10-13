"""Concierge "places to visit": hotel list + RETRIEVAL from the tourism portal (mocked), offbeat intent, honest "none found",
place cards with map links, Hindi / Hinglish. Offline: the portal is a fake; no network. All data SYNTHETIC.
"""

from urllib.parse import unquote

import pytest
from conftest import auth

from hoi_platform import mongo
from hoi_platform.services import ai, concierge, places, profiles, tenants

# A fake tourism portal (shapes as in portal/hoi_portal: /destinations, /destinations/{id}/places, /local-experiences).
DESTS = [
    {
        "id": "nainital",
        "name": "Nainital",
        "district": "nainital",
        "district_name": "Nainital",
        "lat": 29.38,
        "lon": 79.463,
        "tags": ["hill town", "lake"],
        "why_go": "Lake town in Kumaon.",
        "crowd_today": {"index": 70, "band": "high"},
    },
    {
        "id": "jim-corbett-ramnagar",
        "name": "Jim Corbett / Ramnagar",
        "district": "nainital",
        "district_name": "Nainital",
        "lat": 29.394,
        "lon": 79.126,
        "tags": ["wildlife", "national park"],
        "why_go": "National park on the foothills.",
        "crowd_today": {"index": 66, "band": "high"},
    },
    {
        "id": "almora",
        "name": "Almora",
        "district": "almora",
        "district_name": "Almora",
        "lat": 29.597,
        "lon": 79.659,
        "tags": ["hill town"],
        "why_go": "Old hill town with views.",
        "crowd_today": {"index": 57, "band": "moderate"},
    },
    {
        "id": "mussoorie",
        "name": "Mussoorie",
        "district": "dehradun",
        "district_name": "Dehradun",
        "lat": 30.459,
        "lon": 78.064,
        "tags": ["hill town"],
        "why_go": "Hill town.",
        "crowd_today": {"index": 75, "band": "high"},
    },
    {
        "id": "dhanaulti",
        "name": "Dhanaulti",
        "district": "tehri-garhwal",
        "district_name": "Tehri Garhwal",
        "lat": 30.43,
        "lon": 78.24,
        "tags": ["hill town"],
        "why_go": "Quiet deodar forests.",
        "crowd_today": {"index": 40, "band": "moderate"},
    },
    {
        "id": "kashipur",
        "name": "Kashipur",
        "district": "udham-singh-nagar",
        "district_name": "Udham Singh Nagar",
        "lat": 29.21,
        "lon": 78.96,
        "tags": ["town"],
        "why_go": "Plains town.",
        "crowd_today": {"index": 30, "band": "low"},
    },
]
VIEWPOINTS = {
    "nainital": [
        {"name": "Snow View", "kind": "viewpoint", "distance_km": 1.7, "lat": 29.39523, "lon": 79.462},
        {"name": "Dorthy Seat", "kind": "viewpoint", "distance_km": 1.2, "lat": 29.3833, "lon": 79.45072},
    ],
    "mussoorie": [{"name": "Gun Hill", "kind": "viewpoint", "distance_km": 0.6, "lat": 30.4613, "lon": 78.0756}],
}
EXPERIENCES = {
    "nainital": [
        {
            "id": "LX-1",
            "title": "Birding walk, Nainital",
            "type": "birding",
            "type_label": "Birding walk",
            "destination_id": "nainital",
            "destination_name": "Nainital",
            "duration_hours": 4.5,
            "group_max": 3,
            "synthetic": True,
        },
        {
            "id": "LX-2",
            "title": "Temple-town heritage walk, Nainital",
            "type": "heritage_walk",
            "type_label": "Heritage walk",
            "destination_id": "nainital",
            "destination_name": "Nainital",
            "duration_hours": 2,
            "group_max": 12,
            "synthetic": True,
        },
    ],
}


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakePortal:
    def __init__(self, dests=None, viewpoints=None, experiences=None, fail=False):
        self.dests = DESTS if dests is None else dests
        self.viewpoints = VIEWPOINTS if viewpoints is None else viewpoints
        self.experiences = EXPERIENCES if experiences is None else experiences
        self.fail, self.calls = fail, []

    def __call__(self, url, params, timeout=None):
        self.calls.append((url, dict(params)))
        if self.fail:
            raise OSError("portal down")
        path = url.split("/api/v1", 1)[1]
        if path == "/meta":
            districts = {d["district"]: d["district_name"] for d in self.dests}
            return Resp(
                200,
                {
                    "districts": [{"id": k, "name": v} for k, v in districts.items()],
                    "destinations": [{"id": d["id"], "name": d["name"], "district": d["district"]} for d in self.dests],
                },
            )
        if path == "/destinations":
            items = [d for d in self.dests if not params.get("district") or d["district"] == params["district"]]
            return Resp(200, {"items": items, "total": len(items)})
        if path.startswith("/destinations/") and path.endswith("/nearby"):
            me = next(d for d in self.dests if d["id"] == path.split("/")[2])
            others = sorted(
                (
                    {**d, "distance_km": round(places.haversine_km(me["lat"], me["lon"], d["lat"], d["lon"]))}
                    for d in self.dests
                    if d is not me
                ),
                key=lambda d: d["distance_km"],
            )
            return Resp(200, {"items": [{k: v for k, v in d.items() if k != "why_go"} for d in others[: int(params.get("limit", 6))]]})
        if path.startswith("/destinations/") and path.endswith("/places"):
            items = self.viewpoints.get(path.split("/")[2], [])
            return Resp(200, {"available": bool(items), "groups": [{"category": "viewpoint", "items": items}] if items else []})
        if path == "/local-experiences":
            return Resp(200, {"items": self.experiences.get(params.get("district"), [])})
        return Resp(404, {"detail": "not found"})


@pytest.fixture(autouse=True)
def _fresh_cache():
    mongo.col("places_cache").delete_many({})
    ai.use()
    yield
    mongo.col("places_cache").delete_many({})
    ai.use()


@pytest.fixture
def portal():
    fake = FakePortal()
    places.set_http(fake)
    return fake


def hotel(region: str, name: str, nearby=None, location=None) -> dict:
    """A new SYNTHETIC hotel (own tenant + property + profile) and a concierge context for one of its rooms."""
    t = tenants.create_tenant(f"{name} (test)", plan="growth")
    prop = tenants.add_property(t["id"], name, region, 6)
    data = {"display_name": name, "nearby": nearby or []}
    if location:
        data["location"] = location
    profiles.put(t["id"], data, "test", prop["id"])
    prof = profiles.public(t["id"], prop["id"])
    return {
        "room": "101",
        "profile": prof,
        "place": {"tenant_id": t["id"], "property_id": prop["id"]},
        "stay": {"late_checkout": {"status": "none"}, "checkout": None, "feedback_given": False},
        "requests": [],
    }


def ask(ctx: dict, text: str) -> dict:
    return concierge.rules(text, concierge.detect_lang(text), ctx)


# ------------------------------------------------------------------ retrieval for a new hotel
def test_new_nainital_hotel_with_empty_list_gets_places_from_the_portal(portal):
    ctx = hotel("Nainital, Uttarakhand", "Lakeside Test Stay, Nainital")
    assert ctx["profile"]["nearby"] == []
    out = ask(ctx, "places to visit nearby?")
    names = [c["name"] for c in out["cards"]]
    assert "Snow View" in names and "Almora" in names and "Nainital" not in names  # the hotel's own town is not a "place nearby"
    assert "near Nainital" in out["reply"] and "Snow View" in out["reply"]
    assert out["speak"] and "http" not in out["speak"] and "Snow View" not in out["speak"]  # voice: one short sentence
    almora = next(c for c in out["cards"] if c["name"] == "Almora")
    assert 25 <= almora["distance_km"] <= 35 and almora["source"] == "portal"
    assert all(len(c) and c["image"].startswith("/shared/") for c in out["cards"])
    # the slow full destination list is not needed when the town is known by name
    assert not any(u.endswith("/destinations") and not q for u, q in portal.calls)
    # cached: the same question again makes no new portal call
    n = len(portal.calls)
    ask(ctx, "what can we visit around here")
    assert len(portal.calls) == n
    assert mongo.col("places_cache").count_documents({"ok": True}) >= 3


def test_hotel_found_by_coordinates_when_region_is_empty(portal):
    ctx = hotel("", "Coordinates Test Stay", location={"lat": 29.39, "lon": 79.45})
    out = ask(ctx, "sightseeing")
    assert any(c["name"] == "Snow View" for c in out["cards"])
    assert all(c["distance_km"] is None or c["distance_km"] <= places.MAX_KM for c in out["cards"])


def test_long_hotel_list_needs_no_portal_call(portal):
    nearby = [{"name": f"Test spot {i}", "distance_note": "", "tip": "A short walk."} for i in range(5)]
    ctx = hotel("Nainital, Uttarakhand", "Full List Test Stay", nearby=nearby)
    out = ask(ctx, "nearby places")
    assert [c["name"] for c in out["cards"]][:5] == [f"Test spot {i}" for i in range(5)]
    assert portal.calls == []


def test_portal_offline_falls_back_to_the_hotel_list():
    places.set_http(FakePortal(fail=True))
    ctx = hotel("Nainital, Uttarakhand", "Offline Test Stay", nearby=[{"name": "Naina Devi temple", "tip": "Go early."}])
    out = ask(ctx, "places to visit")
    assert [c["name"] for c in out["cards"]] == ["Naina Devi temple"] and out["cards"][0]["kind"] == "temple"
    # a hotel with no list at all and no portal: no invented places, the front desk is offered
    empty = hotel("Nainital, Uttarakhand", "Empty Offline Test Stay")
    out = ask(empty, "places to visit")
    assert not out.get("cards")
    assert "front desk" in out["reply"].lower()


def test_stale_cache_is_used_when_the_portal_fails(portal):
    ctx = hotel("Nainital, Uttarakhand", "Stale Cache Test Stay")
    first = ask(ctx, "nearby places")
    mongo.col("places_cache").update_many({}, {"$set": {"expires_ts": 0}})  # everything expired
    places.set_http(FakePortal(fail=True))
    again = ask(ctx, "nearby places")
    assert [c["name"] for c in again["cards"]] == [c["name"] for c in first["cards"]]


# ------------------------------------------------------------------ offbeat / lesser-known
@pytest.mark.parametrize(
    "text",
    [
        "hidden places near here",
        "any offbeat spots?",
        "unexplored places",
        "somewhere less crowded",
        "kam bheed wali jagah batao",
        "jo log nahi jaate aisi jagah",
        "कम भीड़ वाली जगह बताइए",
        "hidden gems nearby",
    ],
)
def test_offbeat_intent_detected(text):
    t = " " + concierge.norm(text) + " "
    assert concierge.wants_places(t) and concierge.has(t, concierge.OFFBEAT_WORDS)


@pytest.mark.parametrize("text", ["please visit my room to clean it", "are there hidden charges?", "is the wifi password secret?"])
def test_not_a_places_question(text):
    assert not concierge.wants_places(" " + concierge.norm(text) + " ")


def test_offbeat_returns_quiet_places_with_the_reason(portal):
    ctx = hotel("Nainital, Uttarakhand", "Offbeat Test Stay")
    out = ask(ctx, "hidden places near here")
    names = [c["name"] for c in out["cards"]]
    assert out["cards"] and all(c["offbeat"] and c["why_quiet"] for c in out["cards"])
    assert "Almora" in names  # crowd estimate moderate and lower than Nainital's
    assert "Jim Corbett / Ramnagar" not in names  # crowd estimate high
    assert "Kashipur" not in names  # a quiet day does not make a plain town a "hidden" spot
    assert "Birding walk, Nainital" in names  # small-group local experience
    assert "Temple-town heritage walk, Nainital" not in names  # heritage walks are not counted as offbeat
    birding = next(c for c in out["cards"] if c["name"] == "Birding walk, Nainital")
    assert birding["sample"] is True  # portal experiences are SAMPLE data and say so
    assert "quieter" in out["reply"].lower() and "popular" not in out["reply"].lower()


def test_hotel_marked_offbeat_place_comes_first(portal):
    nearby = [
        {"name": "Mall Road", "tip": "Busy promenade."},
        {"name": "Pangot village trail", "tip": "Birds and forest.", "offbeat": True},
        {"name": "Kilbury forest road", "tip": "Quiet walk under oaks."},
    ]
    ctx = hotel("Nainital, Uttarakhand", "Marked Test Stay", nearby=nearby)
    out = ask(ctx, "offbeat places?")
    names = [c["name"] for c in out["cards"]]
    assert names[:2] == ["Pangot village trail", "Kilbury forest road"] and "Mall Road" not in names
    assert out["cards"][0]["why_quiet"] == places.OFFBEAT_SIGNALS["hotel"]


def test_no_quiet_places_says_so_honestly():
    busy = [{**d, "crowd_today": {"index": 90, "band": "very_high"}} for d in DESTS]
    places.set_http(FakePortal(dests=busy, experiences={}))
    ctx = hotel("Nainital, Uttarakhand", "Busy Test Stay")
    out = ask(ctx, "hidden places near here")
    assert out["reply"].startswith("I could not find lesser-known spots near Nainital; here are the popular ones:")
    assert out["cards"] and not any(c["offbeat"] for c in out["cards"])
    hi = ask(ctx, "कम भीड़ वाली जगह बताइए")
    assert "नहीं मिलीं" in hi["reply"] and "लोकप्रिय" in hi["reply"]
    assert "दिखा रही हूँ" in hi["speak"]  # feminine first person


# ------------------------------------------------------------------ cards
def test_card_maps_urls():
    c = places.card("Snow View", "", "viewpoint", lat=29.39523, lon=79.462)
    assert c["maps_url"] == "https://www.google.com/maps/search/?api=1&query=29.39523,79.46200"
    named = places.card("Naina Devi temple", "", "temple", town="Nainital")
    assert named["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=")
    assert unquote(named["maps_url"].split("query=")[1]) == "Naina Devi temple, Nainital, Uttarakhand"
    assert places.card("x", "", "lake", image="https://evil.example/x.png")["image"] == "/shared/places/lake.svg"  # same-origin only


def test_place_pictures_exist(client):
    for kind in ("mountain", "viewpoint", "lake", "temple", "forest", "village", "town", "food", "waterfall"):
        r = client.get(f"/shared/places/{kind}.svg")
        assert r.status_code == 200 and r.content.startswith(b"<svg")


# ------------------------------------------------------------------ Hindi / Hinglish
def test_hindi_and_hinglish_places_questions(portal):
    ctx = hotel("Nainital, Uttarakhand", "Hindi Test Stay")
    hi = ask(ctx, "आसपास घूमने की जगह बताइए")
    assert hi["cards"] and "Nainital के पास" in hi["reply"] and "दिखा रही हूँ" in hi["speak"]
    hg = ask(ctx, "aas paas ghoomne ki jagah")
    assert hg["cards"] and "Nainital ke paas" in hg["reply"] and "dikha rahi hoon" in hg["speak"]
    quiet = ask(ctx, "kam bheed wali jagah batao")
    assert all(c["offbeat"] for c in quiet["cards"]) and "kam bheed" in quiet["reply"]


# ------------------------------------------------------------------ the guest endpoint
def test_chat_endpoint_returns_cards_and_skips_the_llm(client, portal):
    owner = auth(client, "demo.owner")
    r = next(x for x in client.get("/rooms", headers=owner).json()["rooms"] if x["status"] == "occupied")

    class NoLlm:
        name = "must-not-run"

        def available(self):
            return True, "ok"

        def complete_json(self, system, messages):
            raise AssertionError("places questions must not go to the LLM")

    ai.use(chat=NoLlm())
    out = client.post(f"/public/guest/{r['guest_token']}/chat", json={"message": "hidden places near here", "lang": "en"}).json()
    assert out["source"] == "rules" and out["cards"] and out["speak"]
    names = [c["name"] for c in out["cards"]]
    assert names[0] == "Landour and Lal Tibba"  # the demo hotel marks it as a quiet spot
    assert "Dhanaulti" in names  # quieter than Mussoorie today (portal crowd estimate), within 60 km
    assert all(c["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=") for c in out["cards"])
    normal = client.post(f"/public/guest/{r['guest_token']}/chat", json={"message": "Wi-Fi?", "lang": "en"}).json()
    assert normal["cards"] == [] and normal["speak"] is None
