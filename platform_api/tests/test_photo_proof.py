"""Photo proof per job kind (S2): photos only where they prove something, a per-hotel setting. Offline, SYNTHETIC data."""

import pytest
from conftest import auth, jpeg

from hoi_platform import mongo, ratelimit
from hoi_platform.services import photo_proof

URL = "/hotel/settings/photo-proof"


@pytest.fixture(autouse=True)
def _fresh(client, owner):
    ratelimit.reset()
    client.post("/dispatch/reset", headers=owner)
    client.put("/dispatch/context", json={"working": {"HS05": "housekeeping"}, "bands": {}}, headers=owner)
    defaults = [{"kind": k, "before": b, "after": a} for k, (_, b, a) in photo_proof.DEFAULTS.items()]
    yield
    client.put(URL, json={"kinds": defaults}, headers=owner)


def _room(client, owner, status):
    hotel = client.get("/workspace/properties", headers=owner).json()[0]["id"]  # the hotel HS05 works at (not the homestay)
    rooms = client.get(f"/rooms?property_id={hotel}", headers=owner).json()["rooms"]
    return next(r for r in rooms if r["status"] == status)


def _towels(client, owner):
    r = _room(client, owner, "occupied")
    assert client.post(f"/public/guest/{r['guest_token']}/requests", json={"key": "towels"}).status_code == 201
    return next(j for j in client.get("/dispatch/jobs", headers=owner).json() if j["room"] == r["number"] and j["kind"] == "guest")


def _cleaning(client, owner):
    r = _room(client, owner, "occupied")
    room = client.post(f"/rooms/{r['id']}/checkout", headers=owner).json()
    return next(j for j in client.get("/dispatch/jobs", headers=owner).json() if j["id"] == room["current_job_id"])


def _act(client, worker, jid, what):
    return client.post(f"/dispatch/jobs/{jid}/{what}", json={}, headers=worker)


def test_delivery_needs_no_photo(client, owner, worker):
    job = _towels(client, owner)
    assert job["request"] == "towels" and job["offer_to"] == "HS05"
    assert job["photos_required"] == {"kind": "delivery", "before": False, "after": False}
    assert _act(client, worker, job["id"], "accept").status_code == 200
    assert _act(client, worker, job["id"], "start").json()["status"] == "in_progress"
    assert _act(client, worker, job["id"], "complete").json()["status"] == "done"
    assert mongo.col("photos").count_documents({"job_id": job["id"]}) == 0


def test_cleaning_needs_before_and_after(client, owner, worker):
    job = _cleaning(client, owner)
    assert job["photos_required"] == {"kind": "cleaning", "before": True, "after": True}
    _act(client, worker, job["id"], "accept")
    r = _act(client, worker, job["id"], "start")
    assert r.status_code == 422 and "before photo" in r.json()["detail"]
    files = {"file": ("b.jpg", jpeg(), "image/jpeg")}
    assert client.post(f"/dispatch/jobs/{job['id']}/photos", data={"kind": "before"}, files=files, headers=worker).status_code == 201
    assert _act(client, worker, job["id"], "start").status_code == 200
    assert _act(client, worker, job["id"], "complete").status_code == 422


def test_setting_changes_the_rule(client, owner, worker):
    body = {"kinds": [{"kind": "delivery", "before": False, "after": True}, {"kind": "cleaning", "before": False, "after": False}]}
    r = client.put(URL, json=body, headers=owner)
    assert r.status_code == 200
    got = {k["kind"]: k for k in r.json()["kinds"]}
    assert got["delivery"]["after"] is True and got["cleaning"]["before"] is False
    assert got["repair"] == {**got["repair"], "before": False, "after": True}  # kinds left out keep their rule

    job = _towels(client, owner)
    _act(client, worker, job["id"], "accept")
    _act(client, worker, job["id"], "start")
    assert _act(client, worker, job["id"], "complete").status_code == 422  # now the delivery needs an after photo

    clean = _cleaning(client, owner)
    _act(client, worker, clean["id"], "accept")
    assert _act(client, worker, clean["id"], "start").json()["status"] == "in_progress"  # no before photo needed any more


def test_get_shape_and_roles(client, owner, worker):
    head = auth(client, "demo.housekeeping")
    r = client.get(URL, headers=head)
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"kinds", "defaults"} and [k["kind"] for k in data["kinds"]] == list(photo_proof.DEFAULTS)
    assert all(set(k) == {"kind", "label", "before", "after"} for k in data["kinds"] + data["defaults"])
    d = {k["kind"]: k for k in data["defaults"]}
    assert d["cleaning"]["before"] and d["cleaning"]["after"]
    assert d["repair"]["after"] and not d["repair"]["before"]
    assert d["lost_found"]["after"] and d["damage"]["after"]
    assert not any(d[k]["before"] or d[k]["after"] for k in ("delivery", "guest_help", "alert", "checkout", "general"))

    body = {"kinds": [{"kind": "delivery", "before": False, "after": True}]}
    assert client.get(URL, headers=worker).status_code == 403
    assert client.put(URL, json=body, headers=head).status_code == 403  # owner only
    assert client.put(URL, json=body, headers=worker).status_code == 403
    assert client.put(URL, json={"kinds": [{"kind": "wake_up_call", "before": True, "after": True}]}, headers=owner).status_code == 422
    assert client.get(URL, headers=owner).json()["kinds"] == data["kinds"]  # nothing saved by the refused calls


def test_voice_start_and_done_without_photos(client, owner, worker):
    job = _towels(client, owner)
    _act(client, worker, job["id"], "accept")
    st = client.post("/me/voice/command", json={"text": "start", "lang": "en"}, headers=worker).json()
    assert st["proposed_action"]["action"] == "start"
    assert client.post("/me/voice/act", json={"action": "start", "params": {"job_id": job["id"]}}, headers=worker).status_code == 200
    done = client.post("/me/voice/command", json={"text": "ho gaya", "lang": "hi"}, headers=worker).json()
    assert done["proposed_action"] == {**done["proposed_action"], "action": "complete", "params": {"job_id": job["id"]}}
    r = client.post("/me/voice/act", json={"action": "complete", "params": {"job_id": job["id"]}}, headers=worker)
    assert r.status_code == 200 and r.json()["job"]["status"] == "done"


@pytest.mark.parametrize(
    ("job", "kind"),
    [
        ({"kind": "cleaning"}, "cleaning"),
        ({"kind": "maintenance"}, "repair"),
        ({"kind": "guest_checkout"}, "checkout"),
        ({"kind": "guest", "request": "food"}, "delivery"),
        ({"kind": "guest", "request": "lost_item"}, "lost_found"),
        ({"kind": "guest", "request": "safety_alert"}, "alert"),
        ({"kind": "guest"}, "guest_help"),
        ({"kind": "general", "source": "voice", "request": "pest_control"}, "pest_control"),
        ({"kind": "general", "source": "voice"}, "damage"),
        ({"kind": "general", "department": "maintenance"}, "repair"),
        ({"kind": "general", "department": "housekeeping"}, "general"),
    ],
)
def test_proof_kind_mapping(job, kind):
    assert photo_proof.proof_kind(job) == kind


def test_every_guest_menu_key_is_mapped():
    from hoi_platform.services import rooms

    assert set(rooms.GUEST_MENU) <= set(photo_proof.REQUEST_KIND)
