"""Live-QA fixes (SYNTHETIC demo hotel): room check and duplicate guard on POST /dispatch/jobs, plain stock-request
titles and the "Give from" suggestion for a stock request."""

from datetime import timedelta

from hoi_platform import mongo
from hoi_platform.services import dispatch
from hoi_platform.services import inventory as inv

WORKING = {"M1": "maintenance", "H1": "housekeeping"}


def _setup(client, owner) -> str:
    client.post("/dispatch/reset", headers=owner)
    r = client.put("/dispatch/context", json={"day": "2029-12-24", "shift": "morning", "working": WORKING, "bands": {}}, headers=owner)
    assert r.status_code == 200
    return client.get("/rooms", headers=owner).json()["rooms"][0]["number"]


def test_job_for_unknown_room_is_refused(client, owner):
    _setup(client, owner)
    numbers = {r["number"] for r in client.get("/rooms", headers=owner).json()["rooms"]}
    assert "999" not in numbers
    n = mongo.col("jobs").count_documents({})
    r = client.post("/dispatch/jobs", json={"title": "AC not cooling", "room": "999"}, headers=owner)
    assert r.status_code == 404 and r.json()["detail"] == "Room 999 not found."
    assert mongo.col("jobs").count_documents({}) == n  # nothing was made
    ok = client.post("/dispatch/jobs", json={"title": "Guard at gate", "department": "security"}, headers=owner)
    assert ok.status_code == 201  # no room: still fine


def test_known_room_is_trimmed_and_accepted(client, owner):
    room = _setup(client, owner)
    r = client.post("/dispatch/jobs", json={"title": "Tap leaking", "room": f" {room} "}, headers=owner)
    assert r.status_code == 201 and r.json()["room"] == room and r.json()["existing"] is False


def test_same_open_job_twice_returns_the_first(client, owner):
    room = _setup(client, owner)
    first = client.post("/dispatch/jobs", json={"title": "Extra towels", "room": room}, headers=owner)
    assert first.status_code == 201
    again = client.post("/dispatch/jobs", json={"title": "  extra TOWELS ", "room": room}, headers=owner)
    assert again.status_code == 200
    body = again.json()
    assert body["existing"] is True and body["duplicate_of"] == first.json()["id"] == body["id"]
    assert mongo.col("jobs").count_documents({"room": room, "title": "Extra towels"}) == 1
    # a different issue for the same room is a new job
    other = client.post("/dispatch/jobs", json={"title": "Fresh linen", "room": room}, headers=owner)
    assert other.status_code == 201 and other.json()["id"] != body["id"]


def test_duplicate_window_and_done_jobs(client, owner):
    room = _setup(client, owner)
    jid = client.post("/dispatch/jobs", json={"title": "Bulb fused", "room": room}, headers=owner).json()["id"]
    # older than the window: a new job
    old = mongo.now() - timedelta(minutes=dispatch.DUPLICATE_MINUTES + 1)
    mongo.col("jobs").update_one({"id": jid}, {"$set": {"created_at": old}})
    r = client.post("/dispatch/jobs", json={"title": "Bulb fused", "room": room}, headers=owner)
    assert r.status_code == 201 and r.json()["id"] != jid
    # a finished job does not block a new one
    mongo.col("jobs").update_one({"id": r.json()["id"]}, {"$set": {"status": "done"}})
    again = client.post("/dispatch/jobs", json={"title": "Bulb fused", "room": room}, headers=owner)
    assert again.status_code == 201 and again.json()["id"] != r.json()["id"]


def test_request_title_is_plain():
    assert inv.request_title([("Bath towel", 2.0)], "housekeeping") == "Bath towel ×2 for Housekeeping"
    t = inv.request_title([("Soap", 4.0), ("Shampoo", 1.5)], "fnb_service", "204")
    assert t == "Soap ×4, Shampoo ×1.5 for F&B service · room 204"
    many = inv.request_title([(f"Item {i}", 1.0) for i in range(5)], "maintenance")
    assert many == "Item 0 ×1, Item 1 ×1, Item 2 ×1, +2 more for Maintenance"


def test_choose_source_prefers_a_place_with_enough():
    locs = [
        {"id": "pantry", "name": "Housekeeping pantry (floor 2)", "kind": "pantry"},
        {"id": "kitchen", "name": "Kitchen store", "kind": "store"},
        {"id": "main", "name": "Main store", "kind": "store"},
    ]
    stock = {("towel", "pantry"): 0.0, ("towel", "main"): 50.0, ("soap", "pantry"): 10.0, ("soap", "main"): 2.0}
    assert inv.choose_source({"towel": 2}, stock, locs) == "main"  # the pantry (first by name) has none
    assert inv.choose_source({"soap": 5}, stock, locs) == "pantry"  # only the pantry has enough
    assert inv.choose_source({"towel": 2, "soap": 5}, stock, locs) == "main"  # nobody has both: the main store
    assert inv.choose_source({"soap": 1}, stock, locs) == "main"  # both have enough: the main store first
    assert inv.choose_source({}, stock, locs) == "main"
    assert inv.main_store([{"id": "a", "name": "Pantry", "kind": "pantry"}, {"id": "b", "name": "Store B", "kind": "store"}]) == "b"


def test_requests_api_carries_title_and_give_from(client, store):
    items = {i["sku"]: i for i in client.get("/inventory/items", headers=store).json()}
    locs = client.get("/inventory/locations", headers=store).json()
    stock = {(r["item_id"], r["location_id"]): r["qty"] for r in client.get("/inventory/stock", headers=store).json()["stock"]}
    item = next(i for i in items.values() if any(stock.get((i["id"], lo["id"]), 0) >= 2 for lo in locs))
    body = {"department": "housekeeping", "lines": {item["id"]: 2}, "room": "204"}
    rid = client.post("/inventory/requests", json=body, headers=store).json()["id"]
    req = next(r for r in client.get("/inventory/requests", headers=store).json() if r["id"] == rid)
    assert req["title"] == f"{item['name']} ×2 for Housekeeping · room 204"
    assert rid not in req["title"] and "demo." not in req["title"]
    assert stock.get((item["id"], req["give_from"]), 0) >= 2  # "Give all" from there works
    r = client.post(f"/inventory/requests/{rid}/fulfil", json={"issued": {item["id"]: 2}, "from_location": req["give_from"]}, headers=store)
    assert r.status_code == 200 and r.json()["status"] == "issued"
