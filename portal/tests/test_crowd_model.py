"""Real-data crowd model (Char Dham): loads, guardrails, confidence in the API, alerts, estimate fallback."""

import copy
from datetime import date, timedelta

import pytest
from hoi_portal.services import crowd
from hoi_portal.services import crowd_model as cm

DEST = "kedarnath"


@pytest.fixture(autouse=True)
def _real_model():
    crowd.reset_model()
    yield
    crowd.reset_model()
    crowd.invalidate()


@pytest.fixture
def bundle() -> cm.Bundle:
    b = crowd.model_bundle()
    assert b is not None, "hoi_portal/models/crowd_real_v1.json must load"
    return b


def test_model_loads_and_covers_the_four_shrines(bundle):
    assert bundle.raw["real_data"] is True
    assert set(bundle.dests) == {"kedarnath", "badrinath", "gangotri", "yamunotri"}
    assert crowd.model_covers(DEST) and not crowd.model_covers("rishikesh")


def test_closed_season_is_closed_not_quiet(bundle):
    year = max(int(y) for y in bundle.dests[DEST]["seasons"])
    r = cm.forecast_day(bundle, DEST, date(year, 1, 15))
    assert r["status"] == "closed" and r["pilgrims"] == 0 and r["band"] is None


def test_prediction_clipped_to_capacity_and_ordered(bundle):
    last = bundle.last_observed(DEST)
    cap = bundle.dests[DEST]["cap"]
    for h in range(1, cm.MAX_H + 1):
        r = cm.predict(bundle, DEST, last + timedelta(days=h), as_of=last)
        if r["status"] in ("closed", "abstain"):
            continue
        assert 0 <= r["low"] <= r["pilgrims"] <= r["high"] <= cap
        assert r["confidence"] in {"high", "medium", "low"}
    assert cm.band_of(bundle, DEST, 10 * cap) == ("very_high", 100)


def test_fallback_to_last_season_when_counts_are_old(bundle):
    last = bundle.last_observed(DEST)
    far = last + timedelta(days=cm.MAX_H + 5)
    r = cm.forecast_day(bundle, DEST, far)
    assert r["status"] in {"closed", "ok", "abstain", "unknown_season"}
    if r["status"] == "ok":
        assert r["basis"] == "seasonal_baseline" and r["confidence"] == "low"


def test_invalid_input_is_rejected(bundle):
    last = bundle.last_observed(DEST)
    with pytest.raises(ValueError):
        cm.predict(bundle, "atlantis", last + timedelta(days=1), as_of=last)
    with pytest.raises(ValueError):
        cm.predict(bundle, DEST, last + timedelta(days=40), as_of=last)
    with pytest.raises(ValueError):
        cm.predict(bundle, DEST, last + timedelta(days=1), as_of=last, recent={last.isoformat(): "lots"})


def test_api_returns_confidence_for_every_day(client):
    c = client.get(f"/api/v1/destinations/{DEST}/crowd").json()
    assert c["source"] == "real_model" and c["model"]["version"] == "real_v1"
    assert len(c["outlook"]) == 14 and isinstance(c["alerts"], list)
    for x in c["outlook"]:
        assert x["confidence"] in {"high", "medium", "low"} and 0 <= x["index"] <= 100
        assert x["band"] == crowd.band(x["index"])
        if x.get("pilgrims") is not None and not x.get("closed"):
            lo, hi = x["range"]
            assert lo <= x["pilgrims"] <= hi
    r = client.get("/api/v1/destinations/rishikesh/crowd").json()  # not covered: the estimate, labelled low
    assert r["source"] == "estimate" and all(x["confidence"] == "low" for x in r["outlook"])


def test_estimate_used_when_the_model_is_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(crowd, "MODEL_PATH", tmp_path / "missing.json")
    crowd.reset_model()
    c = client.get(f"/api/v1/destinations/{DEST}/crowd").json()
    assert c["source"] == "estimate" and c["model"] is None and "Not a headcount" in c["note"]


def test_very_busy_alert_reaches_page_and_officials(client, admin, bundle):
    hot = cm.Bundle(copy.deepcopy(bundle.raw))
    hot.dests[DEST]["band_edges"] = [1.0, 2.0, 3.0]  # everything open counts as very busy
    hot.dests[DEST]["cap"] = 4.0
    crowd.set_model(hot)
    look = crowd.outlook(crowd.Context(), DEST, date.today(), 14)
    alerts = crowd.alert_days(look)
    assert len(alerts) == sum(1 for x in look if not x.get("closed") and x["index"] >= crowd.ALERT_AT)
    for a in alerts:
        assert a["reason"] and a["confidence"] in {"high", "medium", "low"}
    if alerts:
        c = client.get(f"/api/v1/destinations/{DEST}/crowd").json()
        assert c["alert"] is True and c["alerts"][0]["reason"]
        rush = client.get("/api/v1/analytics/rush", headers=admin).json()
        mine = [a for a in rush["alerts"] if a["destination_id"] == DEST]
        assert mine and {"reason", "confidence", "source"} <= set(mine[0])


def test_alert_days_plain_reason_and_skips_closed():
    look = [
        {"date": "2026-05-02", "index": 92, "confidence": "medium", "reason": "usual for opening weeks", "source": "real_model"},
        {"date": "2026-05-03", "index": 60, "confidence": "high", "source": "real_model"},
        {"date": "2026-11-20", "index": 99, "closed": True, "confidence": "high", "source": "real_model"},
        {"date": "2026-06-01", "index": 88, "events": ["Some festival"], "source": "estimate"},
    ]
    out = crowd.alert_days(look)
    assert [a["date"] for a in out] == ["2026-05-02", "2026-06-01"]
    assert out[0]["reason"] == "usual for opening weeks" and out[1]["reason"] == "festival"
    assert out[1]["confidence"] == "low"
