"""Retry safety (hoi_platform/idempotency.py): a guest's double tap, or a retry after a lost response, must not create a
second job or turn a successful staff action into an error. The client sends one Idempotency-Key per attempt; the
server replays the first response for the same key. Without a key the old behaviour is unchanged (backward compatible).
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from test_concierge import room
from test_inventory_api import _ids

from hoi_platform import mongo, ratelimit


@pytest.fixture(autouse=True)
def _fresh_limits():
    ratelimit.reset()  # the guest endpoint allows 10 requests a minute per IP; every test client shares one IP
    yield
    ratelimit.reset()


def _guest_jobs(room_id: str) -> int:
    return mongo.col("jobs").count_documents({"room_id": room_id, "kind": "guest"})


def test_without_a_key_a_retried_guest_request_creates_a_second_job(client, owner):
    """The bug this fixes: the request reaches the server, the answer is lost, the guest taps again -> two jobs."""
    r = room(client, owner)
    before = _guest_jobs(r["id"])
    for _ in range(2):
        assert client.post(f"/public/guest/{r['guest_token']}/requests", json={"key": "towels"}).status_code == 201
    assert _guest_jobs(r["id"]) - before == 2


def test_same_key_replays_the_first_response_and_creates_one_job(client, owner):
    r = room(client, owner)
    before = _guest_jobs(r["id"])
    h = {"Idempotency-Key": "guest-towels-attempt-1"}
    first = client.post(f"/public/guest/{r['guest_token']}/requests", json={"key": "towels"}, headers=h)
    again = client.post(f"/public/guest/{r['guest_token']}/requests", json={"key": "towels"}, headers=h)
    assert first.status_code == again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true" and "Idempotent-Replayed" not in first.headers
    assert again.json()["requests"] == first.json()["requests"]
    assert _guest_jobs(r["id"]) - before == 1


def test_parallel_double_tap_with_one_key_creates_one_job(client, owner):
    r = room(client, owner)
    before = _guest_jobs(r["id"])
    h = {"Idempotency-Key": "guest-double-tap"}
    url = f"/public/guest/{r['guest_token']}/requests"
    with ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(lambda _: client.post(url, json={"key": "water"}, headers=h).status_code, range(6)))
    assert _guest_jobs(r["id"]) - before == 1
    # one did the work; the rest either replayed it (201) or were told it is still being processed (409, safe to retry)
    assert codes.count(201) >= 1 and set(codes) <= {201, 409}


def test_same_key_with_a_different_body_is_rejected(client, owner):
    r = room(client, owner)
    h = {"Idempotency-Key": "guest-reused-key"}
    url = f"/public/guest/{r['guest_token']}/requests"
    assert client.post(url, json={"key": "towels"}, headers=h).status_code == 201
    bad = client.post(url, json={"key": "water"}, headers=h)
    assert bad.status_code == 422 and "different request" in bad.json()["detail"]


def test_keys_are_scoped_per_room(client, owner):
    """Two rooms that happen to send the same key are two different requests."""
    a, b = room(client, owner), room(client, owner)
    h = {"Idempotency-Key": "same-key-two-rooms"}
    before = _guest_jobs(a["id"]) + _guest_jobs(b["id"])
    for x in (a, b):
        assert client.post(f"/public/guest/{x['guest_token']}/requests", json={"key": "towels"}, headers=h).status_code == 201
    assert _guest_jobs(a["id"]) + _guest_jobs(b["id"]) - before == 2


def test_a_failed_request_is_not_stored_so_a_fixed_retry_works(client, owner):
    r = room(client, owner)
    h = {"Idempotency-Key": "guest-bad-then-good"}
    url = f"/public/guest/{r['guest_token']}/requests"
    assert client.post(url, json={"key": "no-such-request"}, headers=h).status_code == 422
    assert mongo.col("idempotency_keys").count_documents({"key": {"$regex": "guest-bad-then-good$"}}) == 0
    assert client.post(url, json={"key": "no-such-request"}, headers=h).status_code == 422  # not replayed: re-checked


def test_key_records_expire_after_a_day(client):
    ix = mongo.col("idempotency_keys").index_information()
    assert any(v.get("expireAfterSeconds") == 86400 for v in ix.values())


def test_retried_staff_action_is_replayed_not_turned_into_an_error(client, owner):
    """Accept succeeds, the answer is lost, the phone retries: before, the worker saw 'no longer available' (409)."""
    client.post("/dispatch/reset", headers=owner)
    client.put("/dispatch/context", json={"working": {"H1": "housekeeping"}, "bands": {}}, headers=owner)
    job = client.post("/dispatch/jobs", json={"title": "Fresh towels", "room": "101", "department": "housekeeping"}, headers=owner).json()
    who = job["offer_to"]
    url = f"/dispatch/jobs/{job['id']}/accept"
    h = {**owner, "Idempotency-Key": f"accept-{job['id']}"}
    first = client.post(url, json={"employee_id": who}, headers=h)
    again = client.post(url, json={"employee_id": who}, headers=h)
    assert first.status_code == again.status_code == 200 and again.json()["status"] == "accepted"
    assert client.post(url, json={"employee_id": who}, headers=owner).status_code == 409  # without a key: unchanged
    accepted = [a for a in mongo.col("audit_log").find({"action": "job.accepted", "detail": job["id"]})]
    assert len(accepted) == 1


def test_retried_supply_request_is_stored_once(client, store, worker):
    items, _, _ = _ids(client, store)
    body = {"department": "housekeeping", "lines": {items["AMN-SH"]: 3}, "note": "idempotency test"}
    h = {**worker, "Idempotency-Key": "supply-request-1"}
    ids = {client.post("/inventory/requests", json=body, headers=h).json()["id"] for _ in range(3)}
    assert len(ids) == 1
    assert mongo.col("inv_reqs").count_documents({"note": "idempotency test"}) == 1


def test_confirmed_chat_action_is_retry_safe(client, owner):
    """The concierge's Confirm tap also creates jobs; a retried confirm with the same key creates one."""
    r = room(client, owner)
    before = _guest_jobs(r["id"])
    url, h = f"/public/guest/{r['guest_token']}/actions", {"Idempotency-Key": "guest-confirm-1"}
    body = {"action": "request", "params": {"type": "towels"}}
    first, again = (client.post(url, json=body, headers=h) for _ in range(2))
    assert first.status_code == again.status_code == 200 and again.headers.get("Idempotent-Replayed") == "true"
    assert _guest_jobs(r["id"]) - before == 1
