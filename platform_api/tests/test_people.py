"""Homestay mode, recognition points (positive-only incentives) and staffing requests to the tourism portal. SYNTHETIC data.

Recognition facts are written straight into a fresh test tenant (jobs, after photos, feedback) so every number is controlled;
visibility and roles are checked through the API on the demo tenant. The tourism portal is always a fake: no network.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from conftest import auth

from hoi_platform import mongo, seed
from hoi_platform.services import dispatch, portal_client, recognition, staffing, tenants

MONTH = "2026-03"
T0 = datetime(2026, 3, 10, 6, 0, tzinfo=UTC)


# ------------------------------------------------------------------ homestay mode
def test_demo_has_a_homestay_property_in_homestay_mode(client, owner):
    props = client.get("/workspace/properties", headers=owner).json()
    hs = next(p for p in props if p["name"] == seed.HOMESTAY_NAME)
    assert "(demo)" in hs["name"] and hs["rooms"] == 6 and hs["mode"] == "homestay"
    assert props[0]["mode"] == "hotel"
    rooms = client.get("/rooms", params={"property_id": hs["id"]}, headers=owner).json()
    assert sorted(r["number"] for r in rooms["rooms"]) == ["DN1", "DN2", "DN3", "DN4", "DN5", "DN6"]
    staff = [s for s in client.get("/workspace/staff", headers=owner).json() if s.get("property_id") == hs["id"]]
    assert [(s["employee_id"], s["role_title"]) for s in staff] == [("DN01", "Host"), ("DN02", "Cook"), ("DN03", "Helper")]
    assert not [k for s in staff for k in s if k.lower() in ("name", "gender", "age", "phone")]
    prof = client.get("/hotel/profile", params={"property_id": hs["id"]}, headers=owner).json()
    assert prof["exists"] and prof["display_name"] == "Deodar Nest Homestay, Dhanaulti (demo)" and prof["synthetic"]
    # the homestay owner demo account opens the homestay first; the helper's app is in homestay mode
    me = client.get("/auth/me", headers=auth(client, "demo.homestay")).json()["user"]
    assert me["role"] == "owner" and me["prefs"]["property_id"] == hs["id"]
    shifts = client.get("/me/shifts", headers=auth(client, "DN03")).json()
    assert shifts["mode"] == "homestay" and shifts["property"]["id"] == hs["id"] and shifts["on_shift_now"]
    assert client.get("/me/shifts", headers=auth(client, "HS05")).json()["mode"] == "hotel"


def test_small_properties_default_to_homestay():
    t = tenants.create_tenant("Mode test group (test)", plan="growth")
    assert tenants.add_property(t["id"], "Tiny", "", 10)["mode"] == "homestay"  # <= 10 rooms (ASSUMED threshold)
    assert tenants.add_property(t["id"], "Bigger", "", 11)["mode"] == "hotel"
    assert tenants.add_property(t["id"], "Small hotel", "", 8, mode="hotel")["mode"] == "hotel"
    # a property stored before modes existed gets the default from its room count
    mongo.col("properties").insert_one({"id": "prop_legacy", "tenant_id": t["id"], "name": "Legacy", "rooms": 6, "created_at": mongo.now()})
    assert next(p for p in tenants.properties(t["id"]) if p["id"] == "prop_legacy")["mode"] == "homestay"


def test_owner_switches_mode_and_others_cannot(client, owner, hr):
    first = client.get("/workspace/properties", headers=owner).json()[0]["id"]
    assert client.patch(f"/workspace/properties/{first}", json={"mode": "homestay"}, headers=hr).status_code == 403
    assert client.patch(f"/workspace/properties/{first}", json={"mode": "villa"}, headers=owner).status_code == 422
    assert client.patch(f"/workspace/properties/{first}", json={"colour": "red"}, headers=owner).status_code == 422
    r = client.patch(f"/workspace/properties/{first}", json={"mode": "homestay"}, headers=owner)
    assert r.status_code == 200 and r.json()["mode"] == "homestay"
    r = client.patch(f"/workspace/properties/{first}", json={"mode": "hotel"}, headers=owner)
    assert r.json()["mode"] == "hotel"
    assert client.patch("/workspace/properties/prop_nope", json={"mode": "hotel"}, headers=owner).status_code == 404


def test_homestay_jobs_go_to_the_homestay_team(client, owner):
    hs = next(p for p in client.get("/workspace/properties", headers=owner).json() if p["mode"] == "homestay")
    room = next(r for r in client.get("/rooms", params={"property_id": hs["id"]}, headers=owner).json()["rooms"] if r["number"] == "DN2")
    # the hotel's roster snapshot has nobody from the homestay on shift: homestay teams need no roster
    client.put("/dispatch/context", json={"working": {"HS05": "housekeeping"}, "bands": {}}, headers=owner)
    tea = client.post(f"/public/guest/{room['guest_token']}/requests", json={"key": "tea"})
    assert tea.status_code in (200, 201)
    job = next(j for j in client.get("/dispatch/jobs", headers=owner).json() if j.get("room") == "DN2")
    # nobody in fnb_service at the homestay: anyone of the 3-person team may be offered it, never hotel staff
    assert job["offer_to"] in ("DN01", "DN02", "DN03")
    hotel_job = client.post(
        "/dispatch/jobs", json={"title": "Towels", "department": "housekeeping", "room": "101", "urgency": "low"}, headers=owner
    ).json()
    assert hotel_job["offer_to"] == "HS05"
    # offer window: a family team gets 15 minutes to answer (the card shows no countdown bar); the hotel keeps its 30 s
    assert 14 * 60 < job["seconds_left"] <= dispatch.HOMESTAY_OFFER_SECONDS
    assert hotel_job["seconds_left"] <= 30


# ------------------------------------------------------------------ recognition points
@pytest.fixture(scope="module")
def rec():
    t = tenants.create_tenant("Recognition test hotel (test)", plan="growth")
    prop = tenants.add_property(t["id"], "Rec hotel", "", 20)
    tenants.import_staff(
        t["id"],
        [{"employee_id": e, "department": "housekeeping"} for e in ("R1", "R2", "R3", "R4")]
        + [{"employee_id": "RM", "department": "management"}],
    )
    tenants.update_property(t["id"], prop["id"], incentive_monthly_budget_cap=1000)
    return t["id"], prop["id"]


def _job(tid, emp, *, minutes=20, urgency="medium", kind="general", inspection=None, photo=True, room_id=None, at=T0, n=[0]):  # noqa: B006
    n[0] += 1
    jid = f"job_rec{n[0]}"
    done = at + timedelta(minutes=minutes)
    mongo.col("jobs").insert_one(
        {
            "id": jid,
            "tenant_id": tid,
            "title": "t",
            "department": "housekeeping",
            "status": "done",
            "assigned_to": emp,
            "urgency": urgency,
            "kind": kind,
            "inspection": inspection,
            "room_id": room_id,
            "created_at": at,
            "accepted_at": at,
            "started_at": at,
            "done_at": done,
        }
    )
    if photo:
        mongo.col("photos").insert_one({"id": f"ph_{jid}", "tenant_id": tid, "job_id": jid, "kind": "after"})
    return jid


def _row(out, emp):
    return next(w for w in out["workers"] if w["employee_id"] == emp)


def test_recognition_weights_events_and_no_negatives(rec):
    tid, pid = rec
    _job(tid, "R1", minutes=20)  # on time (medium target 60) + photo = 10 + 2
    _job(tid, "R1", minutes=200, photo=False)  # late, no photo: 0 points, never negative
    _job(tid, "R1", minutes=30, kind="cleaning", inspection="pass")  # 10 + 2 + 5
    _job(tid, "R1", minutes=30, kind="cleaning", inspection="fail")  # 10 + 2, a failed inspection takes nothing away
    _job(tid, "R1", minutes=30, kind="guest", room_id="room_r1")  # 10 + 2
    mongo.col("guest_feedback").insert_many(
        [
            {"id": "fb1", "tenant_id": tid, "room_id": "room_r1", "stay": 1, "rating": 5, "created_at": T0 + timedelta(hours=5)},
            {"id": "fb2", "tenant_id": tid, "room_id": "room_r1", "stay": 2, "rating": 2, "created_at": T0 + timedelta(hours=6)},
        ]
    )
    out = recognition.compute(tid, pid, MONTH)
    r1 = _row(out, "R1")
    by = {b["key"]: b for b in r1["breakdown"]}
    assert (by["on_time_job"]["count"], by["after_photo"]["count"], by["inspection_pass"]["count"], by["guest_feedback_good"]["count"]) == (
        4,
        4,
        1,
        1,
    )
    assert r1["points"] == 4 * 10 + 4 * 2 + 5 + 5 == 58 and r1["jobs_done"] == 5 and r1["eligible"]
    assert all(w["points"] >= 0 and all(b["points"] >= 0 for b in w["breakdown"]) for w in out["workers"])
    assert "RM" not in {w["employee_id"] for w in out["workers"]}  # management side not in the staff scheme
    assert "never used for discipline" in out["note"]
    assert recognition.compute(tid, pid, "2026-04")["team"]["total_points"] == 0  # month window


def test_recognition_caps_min_jobs_and_budget_share(rec):
    tid, pid = rec
    at = datetime(2026, 5, 5, 6, 0, tzinfo=UTC)
    for _ in range(5):
        _job(tid, "R2", at=at)  # 5 x 12 = 60
    for _ in range(15):
        _job(tid, "R3", at=at)  # 15 x 12 = 180
    for _ in range(2):
        _job(tid, "R4", at=at)  # 24 points but only 2 jobs: below min_jobs
    out = recognition.compute(tid, pid, "2026-05")
    r2, r3, r4 = (_row(out, e) for e in ("R2", "R3", "R4"))
    assert (r2["points"], r3["points"], r4["points"]) == (60, 180, 24)
    assert not r4["eligible"] and r4["estimated_reward_inr"] == 0 and r4["points"] == 24  # points still shown
    # shares of the eligible pool (60 + 180), each capped at max_share (25 %) of the 1000 budget
    assert r2["share"] == 0.25 and r3["share"] == 0.75
    assert r2["estimated_reward_inr"] == 250 and r3["estimated_reward_inr"] == 250 and out["unallocated_inr"] == 500
    # owner settings: a wider max share and a lower points cap
    tenants.update_property(tid, pid, recognition=recognition.validate_config({"max_share": 1.0, "max_points_per_worker": 100}))
    out = recognition.compute(tid, pid, "2026-05")
    r2, r3 = _row(out, "R2"), _row(out, "R3")
    assert r3["points"] == 100 and r3["raw_points"] == 180 and r3["capped"]
    assert (r2["estimated_reward_inr"], r3["estimated_reward_inr"]) == (370, 620)  # 60/160 and 100/160 of 1000, rounded down to 10
    # weights are configurable but positive only
    tenants.update_property(tid, pid, recognition=recognition.validate_config({"weights": {"on_time_job": 4, "after_photo": 0}}))
    assert _row(recognition.compute(tid, pid, "2026-05"), "R2")["points"] == 20
    with pytest.raises(Exception, match="positive only"):
        recognition.validate_config({"weights": {"on_time_job": -5}})
    # no budget set: points still count, no money estimate
    tenants.update_property(tid, pid, incentive_monthly_budget_cap=0)
    out = recognition.compute(tid, pid, "2026-05")
    assert not out["budget_set"] and all(w["estimated_reward_inr"] == 0 for w in out["workers"])


def test_recognition_visibility_own_only(client, owner, hr, store):
    worker = auth(client, "HS05")
    me = client.get("/me/recognition", headers=worker)
    assert me.status_code == 200
    body = me.json()
    assert body["employee_id"] == "HS05" and "workers" not in body and "leaderboard" not in body
    assert set(body["team"]) == {"members", "people_with_points", "total_points", "average_points"}
    assert "HS0" not in str(body["team"]) and "never used for discipline" in body["note"]
    assert body["how_to_earn"] and body["weights"]["on_time_job"] == 10
    assert client.get("/recognition/summary", headers=worker).status_code == 403
    assert client.get("/recognition/summary", headers=store).status_code == 403
    s = client.get("/recognition/summary", headers=hr).json()
    ids = [w["employee_id"] for w in s["workers"]]
    assert ids == sorted(ids) and "leaderboard" not in s  # listed by id, not ranked
    hk = client.get("/recognition/summary", headers=auth(client, "demo.housekeeping")).json()
    assert hk["department"] == "housekeeping" and {w["department"] for w in hk["workers"]} <= {"housekeeping"}
    # a ranked leaderboard only when the owner opts in
    first = client.get("/workspace/properties", headers=owner).json()[0]["id"]
    client.patch(f"/workspace/properties/{first}", json={"recognition_leaderboard_opt_in": True}, headers=owner)
    try:
        assert "leaderboard" in client.get("/recognition/summary", headers=hr).json()
        assert "leaderboard" in client.get("/me/recognition", headers=worker).json()
    finally:
        client.patch(f"/workspace/properties/{first}", json={"recognition_leaderboard_opt_in": False}, headers=owner)
    neg = client.patch(f"/workspace/properties/{first}", json={"recognition": {"weights": {"on_time_job": -1}}}, headers=owner)
    assert neg.status_code == 422


# ------------------------------------------------------------------ staffing requests
class FakePortal:
    def __init__(self, fail: bool = False):
        self.fail, self.calls = fail, []

    def __call__(self, payload: dict, api_key: str) -> dict:
        self.calls.append((payload, api_key))
        if self.fail:
            raise portal_client.PortalError("The tourism portal could not be reached (ConnectError).")
        return {"id": "portal_req_1", "status": "received"}


KEY = "pk_test_SECRET_123"


def _homestay(client, owner):
    return next(p for p in client.get("/workspace/properties", headers=owner).json() if p["mode"] == "homestay")["id"]


D0 = date.today() + timedelta(days=5)  # relative: the portal (and now the platform) refuse windows already over
REQ = {"department": "housekeeping", "skill": "room_cleaning", "date_from": D0.isoformat(),
       "date_to": (D0 + timedelta(days=2)).isoformat(), "openings": 2}


def test_staffing_request_forwarded_with_the_property_key(client, owner, monkeypatch):
    pid = _homestay(client, owner)
    fake = FakePortal()
    monkeypatch.setattr(staffing.portal_client, "send", fake)
    r = client.patch(f"/workspace/properties/{pid}", json={"portal_api_key": KEY}, headers=owner)
    assert r.status_code == 200 and r.json()["portal_key_set"] and KEY not in r.text
    out = client.post(
        "/staffing/requests",
        json={**REQ, "property_id": pid, "note": "Wedding weekend, call 9876543210", "source": "roster_shortage"},
        headers=owner,
    )
    assert out.status_code == 201, out.text
    j = out.json()
    assert j["status"] == "sent" and j["portal_ref"] == "portal_req_1" and j["attempts"] == 1 and j["property_id"] == pid
    ((payload, key),) = fake.calls
    assert key == KEY and payload["external_id"] == j["id"] and payload["openings"] == 2 and payload["department"] == "housekeeping"
    assert "9876543210" not in payload["note"]  # phone numbers masked
    listed = client.get("/staffing/requests", params={"property_id": pid}, headers=owner).json()
    assert listed[0]["id"] == j["id"]
    everything = (
        str(listed)
        + str(client.get("/workspace/properties", headers=owner).json())
        + str(client.get("/workspace/audit", headers=owner).json())
    )
    assert KEY not in everything and "_portal_key" not in everything  # the key is never returned or logged


def test_staffing_request_failure_stays_pending_then_retry(client, owner, hr, monkeypatch):
    pid = _homestay(client, owner)
    client.patch(f"/workspace/properties/{pid}", json={"portal_api_key": KEY}, headers=owner)
    monkeypatch.setattr(staffing.portal_client, "send", FakePortal(fail=True))
    j = client.post("/staffing/requests", json={**REQ, "property_id": pid}, headers=hr).json()
    assert j["status"] == "pending_send" and "could not be reached" in j["last_error"] and j["attempts"] == 1
    ok = FakePortal()
    monkeypatch.setattr(staffing.portal_client, "send", ok)
    again = client.post(f"/staffing/requests/{j['id']}/send", headers=owner).json()
    assert again["status"] == "sent" and again["attempts"] == 2 and again["last_error"] is None and len(ok.calls) == 1
    assert client.post(f"/staffing/requests/{j['id']}/send", headers=owner).json()["attempts"] == 2  # sent: not sent twice
    # no key saved -> pending with a plain reason, nothing sent
    client.patch(f"/workspace/properties/{pid}", json={"portal_api_key": ""}, headers=owner)
    calls = FakePortal()
    monkeypatch.setattr(staffing.portal_client, "send", calls)
    nokey = client.post("/staffing/requests", json={**REQ, "property_id": pid}, headers=owner).json()
    assert nokey["status"] == "pending_send" and "API key" in nokey["last_error"] and not calls.calls


def test_staffing_request_validation_and_roles(client, owner, store):
    worker = auth(client, "HS05")
    assert client.post("/staffing/requests", json=REQ, headers=worker).status_code == 403
    assert client.post("/staffing/requests", json=REQ, headers=store).status_code == 403
    assert client.post("/staffing/requests", json={**REQ, "openings": 0}, headers=owner).status_code == 422
    before = (D0 - timedelta(days=1)).isoformat()
    assert client.post("/staffing/requests", json={**REQ, "date_to": before}, headers=owner).status_code == 422
    past = (date.today() - timedelta(days=3)).isoformat()
    r = client.post("/staffing/requests", json={**REQ, "date_from": past, "date_to": past}, headers=owner)
    assert r.status_code == 422 and "already over" in r.text
    far = (date.today() + timedelta(days=staffing.PORTAL_MAX_LEAD_DAYS + 1)).isoformat()  # e.g. the 2029 demo roster week
    r = client.post("/staffing/requests", json={**REQ, "date_from": far, "date_to": far}, headers=owner)
    assert r.status_code == 422 and "within 180 days" in r.text
    assert client.post("/staffing/requests", json={**REQ, "worker_name": "X"}, headers=owner).status_code == 422  # no extra fields
    assert client.post("/staffing/requests", json={**REQ, "property_id": "prop_other"}, headers=owner).status_code == 404


def test_payload_fits_the_portal_limits():
    base = {"id": "stf_1", "department": "kitchen", "date_from": "2026-11-01", "date_to": "2026-11-02", "openings": 1}
    # free text skill -> the department's portal key; the words go into the note
    p = staffing.payload({**base, "skill": "tandoor, North Indian curries", "note": "Wedding"})
    assert p["skill"] == "cook_indian" and p["note"] == "Skill: tandoor, North Indian curries. Wedding"
    assert set(p) == {"external_id", "department", "skill", "date_from", "date_to", "openings", "note"}
    # a key-like skill is sent as it is (the portal maps or falls back to the department)
    assert staffing.payload({**base, "skill": "kitchen_helper"})["skill"] == "kitchen_helper"
    long = staffing.payload({**base, "skill": "x " * 30, "note": "n" * 500})
    assert len(long["skill"]) <= staffing.PORTAL_SKILL_MAX and len(long["note"]) == staffing.PORTAL_NOTE_MAX
    assert staffing.payload({**base, "department": "spa", "skill": ""})["skill"] == "spa"  # unmapped: the department


def test_portal_rejection_reason_is_shown(monkeypatch):
    class R:
        status_code = 422

        def json(self):
            return {"detail": "The staffing window starts more than 180 days from now."}

    monkeypatch.setattr(portal_client.httpx, "request", lambda *a, **k: R())
    with pytest.raises(portal_client.PortalError) as e:
        portal_client.send({"external_id": "a"}, "k1")
    assert e.value.message == "The tourism portal answered HTTP 422: The staffing window starts more than 180 days from now."
    assert "k1" not in e.value.message


def test_portal_client_retries_once_on_a_cold_start(monkeypatch):
    calls = []

    class R:
        status_code = 201

        def json(self):
            return {"job_id": "JOB-1"}

    def slow_then_ok(method, url, **kw):
        calls.append(kw["timeout"])
        if len(calls) == 1:
            raise portal_client.httpx.ReadTimeout("cold start")
        return R()

    monkeypatch.setattr(portal_client.httpx, "request", slow_then_ok)
    assert portal_client.send({"external_id": "a"}, "k1") == {"job_id": "JOB-1"} and len(calls) == 2
    assert calls[0].read >= 20  # a longer read timeout than the old 10 s

    def always_slow(method, url, **kw):
        calls.append(1)
        raise portal_client.httpx.ReadTimeout("cold start")

    calls.clear()
    monkeypatch.setattr(portal_client.httpx, "request", always_slow)
    with pytest.raises(portal_client.PortalError) as e:
        portal_client.send({"external_id": "a"}, "k1")
    assert len(calls) == 2 and "ReadTimeout" in e.value.message and "try again" in e.value.message


def test_portal_client_uses_env_url_and_key_header(monkeypatch):
    seen = []

    class R:
        status_code = 201

        def json(self):
            return {"id": "x1"}

    def fake_request(method, url, json=None, params=None, headers=None, timeout=None):
        seen.append(dict(method=method, url=url, headers=headers, json=json, params=params))
        return R()

    monkeypatch.setenv("PORTAL_API_URL", "https://portal.example.test/")
    monkeypatch.setattr(portal_client.httpx, "request", fake_request)
    assert portal_client.send({"external_id": "a"}, "k1") == {"id": "x1"}
    assert seen[0]["url"] == "https://portal.example.test/api/v1/ingest/staffing-request" and seen[0]["headers"] == {"X-API-Key": "k1"}
    portal_client.candidate_matches("housekeeping", "k1", limit=3)
    assert seen[1]["method"] == "GET" and seen[1]["url"].endswith("/api/v1/ingest/candidate-matches")
    assert seen[1]["params"] == {"skill": "housekeeping", "limit": 3} and seen[1]["headers"] == {"X-API-Key": "k1"}
    assert portal_client.job_url("JOB-000001") == "https://portal.example.test/#/jobs/JOB-000001"
    monkeypatch.delenv("PORTAL_API_URL")
    assert portal_client.base_url() == "https://hoi-portal.vercel.app"
