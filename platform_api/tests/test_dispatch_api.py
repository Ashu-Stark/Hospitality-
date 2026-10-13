from conftest import jpeg

WORKING = {"M1": "maintenance", "M2": "maintenance", "M3": "maintenance", "H1": "housekeeping"}
BANDS = {"M1": "low", "M2": "high", "M3": "low"}


def _setup(client, owner):
    client.post("/dispatch/reset", headers=owner)
    r = client.put("/dispatch/context", json={"day": "2029-12-24", "shift": "morning", "working": WORKING, "bands": BANDS}, headers=owner)
    assert r.status_code == 200


def test_offer_decline_timeout_accept_photos_complete(client, owner):
    _setup(client, owner)
    job = client.post("/dispatch/jobs", json={"title": "AC not cooling", "room": "204", "urgency": "high"}, headers=owner).json()
    assert job["department"] == "maintenance" and job["status"] == "offered"
    assert job["offer_to"] in ("M1", "M3")  # M2 is high-risk: the retention guard ranks them last
    assert job["ranking"][-1]["employee_id"] == "M2" and job["ranking"][-1]["parts"]["retention_guard"] == -15
    first = job["offer_to"]

    # a worker cannot act for someone else, and a non-offered worker cannot accept
    assert client.post(f"/dispatch/jobs/{job['id']}/accept", json={"employee_id": "H1"}, headers=owner).status_code == 409

    job = client.post(f"/dispatch/jobs/{job['id']}/decline", json={"employee_id": first}, headers=owner).json()
    second = job["offer_to"]
    assert second != first

    # server-side expiry: force the window into the past, then any read moves the offer on
    from datetime import UTC, datetime

    from hoi_platform import mongo

    mongo.col("jobs").update_one({"id": job["id"]}, {"$set": {"offer_expires_at": datetime(2000, 1, 1, tzinfo=UTC)}})
    job = next(j for j in client.get("/dispatch/jobs", headers=owner).json() if j["id"] == job["id"])
    assert [a["outcome"] for a in job["attempts"]][:2] == ["declined", "timeout"]
    third = job["offer_to"]
    assert third not in (first, second)

    # photos are required in order, only by the assignee
    assert client.post(f"/dispatch/jobs/{job['id']}/accept", json={"employee_id": third}, headers=owner).json()["status"] == "accepted"
    assert client.post(f"/dispatch/jobs/{job['id']}/start", json={"employee_id": third}, headers=owner).status_code == 422
    files = {"file": ("b.jpg", jpeg(), "image/jpeg")}
    r = client.post(f"/dispatch/jobs/{job['id']}/photos", data={"kind": "after", "employee_id": third}, files=files, headers=owner)
    assert r.status_code == 409  # after-photo before starting
    r = client.post(f"/dispatch/jobs/{job['id']}/photos", data={"kind": "before", "employee_id": third}, files=files, headers=owner)
    assert r.status_code == 201 and r.json()["verified"] and len(r.json()["sha256"]) == 64
    assert client.post(f"/dispatch/jobs/{job['id']}/start", json={"employee_id": third}, headers=owner).json()["status"] == "in_progress"
    r = client.post(
        f"/dispatch/jobs/{job['id']}/photos",
        data={"kind": "after", "employee_id": third},
        files={"file": ("a.jpg", jpeg((60, 200, 60)), "image/jpeg")},
        headers=owner,
    )
    assert r.status_code == 201
    assert client.post(f"/dispatch/jobs/{job['id']}/complete", json={"employee_id": third}, headers=owner).json()["status"] == "done"
    ph = client.get(f"/dispatch/jobs/{job['id']}/photos", headers=owner).json()
    assert set(ph) == {"before", "after"} and ph["before"]["server_ts"] <= ph["after"]["server_ts"]
    img = client.get(f"/dispatch/photos/{ph['after']['id']}", headers=owner)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"


def test_not_an_image_is_rejected(client, owner):
    _setup(client, owner)
    job = client.post("/dispatch/jobs", json={"title": "Bulb fused", "room": "101"}, headers=owner).json()
    who = job["offer_to"]
    client.post(f"/dispatch/jobs/{job['id']}/accept", json={"employee_id": who}, headers=owner)
    r = client.post(
        f"/dispatch/jobs/{job['id']}/photos",
        data={"kind": "before", "employee_id": who},
        files={"file": ("x.jpg", b"not an image", "image/jpeg")},
        headers=owner,
    )
    assert r.status_code == 422


def test_unassigned_and_manual_offer(client, owner):
    _setup(client, owner)
    job = client.post("/dispatch/jobs", json={"title": "Guard at gate", "department": "security", "urgency": "high"}, headers=owner).json()
    assert job["status"] == "unassigned"
    assert client.post(f"/dispatch/jobs/{job['id']}/offer", json={"employee_id": "M1"}, headers=owner).status_code == 422  # wrong dept


def test_worker_sees_only_own_jobs_without_bands(client, owner, worker):
    client.put(
        "/dispatch/context", json={"working": {"HS05": "housekeeping", "H9": "housekeeping"}, "bands": {"H9": "high"}}, headers=owner
    )
    client.post("/dispatch/jobs", json={"title": "Extra towels", "room": "305"}, headers=owner)
    ctx = client.get("/dispatch/context", headers=worker).json()
    assert ctx["bands"] == {}
    mine = client.get("/dispatch/jobs", headers=worker).json()
    assert all(j.get("assigned_to") == "HS05" or j.get("offer_to") == "HS05" for j in mine)
    assert all(j["ranking"] == [] for j in mine)
    other = client.post("/dispatch/jobs/does-not-matter/accept", json={"employee_id": "H9"}, headers=worker)
    assert other.status_code == 403
