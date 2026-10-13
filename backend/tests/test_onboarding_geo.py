"""Onboarding: LocationIQ geocoding of the location answer, with a fake geocoder (no network)."""

import pytest

from backend.onboarding import geocode
from backend.onboarding.config import load_config
from backend.onboarding.schema import Geo, HotelProfile

FOUND = Geo(lat=30.4545, lon=78.0847, display_name="Mussoorie, Dehradun, Uttarakhand, India",
            confidence=0.61, query="Mussoorie")


class FakeGeocoder:
    def __init__(self, result=FOUND, fail=False):  # noqa: ANN001
        self.result, self.fail, self.calls = result, fail, []

    def geocode(self, query: str):  # noqa: ANN201
        self.calls.append(query)
        if self.fail:
            raise TimeoutError("network down")
        return self.result.model_copy(update={"query": query}) if self.result else None


def _start(client) -> str:  # noqa: ANN001
    r = client.post("/onboarding/start", json={"language": "en"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _answer_rooms_then_location(client, sid: str, text: str = "Mussoorie") -> dict:  # noqa: ANN001
    client.post("/onboarding/answer", json={"session_id": sid, "text": "We have 12 rooms"})
    r = client.post("/onboarding/answer", json={"session_id": sid, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_location_answer_is_geocoded(client):  # noqa: ANN001
    fake = FakeGeocoder()
    client.app.state.onboarding_geocoder = fake
    sid = _start(client)
    out = _answer_rooms_then_location(client, sid)
    geo = out["fields"]["location"]["geo"]
    assert out["fields"]["location"]["value"] == "Mussoorie" and fake.calls == ["Mussoorie"]
    assert geo["display_name"].startswith("Mussoorie") and geo["source"] == "locationiq"
    assert geo["lat"] == pytest.approx(30.4545) and 0 <= geo["confidence"] <= 1
    # stored in the draft and returned by the summary
    s = client.get("/onboarding/summary", params={"session": sid}).json()
    assert s["fields"]["location"]["geo"]["lon"] == pytest.approx(78.0847)
    # editing the location geocodes the new text
    r = client.patch("/onboarding/field", json={"session_id": sid, "field": "location",
                                                "value": "Nainital"})
    assert r.status_code == 200 and fake.calls[-1] == "Nainital"
    assert r.json()["fields"]["location"]["geo"]["query"] == "Nainital"


def test_failure_or_no_match_is_silent(client):  # noqa: ANN001
    client.app.state.onboarding_geocoder = FakeGeocoder(fail=True)
    out = _answer_rooms_then_location(client, _start(client))
    assert out["fields"]["location"]["value"] == "Mussoorie"
    assert out["fields"]["location"]["geo"] is None and not out["warnings"].get("location")
    client.app.state.onboarding_geocoder = FakeGeocoder(result=None)
    out = _answer_rooms_then_location(client, _start(client))
    assert out["fields"]["location"]["geo"] is None


def test_default_geocoder_without_key_never_calls(monkeypatch):  # noqa: ANN001
    cfg = load_config()
    assert cfg.geocoding is not None and cfg.geocoding.api_key_env == "LOCATIONIQ_API_KEY"
    g = geocode.default_geocoder(cfg)
    monkeypatch.delenv("LOCATIONIQ_API_KEY", raising=False)
    monkeypatch.setattr(g, "_fetch", lambda q: pytest.fail("network call without a key"))
    assert g.geocode("Mussoorie") is None


def test_locationiq_geocoder_parses_and_caches(monkeypatch):  # noqa: ANN001
    g = geocode.default_geocoder(load_config())
    monkeypatch.setenv("LOCATIONIQ_API_KEY", "fake-test-key")
    calls = []
    rows = [{"lat": "30.45", "lon": "78.08", "display_name": "Mall Road, Mussoorie, India",
             "importance": 0.05}]
    monkeypatch.setattr(g, "_fetch", lambda q: calls.append(q) or rows)
    a = g.geocode("  Mall   Road, Mussoorie ")
    assert a.display_name == "Mall Road, Mussoorie, India" and a.confidence == 0.05
    assert g.geocode("mall road, mussoorie") == a and calls == ["Mall Road, Mussoorie"]


def test_old_drafts_without_geo_still_load():
    data = HotelProfile().model_dump()
    data["location"] = {"value": "Almora", "source": "typed", "confidence": 1.0,
                        "needs_verification": False, "confirmed": True, "method": "edit",
                        "note": None}
    p = HotelProfile.model_validate(data)
    assert p.location.value == "Almora" and p.location.geo is None


def test_confirm_not_blocked_by_geocoding(client):  # noqa: ANN001
    client.app.state.onboarding_geocoder = FakeGeocoder(fail=True)
    from tests.test_onboarding_d import TYPED_ANSWERS, run_typed_flow
    out = run_typed_flow(client, TYPED_ANSWERS)
    r = client.post("/onboarding/confirm", json={"session": out["session_id"],
                                                 "acknowledged_legal_fields": out["legal_fields"]})
    assert r.status_code == 200, r.text
