"""HOI ingest with API keys, monthly submission, analytics envelopes and k-anonymity."""

from datetime import date, timedelta

from hoi_portal import mongo


def _stay(client, owner, connected: bool | None = None) -> dict:
    items = client.get("/api/v1/business/businesses", headers=owner).json()["items"]
    return next(b for b in items if b["reports_occupancy"] and b["status"] == "active")


def _agg(dest: str, stay_type: str, day: date) -> tuple[int, int]:
    doc = mongo.db().occupancy_agg.find_one({"destination_id": dest, "stay_type": stay_type, "month": day.strftime("%Y-%m")})
    i = day.day - 1
    return (doc["avail"][i], doc["occ"][i]) if doc else (0, 0)


def test_api_key_shown_once_and_ingest_is_idempotent(client, owner):
    b = _stay(client, owner)
    k = client.post(f"/api/v1/business/businesses/{b['id']}/api-keys", json={"label": "HOI test"}, headers=owner)
    assert k.status_code == 201
    raw = k.json()["api_key"]
    assert raw.startswith("uthp_") and "once" in k.json()["warning"]
    listed = client.get(f"/api/v1/business/businesses/{b['id']}/api-keys", headers=owner).json()["items"]
    assert all("api_key" not in x and "key_hash" not in x for x in listed) and listed[0]["prefix"] == raw[:10]
    stored = mongo.db().api_keys.find_one({"id": k.json()["id"]})
    assert raw not in str(stored)  # only the SHA-256 is stored

    day = date.today() - timedelta(days=1)
    before = _agg(b["destination_id"], b["type"], day)
    seeded = mongo.db().occupancy.find_one({"business_id": b["id"], "month": day.strftime("%Y-%m")})
    old = (seeded["avail"][day.day - 1] or 0, seeded["occ"][day.day - 1] or 0) if seeded else (0, 0)
    payload = {"date": day.isoformat(), "rooms_available": min(3, b["capacity"]), "rooms_occupied": 2, "staff_count": 6, "staff_flagged": 1}
    r1 = client.post("/api/v1/ingest/occupancy", json=payload, headers={"X-API-Key": raw})
    assert r1.status_code == 200, r1.text
    assert r1.json()["result"] in ("created", "replaced")
    r2 = client.post("/api/v1/ingest/occupancy", json=payload, headers={"X-API-Key": raw})
    assert r2.json()["result"] == "unchanged"
    after = _agg(b["destination_id"], b["type"], day)
    assert after == (before[0] - old[0] + payload["rooms_available"], before[1] - old[1] + payload["rooms_occupied"])
    assert mongo.db().occupancy.count_documents({"business_id": b["id"], "month": day.strftime("%Y-%m")}) == 1
    wf = mongo.db().workforce.find_one({"business_id": b["id"], "month": day.strftime("%Y-%m")})
    assert wf["staff_count"] == 6 and wf["flagged"] == 1


def test_ingest_rejects_bad_keys_and_bad_data(client, owner):
    b = _stay(client, owner)
    payload = {"date": (date.today() - timedelta(days=2)).isoformat(), "rooms_available": 2, "rooms_occupied": 1}
    assert client.post("/api/v1/ingest/occupancy", json=payload).status_code == 401
    assert client.post("/api/v1/ingest/occupancy", json=payload, headers={"X-API-Key": "uthp_wrong"}).status_code == 401
    raw = client.post(f"/api/v1/business/businesses/{b['id']}/api-keys", json={}, headers=owner).json()
    h = {"X-API-Key": raw["api_key"]}
    assert client.post("/api/v1/ingest/occupancy", json=dict(payload, rooms_occupied=5), headers=h).status_code == 422
    future = (date.today() + timedelta(days=3)).isoformat()
    assert client.post("/api/v1/ingest/occupancy", json=dict(payload, date=future), headers=h).status_code == 422
    assert client.post("/api/v1/ingest/occupancy", json=dict(payload, rooms_available=99999), headers=h).status_code == 422
    assert client.delete(f"/api/v1/business/businesses/{b['id']}/api-keys/{raw['id']}", headers=owner).json()["revoked"] is True
    assert client.post("/api/v1/ingest/occupancy", json=payload, headers=h).status_code == 401


def test_monthly_submission_keeps_ingested_days(client, owner):
    b = _stay(client, owner)
    prev = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    month = prev.strftime("%Y-%m")
    raw = client.post(f"/api/v1/business/businesses/{b['id']}/api-keys", json={}, headers=owner).json()["api_key"]
    client.post(
        "/api/v1/ingest/occupancy", json={"date": prev.isoformat(), "rooms_available": 1, "rooms_occupied": 1}, headers={"X-API-Key": raw}
    )
    cap = b["capacity"]
    r = client.post(
        f"/api/v1/business/businesses/{b['id']}/occupancy",
        json={"month": month, "rooms_available": cap, "occupied_room_nights": cap * 10},
        headers=owner,
    )
    assert r.status_code == 200, r.text
    assert r.json()["days_skipped_ingested"] == 1
    doc = mongo.db().occupancy.find_one({"business_id": b["id"], "month": month})
    assert doc["src"][0] == "i" and doc["occ"][0] == 1 and set(doc["src"][1:]) == {"m"}
    assert sum(doc["occ"][1:]) == cap * 10
    hist = client.get(f"/api/v1/business/businesses/{b['id']}/occupancy", headers=owner).json()["months"]
    assert any(h["month"] == month and h["sources"].get("i") == 1 for h in hist)
    nxt = (date.today().replace(day=28) + timedelta(days=10)).strftime("%Y-%m")
    assert (
        client.post(
            f"/api/v1/business/businesses/{b['id']}/occupancy",
            json={"month": nxt, "rooms_available": 1, "occupied_room_nights": 1},
            headers=owner,
        ).status_code
        == 422
    )


ANALYTICS = ["kpis", "rush", "occupancy", "market", "registrations", "grievances", "workforce"]


def test_every_analytics_response_is_labelled_synthetic(client, admin, officer):
    for name in ANALYTICS:
        for h in (admin, officer):
            r = client.get(f"/api/v1/analytics/{name}", headers=h)
            assert r.status_code == 200, (name, r.text)
            body = r.json()
            assert body["synthetic"] is True and "SYNTHETIC" in body["note"], name
            assert '"_id"' not in r.text


def test_analytics_shapes(client, admin):
    k = client.get("/api/v1/analytics/kpis", headers=admin).json()
    keys = {t["key"] for t in k["kpis"]}
    assert {
        "registered_businesses",
        "active_rooms",
        "applications_pending",
        "grievances_open",
        "grievances_overdue",
        "avg_occupancy_30d",
        "crowd_alerts",
    } <= keys
    rush = client.get("/api/v1/analytics/rush", headers=admin).json()
    assert len(rush["heatmap"]["weeks"]) == 16 and len(rush["heatmap"]["rows"]) == 24
    assert all(len(r["values"]) == 16 for r in rush["heatmap"]["rows"]) and len(rush["top"]) == 10
    assert all(a["index"] >= 85 for a in rush["alerts"])
    occ = client.get("/api/v1/analytics/occupancy", params={"granularity": "monthly"}, headers=admin).json()
    assert len(occ["by_district"]) == 13 and {s["key"] for s in occ["by_type"]} == {"hotel", "homestay"}
    assert all(len(s["values"]) == len(occ["dates"]) for s in occ["by_district"])
    m = client.get("/api/v1/analytics/market", headers=admin).json()
    assert m["years"] == list(range(2019, 2027)) and m["totals"][0]["yoy_pct"] is None and m["totals"][1]["yoy_pct"] is not None
    assert m["totals"][-1]["partial_year"] is True and m["totals"][-1]["yoy_pct"] is None
    g = client.get("/api/v1/analytics/grievances", headers=admin).json()
    assert g["total"] >= 40 and 0 <= g["sla_breach_rate_pct"] <= 100 and g["median_resolution_days"] is not None
    reg = client.get("/api/v1/analytics/registrations", params={"months": 12}, headers=admin).json()
    assert len(reg["months"]) == 12 and len(reg["series"]) == 2


def test_workforce_k_anonymity(client, admin, officer):
    for params in ({"group_by": "district"}, {"group_by": "type"}):
        w = client.get("/api/v1/analytics/workforce", params=params, headers=admin).json()
        assert w["k_min"] == 5
        shown = [g for g in w["groups"] if not g["suppressed"]]
        hidden = [g for g in w["groups"] if g["suppressed"]]
        assert all(g["businesses"] >= 5 for g in shown)
        for g in hidden:
            assert set(g) == {"key", "label", "suppressed", "reason"} and "k-anonymity" in g["reason"]
        if params["group_by"] == "district":
            assert shown and hidden  # seed has both large and small districts
    # Recompute contributors directly to prove suppression is right.
    w = client.get("/api/v1/analytics/workforce", headers=admin).json()
    latest = w["month"]
    assert latest < date.today().strftime("%Y-%m")  # latest complete month, not the one still filling up
    for g in w["groups"]:
        n = len({r["business_id"] for r in mongo.db().workforce.find({"district": g["key"], "month": latest})})
        assert g["suppressed"] == (n < 5)
    mine = client.get("/api/v1/analytics/workforce", headers=officer).json()
    assert [g["key"] for g in mine["groups"]] == ["rudraprayag"]
