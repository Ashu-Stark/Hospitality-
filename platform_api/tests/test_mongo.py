"""MongoDB layer: production guard, health/ready, integer ids without ObjectId leaks, atomic stock, photo blobs."""

from conftest import jpeg

from hoi_platform import config, mongo
from hoi_platform.services import inventory as inv

TID = "org_demo"


def _prod(uri: str) -> config.Settings:
    return config.Settings(
        env="production",
        jwt_secret="x" * 40,
        jwt_secret_from_env=True,
        access_ttl_minutes=30,
        refresh_ttl_days=14,
        demo_login=False,
        admin_password="a-strong-admin-pass",
        seed_demo=False,
        cors_origins=["https://app.example.com"],
        mongodb_uri=uri,
    )


def test_production_refuses_mongomock_or_missing_uri(monkeypatch):
    for uri in ("", "mongomock://"):
        assert any("MONGODB_URI" in p for p in config.validate(_prod(uri))), uri
    secret = "mongodb+srv://user:s3cret@cluster.example.net/"
    assert config.validate(_prod(secret)) == []
    assert "s3cret" not in repr(_prod(secret))  # the URI never shows up in reprs
    monkeypatch.setattr(config, "settings", _prod("mongomock://"))
    from hoi_platform.main import create_app

    try:
        create_app()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "MONGODB_URI" in str(e)


def test_health_reports_backend_not_uri(client):
    h = client.get("/health").json()
    assert h["database"] == "mongomock" and h["status"] == "ok"
    assert client.get("/ready").json() == {"status": "ready"}


def test_integer_ids_and_no_object_id_leaks(client, owner, store):
    log = client.get("/workspace/audit", headers=owner).json()
    assert log and all(isinstance(e["id"], int) and "_id" not in e for e in log)
    assert [e["id"] for e in log] == sorted((e["id"] for e in log), reverse=True)
    mv = client.get("/inventory/moves?limit=5", headers=store).json()
    assert mv and all(isinstance(m["id"], int) and "_id" not in m and isinstance(m["at"], str) for m in mv)
    for path in ("/inventory/items", "/inventory/pos", "/inventory/requests", "/inventory/counts", "/inventory/moves"):
        assert not _internal_keys(client.get(path, headers=store).json()), path
    for path in ("/rooms", "/workspace", "/workspace/users", "/workspace/invites", "/workspace/staff", "/dispatch/jobs"):
        assert not _internal_keys(client.get(path, headers=owner).json()), path


def _internal_keys(v) -> set:
    """Keys starting with '_' (e.g. _id, _v, _sku_lc) anywhere in a JSON value."""
    if isinstance(v, dict):
        return {k for k in v if k.startswith("_")} | set().union(*(_internal_keys(x) for x in v.values()))
    if isinstance(v, list):
        return set().union(*(_internal_keys(x) for x in v))
    return set()


def test_failed_decrement_and_failed_fulfilment_leave_no_trace(client, store):
    items = {i["sku"]: i["id"] for i in client.get("/inventory/items", headers=store).json()}
    main = next(lo["id"] for lo in client.get("/inventory/locations", headers=store).json() if lo["name"] == "Maintenance store")
    have = inv.stock(TID)[(items["MNT-BA"], main)]
    n_moves = mongo.col("inv_moves").count_documents({"tenant_id": TID})
    r = client.post("/inventory/issue", json={"item_id": items["MNT-BA"], "location_id": main, "qty": have + 1}, headers=store)
    assert r.status_code == 422 and "Not enough" in r.json()["detail"]
    assert inv.stock(TID)[(items["MNT-BA"], main)] == have
    assert mongo.col("inv_moves").count_documents({"tenant_id": TID}) == n_moves
    # a two-line fulfilment whose second line fails is compensated: stock, ledger and the request are unchanged
    rid = inv.request(TID, "demo.store", "maintenance", {items["MNT-BA"]: 1, items["MNT-GE"]: 10_000})
    before = inv.stock(TID)
    try:
        inv.fulfil(TID, rid, {items["MNT-BA"]: 1, items["MNT-GE"]: 10_000}, main, "demo.store")
        raise AssertionError("expected InventoryError")
    except inv.InventoryError:
        pass
    assert inv.stock(TID) == before
    assert mongo.col("inv_moves").count_documents({"tenant_id": TID}) == n_moves
    req = next(x for x in inv.reqs(TID) if x["id"] == rid)
    assert req["status"] == "pending" and all(ln["qty_issued"] == 0 for ln in req["lines"])
    assert inv.check_invariant(TID) == []


def test_count_posts_once(client, store):
    main = next(lo["id"] for lo in client.get("/inventory/locations", headers=store).json() if lo["name"] == "Main store")
    cid = client.post("/inventory/counts", json={"location_id": main}, headers=store).json()["id"]
    assert client.post(f"/inventory/counts/{cid}/post", json={"counted": {}}, headers=store).status_code == 200
    again = client.post(f"/inventory/counts/{cid}/post", json={"counted": {}}, headers=store)
    assert again.status_code == 422 and again.json()["detail"] == "Count is not open."


def test_photos_live_in_mongodb_with_tamper_check(client, owner):
    client.post("/dispatch/reset", headers=owner)
    client.put("/dispatch/context", json={"working": {"MX": "maintenance"}, "bands": {}}, headers=owner)
    job = client.post("/dispatch/jobs", json={"title": "Fan repair", "room": "101"}, headers=owner).json()
    client.post(f"/dispatch/jobs/{job['id']}/accept", json={"employee_id": "MX"}, headers=owner)
    r = client.post(
        f"/dispatch/jobs/{job['id']}/photos",
        data={"kind": "before", "employee_id": "MX"},
        files={"file": ("b.jpg", jpeg(), "image/jpeg")},
        headers=owner,
    ).json()
    assert r["verified"] is True and "path" not in r
    blob = mongo.col("photo_blobs").find_one({"id": r["id"]})
    assert blob["tenant_id"] == TID and bytes(blob["data"])[:2] == b"\xff\xd8"
    assert client.get(f"/dispatch/photos/{r['id']}", headers=owner).content == bytes(blob["data"])
    mongo.col("photo_blobs").update_one({"id": r["id"]}, {"$set": {"data": b"tampered"}})
    assert client.get(f"/dispatch/jobs/{job['id']}/photos", headers=owner).json()["before"]["verified"] is False


def test_double_accept_race_only_one_wins(client, owner):
    from hoi_platform.services import dispatch
    from hoi_platform.services.errors import Conflict

    client.post("/dispatch/reset", headers=owner)
    client.put("/dispatch/context", json={"working": {"MY": "maintenance"}, "bands": {}}, headers=owner)
    job = client.post("/dispatch/jobs", json={"title": "Tap leak", "room": "102"}, headers=owner).json()
    raw = mongo.col("jobs").find_one({"id": job["id"]})
    assert dispatch._update(TID, job["id"], {"note": "x"}, {"_v": raw["_v"]})  # first writer wins
    assert not dispatch._update(TID, job["id"], {"note": "y"}, {"_v": raw["_v"]})  # stale version loses
    assert dispatch.accept(TID, job["id"], "MY")["status"] == "accepted"
    try:
        dispatch.accept(TID, job["id"], "MY")
        raise AssertionError("expected Conflict")
    except Conflict:
        pass
