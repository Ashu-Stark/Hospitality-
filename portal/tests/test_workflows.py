"""Grievances, applications, renewals, district scoping."""

import re

from conftest import login
from hoi_portal import mongo


def _register_business(client, username: str) -> dict:
    r = client.post("/api/v1/auth/register", json={"username": username, "password": "a-long-test-password"})
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "business"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ------------------------------------------------------------------ grievances
def test_grievance_file_track_and_officer_resolve(client, officer):
    r = client.post(
        "/api/v1/grievances",
        json={
            "category": "overcharging",
            "district": "rudraprayag",
            "description": "Charged more than the displayed room rate (test).",
            "contact": "test-contact@example.invalid",
        },
    )
    assert r.status_code == 201, r.text
    g = r.json()
    ticket, code = g["ticket_id"], g["tracking_code"]
    assert re.match(r"^UTHP-G-\d{6}$", ticket) and re.match(r"^\d{6}$", code) and g["status"] == "received"
    assert "contact" not in g and "description" not in g

    t = client.post("/api/v1/grievances/track", json={"ticket_id": ticket, "tracking_code": code})
    assert t.status_code == 200 and t.json()["status"] == "received" and "contact" not in t.json()
    wrong = "000000" if code != "000000" else "111111"
    assert client.post("/api/v1/grievances/track", json={"ticket_id": ticket, "tracking_code": wrong}).status_code == 404

    # Officer sees the private contact; moves it through the workflow.
    og = client.get(f"/api/v1/officer/grievances/{ticket}", headers=officer).json()
    assert og["contact"] == "test-contact@example.invalid"
    r = client.post(
        f"/api/v1/officer/grievances/{ticket}", json={"status": "in_progress", "note": "Calling the business."}, headers=officer
    )
    assert r.json()["status"] == "in_progress"
    client.post(f"/api/v1/officer/grievances/{ticket}", json={"note": "internal only", "public": False}, headers=officer)
    assert (
        client.post(f"/api/v1/officer/grievances/{ticket}", json={"status": "resolved"}, headers=officer).status_code == 422
    )  # note required
    r = client.post(
        f"/api/v1/officer/grievances/{ticket}", json={"status": "resolved", "note": "Refund of the difference agreed."}, headers=officer
    )
    assert r.status_code == 200 and r.json()["resolved_at"]
    assert client.post(f"/api/v1/officer/grievances/{ticket}", json={"status": "assigned"}, headers=officer).status_code == 409

    tracked = client.post("/api/v1/grievances/track", json={"ticket_id": ticket, "tracking_code": code}).json()
    assert tracked["status"] == "resolved" and tracked["overdue"] is False
    notes = [x["note"] for x in tracked["timeline"]]
    assert "Refund of the difference agreed." in notes and "internal only" not in notes


def test_grievance_validation(client):
    bad = client.post("/api/v1/grievances", json={"category": "nope", "district": "rudraprayag", "description": "long enough text"})
    assert bad.status_code == 422
    short = client.post("/api/v1/grievances", json={"category": "other", "district": "rudraprayag", "description": "short"})
    assert short.status_code == 422 and short.json()["errors"][0]["field"] == "description"


# ------------------------------------------------------------------ scoping
def test_district_officer_is_scoped_to_own_district(client, officer, admin):
    apps = client.get("/api/v1/officer/applications", headers=officer).json()
    assert apps["total"] > 0 and all(a["district"] == "rudraprayag" for a in apps["items"])
    gr = client.get("/api/v1/officer/grievances", headers=officer).json()
    assert gr["total"] > 0 and all(g["district"] == "rudraprayag" for g in gr["items"])
    for path in ("/api/v1/officer/grievances", "/api/v1/officer/applications", "/api/v1/analytics/kpis", "/api/v1/officer/businesses"):
        assert client.get(path, params={"district": "chamoli"}, headers=officer).status_code == 403
    other = mongo.db().grievances.find_one({"district": {"$ne": "rudraprayag"}})
    assert client.get(f"/api/v1/officer/grievances/{other['ticket_id']}", headers=officer).status_code == 404
    assert client.post(f"/api/v1/officer/grievances/{other['ticket_id']}", json={"note": "x"}, headers=officer).status_code == 404
    other_app = mongo.db().applications.find_one({"district": {"$ne": "rudraprayag"}, "status": "submitted"})
    r = client.post(f"/api/v1/officer/applications/{other_app['id']}/decision", json={"action": "approve"}, headers=officer)
    assert r.status_code == 404
    adv = mongo.db().advisories.find_one({"district": "chamoli"})
    assert client.patch(f"/api/v1/officer/advisories/{adv['id']}", json={"title": "hijack"}, headers=officer).status_code == 404
    # Officers always post for their own district.
    r = client.post("/api/v1/officer/advisories", json={"title": "Test", "status": "open", "district": "chamoli"}, headers=officer)
    assert r.status_code == 403
    k = client.get("/api/v1/analytics/kpis", headers=officer).json()
    assert k["scope"]["district"] == "rudraprayag"
    # The state admin sees everything.
    assert {g["district"] for g in client.get("/api/v1/officer/grievances", params={"page_size": 100}, headers=admin).json()["items"]} != {
        "rudraprayag"
    }


def test_roles_are_enforced(client, owner):
    assert client.get("/api/v1/officer/applications").status_code == 401
    assert client.get("/api/v1/officer/applications", headers=owner).status_code == 403
    assert client.get("/api/v1/analytics/kpis", headers=owner).status_code == 403
    assert client.get("/api/v1/admin/users", headers=login(client, "demo.officer.rudraprayag")).status_code == 403
    assert client.get("/api/v1/business/dashboard", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_officer_advisory_and_event_crud(client, officer):
    r = client.post(
        "/api/v1/officer/advisories",
        json={"kind": "road", "status": "caution", "title": "Test caution near Gaurikund", "destination_id": "kedarnath", "reason": "test"},
        headers=officer,
    )
    assert r.status_code == 201 and r.json()["district"] == "rudraprayag" and r.json()["sample"] is False
    aid = r.json()["id"]
    assert any(a["id"] == aid for a in client.get("/api/v1/advisories", params={"destination": "kedarnath"}).json()["items"])
    assert client.patch(f"/api/v1/officer/advisories/{aid}", json={"status": "closed"}, headers=officer).json()["status"] == "closed"
    assert client.delete(f"/api/v1/officer/advisories/{aid}", headers=officer).json()["active"] is False
    assert all(a["id"] != aid for a in client.get("/api/v1/advisories").json()["items"])
    bad = client.post(
        "/api/v1/officer/advisories", json={"title": "x road", "kind": "road", "destination_id": "badrinath"}, headers=officer
    )
    assert bad.status_code == 422

    e = client.post(
        "/api/v1/officer/events",
        json={
            "name": "Test trek clean-up drive",
            "start_date": "2026-11-02",
            "end_date": "2026-11-03",
            "destination_ids": ["chopta"],
            "crowd_impact": "low",
        },
        headers=officer,
    )
    assert e.status_code == 201 and e.json()["months"] == [11]
    eid = e.json()["id"]
    assert any(x["id"] == eid for x in client.get("/api/v1/events", params={"month": 11}).json()["items"])
    assert client.delete("/api/v1/officer/events/char-dham-closing", headers=officer).status_code == 404  # curated, not editable
    assert client.delete(f"/api/v1/officer/events/{eid}", headers=officer).status_code == 204


# ------------------------------------------------------------------ applications
def test_application_approve_issues_registration_number(client, officer):
    biz = _register_business(client, "test.homestay.owner")
    body = {
        "business_name": "Test Sample Homestay T01, Chopta",
        "type": "homestay",
        "district": "rudraprayag",
        "destination_id": "chopta",
        "capacity": 4,
        "beds": 8,
        "languages": ["Hindi", "English", "Klingon"],
        "documents": {"identity_proof": True, "address_proof": True, "property_papers": False},
    }
    a = client.post("/api/v1/business/applications", json=body, headers=biz)
    assert a.status_code == 201, a.text
    app = a.json()
    assert app["status"] == "submitted" and app["missing_documents"] == ["property_papers"] and "Klingon" not in app["languages"]
    # Cannot approve with a required document missing.
    assert client.post(f"/api/v1/officer/applications/{app['id']}/decision", json={"action": "approve"}, headers=officer).status_code == 422
    assert (
        client.post(f"/api/v1/officer/applications/{app['id']}/decision", json={"action": "request_changes"}, headers=officer).status_code
        == 422
    )
    r = client.post(
        f"/api/v1/officer/applications/{app['id']}/decision",
        json={"action": "request_changes", "reason": "Tick property papers."},
        headers=officer,
    )
    assert r.json()["status"] == "changes_requested"
    mine = client.get(f"/api/v1/business/applications/{app['id']}", headers=biz).json()
    assert mine["reason"] == "Tick property papers." and "owner_user_id" not in mine
    docs = dict(body["documents"], property_papers=True)
    assert client.put(f"/api/v1/business/applications/{app['id']}", json={"documents": docs}, headers=biz).json()["status"] == "submitted"
    r = client.post(f"/api/v1/officer/applications/{app['id']}/decision", json={"action": "approve"}, headers=officer)
    assert r.status_code == 200, r.text
    reg = r.json()["reg_no"]
    assert re.match(r"^UK-HMS-RUD-\d{5}$", reg)
    assert client.post(f"/api/v1/officer/applications/{app['id']}/decision", json={"action": "approve"}, headers=officer).status_code == 409
    v = client.get("/api/v1/registry/verify", params={"reg_no": reg}).json()
    assert v["valid"] and v["business"]["name"] == body["business_name"] and v["business"]["verified"]
    dash = client.get("/api/v1/business/dashboard", headers=biz).json()
    assert dash["summary"]["businesses"] == 1 and dash["businesses"][0]["reg_no"] == reg
    # Numbers are sequential per (type, district).
    nums = sorted(int(b["reg_no"][-5:]) for b in mongo.db().businesses.find({"reg_no": {"$regex": "^UK-HMS-RUD-"}}))
    assert int(reg[-5:]) == nums[-1] and len(nums) == len(set(nums))


def test_renewal_flow(client, owner, officer):
    mine = client.get("/api/v1/business/businesses", headers=owner).json()["items"]
    due = next(b for b in mine if b["renewal_due"])
    not_due = next(b for b in mine if not b["renewal_due"])
    assert client.post(f"/api/v1/business/businesses/{not_due['id']}/renew", headers=owner).status_code == 409
    r = client.post(f"/api/v1/business/businesses/{due['id']}/renew", headers=owner)
    assert r.status_code == 201 and r.json()["kind"] == "renewal" and r.json()["reg_no"] == due["reg_no"]
    assert client.post(f"/api/v1/business/businesses/{due['id']}/renew", headers=owner).status_code == 409
    ok = client.post(f"/api/v1/officer/applications/{r.json()['id']}/decision", json={"action": "approve"}, headers=officer)
    assert ok.status_code == 200
    after = client.get(f"/api/v1/business/businesses/{due['id']}", headers=owner).json()
    assert after["valid_until"] > due["valid_until"] and after["status"] == "active" and after["renewal_due"] is False
    # Someone else's business is invisible to this owner.
    other = mongo.db().businesses.find_one({"owner_user_id": {"$ne": None}, "district": "chamoli"})
    if other:
        assert client.get(f"/api/v1/business/businesses/{other['id']}", headers=owner).status_code == 404
