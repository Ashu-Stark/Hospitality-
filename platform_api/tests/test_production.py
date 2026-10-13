from conftest import auth, jpeg

from hoi_platform import config, mongo, ratelimit


# ------------------------------------------------------------------ sessions
def test_refresh_rotation_and_reuse_detection(client):
    s = client.post("/auth/demo/demo.owner").json()
    r1 = client.post("/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert r1.status_code == 200 and r1.json()["refresh_token"] != s["refresh_token"]
    # the old token is now dead; presenting it again revokes the whole family (likely theft)
    assert client.post("/auth/refresh", json={"refresh_token": s["refresh_token"]}).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}).status_code == 401


def test_logout_revokes(client):
    s = client.post("/auth/demo/demo.hr").json()
    assert client.post("/auth/logout", json={"refresh_token": s["refresh_token"]}).status_code == 204
    assert client.post("/auth/refresh", json={"refresh_token": s["refresh_token"]}).status_code == 401


def test_login_rate_limit():
    ratelimit.reset()
    for _ in range(3):
        ratelimit.hit("unit-test", 3)
    try:
        ratelimit.hit("unit-test", 3)
        raise AssertionError("expected 429")
    except Exception as e:  # noqa: BLE001
        assert getattr(e, "status_code", None) == 429
    ratelimit.reset()


def test_production_config_refuses_unsafe_settings():
    bad = config.Settings(
        env="production",
        jwt_secret="short",
        jwt_secret_from_env=False,
        access_ttl_minutes=30,
        refresh_ttl_days=14,
        demo_login=True,
        admin_password="x",
        seed_demo=False,
        cors_origins=["*"],
    )
    problems = config.validate(bad)
    assert len(problems) == 5  # incl. no MONGODB_URI
    good = config.Settings(
        env="production",
        jwt_secret="x" * 40,
        jwt_secret_from_env=True,
        access_ttl_minutes=30,
        refresh_ttl_days=14,
        demo_login=False,
        admin_password="a-strong-admin-pass",
        seed_demo=False,
        cors_origins=["https://app.example.com"],
        mongodb_uri="mongodb+srv://user:pw@cluster.example.net/",
    )
    assert config.validate(good) == []


def test_security_headers_and_request_id(client):
    r = client.get("/worker/")
    assert r.status_code == 200 and "HOI Staff" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-request-id"]
    assert client.get("/guest/").status_code == 200
    assert client.get("/ready").json()["status"] == "ready"


# ------------------------------------------------------------------ rooms, guest requests
def _ctx(client, h):
    client.put(
        "/dispatch/context",
        json={"working": {"HK1": "housekeeping", "HK2": "housekeeping", "MT1": "maintenance", "FB1": "fnb_service"}, "bands": {}},
        headers=h,
    )


def test_room_turnaround_flow(client, owner):
    client.post("/dispatch/reset", headers=owner)
    _ctx(client, owner)
    data = client.get("/rooms", headers=owner).json()
    assert data["summary"]["total"] == 45
    room = next(r for r in data["rooms"] if r["status"] == "occupied")
    r = client.post(f"/rooms/{room['id']}/checkout", headers=owner).json()
    assert r["status"] == "dirty" and r["current_job_id"]
    jid, who = r["current_job_id"], None
    job = next(j for j in client.get("/dispatch/jobs", headers=owner).json() if j["id"] == jid)
    who = job["offer_to"]
    assert job["department"] == "housekeeping" and job["room"] == room["number"]
    client.post(f"/dispatch/jobs/{jid}/accept", json={"employee_id": who}, headers=owner)
    files = {"file": ("b.jpg", jpeg(), "image/jpeg")}
    client.post(f"/dispatch/jobs/{jid}/photos", data={"kind": "before", "employee_id": who}, files=files, headers=owner)
    client.post(f"/dispatch/jobs/{jid}/start", json={"employee_id": who}, headers=owner)
    assert _room(client, owner, room["id"])["status"] == "cleaning"
    client.post(f"/dispatch/jobs/{jid}/photos", data={"kind": "after", "employee_id": who}, files=files, headers=owner)
    client.post(f"/dispatch/jobs/{jid}/complete", json={"employee_id": who}, headers=owner)
    assert _room(client, owner, room["id"])["status"] == "inspection"
    # failed inspection creates a re-clean job; pass makes it ready
    r = client.post(f"/rooms/{room['id']}/inspect", json={"passed": False, "note": "bathroom"}, headers=owner).json()
    assert r["status"] == "dirty" and r["current_job_id"] != jid
    mongo.col("rooms").update_one({"id": room["id"]}, {"$set": {"status": "inspection"}})
    assert client.post(f"/rooms/{room['id']}/inspect", json={"passed": True}, headers=owner).json()["status"] == "ready"
    assert client.post(f"/rooms/{room['id']}/check-in", headers=owner).json()["status"] == "occupied"


def _room(client, h, rid):
    return next(r for r in client.get("/rooms", headers=h).json()["rooms"] if r["id"] == rid)


def test_out_of_order_creates_maintenance_job(client, owner):
    _ctx(client, owner)
    room = next(r for r in client.get("/rooms", headers=owner).json()["rooms"] if r["status"] == "ready")
    r = client.post(f"/rooms/{room['id']}/out-of-order", json={"reason": "Leaking pipe"}, headers=owner).json()
    assert r["status"] == "out_of_order"
    job = next(j for j in client.get("/dispatch/jobs", headers=owner).json() if j["id"] == r["current_job_id"])
    assert job["department"] == "maintenance" and job["urgency"] == "high"


def test_guest_request_portal(client, owner):
    _ctx(client, owner)
    room = client.get("/rooms", headers=owner).json()["rooms"][0]
    tok = room["guest_token"]
    v = client.get(f"/public/guest/{tok}").json()
    assert v["room"] == room["number"] and any(m["key"] == "ac" for m in v["menu"])
    assert "guest_token" not in str(v)
    v = client.post(f"/public/guest/{tok}/requests", json={"key": "ac", "note": "making noise"}).json()
    assert v["requests"][0]["status"] == "received"
    jobs = client.get("/dispatch/jobs", headers=owner).json()
    j = next(j for j in jobs if j["source"] == "guest" and j["room"] == room["number"])
    assert j["department"] == "maintenance" and j["urgency"] == "high"
    for _ in range(4):
        client.post(f"/public/guest/{tok}/requests", json={"key": "towels"})
    assert client.post(f"/public/guest/{tok}/requests", json={"key": "towels"}).status_code == 409  # per-room limit
    assert client.get("/public/guest/not-a-real-token").status_code == 404


def test_qr_and_token_visibility(client, owner, store):
    rid = client.get("/rooms", headers=owner).json()["rooms"][0]["id"]
    qr = client.get(f"/rooms/{rid}/qr.svg", headers=owner)
    assert qr.status_code == 200 and "<svg" in qr.text
    assert all("guest_token" not in r for r in client.get("/rooms", headers=store).json()["rooms"])


# ------------------------------------------------------------------ GST, roster, worker self-service
def test_po_gst_split(client, store):
    pos = client.get("/inventory/pos", headers=store).json()
    po = pos[0]
    t = po["totals"]
    assert t["total"] == round(t["taxable"] + t["cgst"] + t["sgst"] + t["igst"], 2)
    assert (t["igst"] == 0) != t["interstate"] or t["taxable"] == 0
    doc = client.get(f"/inventory/pos/{po['id']}/document", headers=store)
    assert doc.status_code == 200 and "HSN" in doc.text and "not a tax invoice" in doc.text
    bad = client.post("/inventory/suppliers", json={"name": "X", "gstin": "BAD"}, headers=store)
    assert bad.status_code == 422
    ok = client.post(
        "/inventory/suppliers", json={"name": "Hill Linen Co (test)", "gstin": "05ABCDE1234F1Z5", "interstate": False}, headers=store
    )
    assert ok.status_code == 201


def test_worker_sees_own_published_shifts(client, owner, worker):
    client.put(
        "/dispatch/roster",
        json={
            "week_start": "2029-12-24",
            "assignments": [
                {"employee_id": "E134", "date": "2029-12-24", "shift": "morning", "hours": 9},
                {"employee_id": "E999", "date": "2029-12-24", "shift": "evening", "hours": 9},
            ],
        },
        headers=owner,
    )
    me = client.get("/me/shifts", headers=worker).json()
    assert [s["employee_id"] for s in me["shifts"]] == ["E134"]
    assert client.put("/dispatch/roster", json={"assignments": []}, headers=worker).status_code == 403
    assert auth(client, "E134")
