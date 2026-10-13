"""Local experiences (host CRUD, public list/filter, join-request scoping) and staffing agencies + the HOI
staffing-request ingest endpoint (key auth, idempotency per source id, job created, agencies notified)."""

from datetime import date, timedelta

from conftest import login
from hoi_portal import mongo


def _next_in(months: list[int], start_days: int = 10) -> str:
    d = date.today() + timedelta(days=start_days)
    for _ in range(400):
        if d.month in months:
            return d.isoformat()
        d += timedelta(days=1)
    raise AssertionError("no date")


def _host_biz(client, owner) -> dict:
    items = client.get("/api/v1/business/businesses", headers=owner).json()["items"]
    return next(b for b in items if b["type"] == "homestay" and b["status"] == "active")


# ------------------------------------------------------------------ local experiences
def test_public_list_filters_and_detail(client):
    r = client.get("/api/v1/local-experiences", params={"page_size": 50}).json()
    assert r["total"] >= 35 and r["items"] and "Sample" in r["note"]
    assert all(i["synthetic"] for i in r["items"]) and sum(r["by_type"].values()) == r["total"]
    one = client.get("/api/v1/local-experiences", params={"type": "birding"}).json()
    assert one["total"] >= 1 and {i["type"] for i in one["items"]} == {"birding"}
    m = client.get("/api/v1/local-experiences", params={"month": 7}).json()
    assert all(7 in i["months"] for i in m["items"])
    dist = client.get("/api/v1/local-experiences", params={"district": "almora"}).json()
    assert dist["total"] >= 1 and all(i["district"] == "almora" for i in dist["items"])
    assert client.get("/api/v1/local-experiences", params={"type": "nope"}).status_code == 422
    d = client.get(f"/api/v1/local-experiences/{r['items'][0]['id']}").json()
    assert d["host"]["status"] == "active" and 1 <= len(d["stays_nearby"]) <= 3
    assert all(s["type"] == "homestay" for s in d["stays_nearby"]) and "No payment" in d["join_note"]
    assert "contact" not in str(d["host"]).lower() or d["host"].get("contact") is None
    assert client.get("/api/v1/local-experiences/LX-9999").status_code == 404
    dest = client.get(f"/api/v1/destinations/{d['destination_id']}").json()
    assert dest["local_experiences"]["total"] >= 1


def test_host_crud_and_permissions(client, owner):
    b = _host_biz(client, owner)
    stays = client.get("/api/v1/registry", params={"type": "homestay", "district": b["district"], "status": "active"}).json()["items"]
    stay_ids = [s["id"] for s in stays if s["id"] != b["id"]][:2]
    body = {
        "business_id": b["id"],
        "title": "Test village walk with our family",
        "type": "village_walk",
        "description": "A short walk around the village fields with the host family.",
        "duration_hours": 2,
        "group_min": 2,
        "group_max": 6,
        "price_min": 300,
        "price_max": 500,
        "languages": ["Hindi", "Garhwali", "Klingon"],
        "months": [4, 5, 10],
        "stay_business_ids": stay_ids,
        "community_share": "Part of the fee goes to the village fund.",
    }
    r = client.post("/api/v1/business/experiences", json=body, headers=owner)
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["languages"] == ["Hindi", "Garhwali"] and e["status"] == "listed" and not e["synthetic"]
    assert client.get(f"/api/v1/local-experiences/{e['id']}").status_code == 200
    mine = client.get("/api/v1/business/experiences", headers=owner).json()
    assert any(x["id"] == e["id"] for x in mine["items"]) and mine["can_host"]
    bad = dict(body, group_min=8, group_max=3)
    assert client.post("/api/v1/business/experiences", json=bad, headers=owner).status_code == 422
    assert client.post("/api/v1/business/experiences", json=dict(body, stay_business_ids=["biz_s001"]), headers=owner).status_code == 422
    assert client.post("/api/v1/business/experiences", json=dict(body, destination_id="nainital"), headers=owner).status_code == 422
    up = client.patch(f"/api/v1/business/experiences/{e['id']}", json={"group_max": 8, "status": "paused"}, headers=owner)
    assert up.status_code == 200 and up.json()["group_max"] == 8 and up.json()["status"] == "paused"
    assert client.get(f"/api/v1/local-experiences/{e['id']}").status_code == 404  # paused: not public
    # Another business account cannot touch it; a hotel-only owner cannot host.
    agency = login(client, "demo.agency")
    assert client.patch(f"/api/v1/business/experiences/{e['id']}", json={"group_max": 9}, headers=agency).status_code == 404
    assert client.delete(f"/api/v1/business/experiences/{e['id']}", headers=agency).status_code == 404
    ag = client.get("/api/v1/business/businesses", headers=agency).json()["items"][0]
    assert client.post("/api/v1/business/experiences", json=dict(body, business_id=ag["id"]), headers=agency).status_code == 403
    assert client.post("/api/v1/business/experiences", json=body, headers=login(client, "demo.seeker")).status_code == 403
    assert client.post("/api/v1/business/experiences", json=body).status_code == 401
    gone = client.delete(f"/api/v1/business/experiences/{e['id']}", headers=owner)
    assert gone.status_code == 200 and gone.json()["status"] == "archived"
    assert all(x["id"] != e["id"] for x in client.get("/api/v1/business/experiences", headers=owner).json()["items"])


def test_join_request_scoping(client, owner):
    mine = client.get("/api/v1/business/experiences", headers=owner).json()["items"]
    e = next(x for x in mine if x["status"] == "listed")
    date_ok = _next_in(e["months"])
    body = {"name": "Asha", "group_size": e["group_min"], "date": date_ok, "contact": "+91-90000-99999 (test)", "note": "Two adults"}
    r = client.post(f"/api/v1/local-experiences/{e['id']}/join", json=body)
    assert r.status_code == 201, r.text
    rid = r.json()["request_id"]
    assert "contact" not in r.json()
    off = [m for m in range(1, 13) if m not in e["months"]]
    if off:
        assert client.post(f"/api/v1/local-experiences/{e['id']}/join", json=dict(body, date=_next_in(off))).status_code == 422
    assert client.post(f"/api/v1/local-experiences/{e['id']}/join", json=dict(body, group_size=99)).status_code == 422
    # The host sees it with the contact; other accounts and the public do not.
    reqs = client.get("/api/v1/business/experience-requests", headers=owner).json()
    got = next(x for x in reqs["items"] if x["id"] == rid)
    assert got["contact"].startswith("+91") and got["status"] == "pending"
    agency = login(client, "demo.agency")
    assert all(x["id"] != rid for x in client.get("/api/v1/business/experience-requests", headers=agency).json()["items"])
    assert client.post(f"/api/v1/business/experience-requests/{rid}", json={"action": "accept"}, headers=agency).status_code == 404
    assert client.get("/api/v1/business/experience-requests").status_code == 401
    assert client.get(f"/api/v1/local-experiences/{e['id']}").json().get("requests") is None
    ok = client.post(f"/api/v1/business/experience-requests/{rid}", json={"action": "accept"}, headers=owner)
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"
    assert client.post(f"/api/v1/business/experience-requests/{rid}", json={"action": "decline"}, headers=owner).status_code == 409


# ------------------------------------------------------------------ staffing agencies + HOI staffing requests
def _hotel_key(client, owner) -> tuple[dict, str]:
    items = client.get("/api/v1/business/businesses", headers=owner).json()["items"]
    hotel = next(b for b in items if b["type"] == "hotel" and b["status"] == "active")
    raw = client.post(f"/api/v1/business/businesses/{hotel['id']}/api-keys", json={"label": "HOI roster"}, headers=owner).json()["api_key"]
    return hotel, raw


def test_staffing_agency_role_and_offers(client):
    agency = login(client, "demo.agency")
    dash = client.get("/api/v1/staffing/mine", headers=agency).json()
    assert dash["agencies"] and dash["agencies"][0]["status"] == "active" and dash["summary"]["open_offers"] >= 1
    ag = dash["agencies"][0]
    assert ag["skills"] and ag["districts_served"]
    pub = client.get("/api/v1/staffing/offers").json()
    assert pub["total"] >= 10 and all(o["agency"]["reg_no"].startswith("UK-STF-") for o in pub["items"])
    assert all("phone" not in str(o).lower() for o in pub["items"])
    start = (date.today() + timedelta(days=20)).isoformat()
    end = (date.today() + timedelta(days=80)).isoformat()
    body = {
        "business_id": ag["id"],
        "skill": "housekeeping",
        "workers": 12,
        "available_from": start,
        "available_to": end,
        "note": "Trained pool",
    }
    r = client.post("/api/v1/staffing/offers", json=body, headers=agency)
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    assert r.json()["workers"] == 12 and r.json()["district"] == ag["district"]
    assert client.post("/api/v1/staffing/offers", json=dict(body, skill="astronaut"), headers=agency).status_code == 422
    owner = login(client, "demo.business")
    hotel = next(b for b in client.get("/api/v1/business/businesses", headers=owner).json()["items"] if b["type"] == "hotel")
    assert client.post("/api/v1/staffing/offers", json=dict(body, business_id=hotel["id"]), headers=owner).status_code == 403
    assert client.patch(f"/api/v1/staffing/offers/{oid}", json={"workers": 5}, headers=owner).status_code == 404
    w = client.patch(f"/api/v1/staffing/offers/{oid}", json={"status": "withdrawn"}, headers=agency)
    assert w.json()["status"] == "withdrawn"
    assert all(o["id"] != oid for o in client.get("/api/v1/staffing/offers").json()["items"])
    reg = client.get("/api/v1/registry", params={"type": "staffing_agency"}).json()
    assert reg["total"] >= 8
    meta = client.get("/api/v1/meta").json()
    assert any(t["key"] == "staffing_agency" for t in meta["business_types"])


def test_staffing_request_ingest(client, owner):
    hotel, raw = _hotel_key(client, owner)
    start = (date.today() + timedelta(days=5)).isoformat()
    end = (date.today() + timedelta(days=12)).isoformat()
    body = {
        "skill": "housekeeping",
        "district": hotel["district"],
        "from": start,
        "to": end,
        "openings": 3,
        "shift_note": "Morning shifts 7-15",
        "source": "hoi_roster_shortage",
        "source_id": "HS-2026-W45-housekeeping",
    }
    assert client.post("/api/v1/ingest/staffing-request", json=body).status_code == 401
    assert client.post("/api/v1/ingest/staffing-request", json=body, headers={"X-API-Key": "uthp_wrong"}).status_code == 401
    h = {"X-API-Key": raw}
    r1 = client.post("/api/v1/ingest/staffing-request", json=body, headers=h)
    assert r1.status_code == 201, r1.text
    j1 = r1.json()
    assert j1["result"] == "created" and j1["agencies_notified"] >= 1
    job = client.get(f"/api/v1/jobs/{j1['job_id']}").json()
    assert job["via_hoi"] and job["staffing_request"]["label"] == "Staffing request via HOI"
    assert job["openings"] == 3 and job["season_from"] == start and job["skills"][0]["key"] == "housekeeping"
    hoi = client.get("/api/v1/jobs", params={"source": "hoi"}).json()
    assert any(i["id"] == j1["job_id"] for i in hoi["items"]) and all(i["via_hoi"] for i in hoi["items"])
    # Idempotent per source id: same call -> same job, no new notifications.
    n_before = mongo.db().notifications.count_documents({"job_id": j1["job_id"]})
    r2 = client.post("/api/v1/ingest/staffing-request", json=body, headers=h).json()
    assert r2["result"] == "unchanged" and r2["job_id"] == j1["job_id"] and r2["agencies_notified"] == 0
    r3 = client.post("/api/v1/ingest/staffing-request", json=dict(body, openings=5), headers=h).json()
    assert r3["result"] == "updated" and r3["job_id"] == j1["job_id"] and r3["openings"] == 5
    assert mongo.db().notifications.count_documents({"job_id": j1["job_id"]}) == n_before
    assert mongo.db().job_posts.count_documents({"staffing_request.source_id": body["source_id"]}) == 1
    other = client.post("/api/v1/ingest/staffing-request", json=dict(body, source_id="HS-2026-W46-housekeeping"), headers=h).json()
    assert other["job_id"] != j1["job_id"]
    # Validation: wrong district, unknown skill, unknown source, window over.
    assert client.post("/api/v1/ingest/staffing-request", json=dict(body, district="almora"), headers=h).status_code == 422
    assert client.post("/api/v1/ingest/staffing-request", json=dict(body, skill="astronaut"), headers=h).status_code == 422
    assert client.post("/api/v1/ingest/staffing-request", json=dict(body, source="manual"), headers=h).status_code == 422
    past = (date.today() - timedelta(days=3)).isoformat()
    assert (
        client.post("/api/v1/ingest/staffing-request", json=dict(body, source_id="x", **{"from": past, "to": past}), headers=h).status_code
        == 422
    )
    # HOI role names are mapped (food_beverage -> F&B service).
    fb = client.post("/api/v1/ingest/staffing-request", json=dict(body, skill="food_beverage", source_id="fb-1"), headers=h).json()
    assert client.get(f"/api/v1/jobs/{fb['job_id']}").json()["skills"][0]["key"] == "fb_service"

    # The demo agency (serves Rudraprayag, pools housekeeping) is notified and can respond; the hotel owner sees it.
    agency = login(client, "demo.agency")
    dash = client.get("/api/v1/staffing/mine", headers=agency).json()
    if hotel["district"] in {d["id"] for d in dash["agencies"][0]["districts_served"]}:
        assert any(n["job_id"] == j1["job_id"] for n in dash["notifications"])
        assert any(rq["id"] == j1["job_id"] for rq in dash["open_requests"])
        ag = dash["agencies"][0]["id"]
        resp = client.post(
            f"/api/v1/staffing/requests/{j1['job_id']}/respond",
            json={"business_id": ag, "workers": 4, "note": "Can start Monday"},
            headers=agency,
        )
        assert resp.status_code == 201, resp.text
        again = client.post(f"/api/v1/staffing/requests/{j1['job_id']}/respond", json={"business_id": ag, "workers": 5}, headers=agency)
        assert again.json()["id"] == resp.json()["id"] and again.json()["workers"] == 5
        owner_view = client.get(f"/api/v1/jobs/{j1['job_id']}", headers=owner).json()
        assert [x["workers"] for x in owner_view["agency_responses"]] == [5]
        assert "agency_responses" not in client.get(f"/api/v1/jobs/{j1['job_id']}").json()
        notes = client.get("/api/v1/business/notifications", headers=owner).json()
        assert any(n["kind"] == "agency_response" and n["job_id"] == j1["job_id"] for n in notes["items"])
    # A hotel owner cannot respond as an agency.
    assert (
        client.post(
            f"/api/v1/staffing/requests/{j1['job_id']}/respond", json={"business_id": hotel["id"], "workers": 1}, headers=owner
        ).status_code
        == 403
    )


def test_staffing_request_platform_client_body(client, owner):
    """The exact body the HOI platform client sends (idempotency on external_id; 201, then 200 with the same job)."""
    hotel, raw = _hotel_key(client, owner)
    body = {
        "external_id": "himsagar-2026-W46-housekeeping",
        "department": "housekeeping",
        "skill": "housekeeping",
        "date_from": (date.today() + timedelta(days=4)).isoformat(),
        "date_to": (date.today() + timedelta(days=10)).isoformat(),
        "openings": 2,
        "note": "Roster week short by 2 housekeeping shifts",
    }
    h = {"X-API-Key": raw}
    r1 = client.post("/api/v1/ingest/staffing-request", json=body, headers=h)
    assert r1.status_code == 201, r1.text
    j = r1.json()
    assert j["job_id"].startswith("JOB-") and j["status"] == "open" and j["result"] == "created"
    r2 = client.post("/api/v1/ingest/staffing-request", json=body, headers=h)
    assert r2.status_code == 200 and r2.json()["job_id"] == j["job_id"] and r2.json()["status"] == "open"
    job = client.get(f"/api/v1/jobs/{j['job_id']}").json()
    assert job["via_hoi"] and job["openings"] == 2 and job["staffing_request"]["shift_note"] == body["note"]
    assert job["season_from"] == body["date_from"] and job["season_to"] == body["date_to"]
    # department is used when skill is not a known key; unknown extra fields are still rejected
    alt = dict(body, external_id="himsagar-2026-W46-fb", skill="Waiter", department="food_beverage")
    r3 = client.post("/api/v1/ingest/staffing-request", json=alt, headers=h)
    assert r3.status_code == 201, r3.text
    assert client.get(f"/api/v1/jobs/{r3.json()['job_id']}").json()["skills"][0]["key"] == "fb_service"
    assert client.post("/api/v1/ingest/staffing-request", json=dict(body, hotel_name="x"), headers=h).status_code == 422
    missing = {k: v for k, v in body.items() if k != "date_to"}
    assert client.post("/api/v1/ingest/staffing-request", json=missing, headers=h).status_code == 422
