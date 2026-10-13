def _ids(client, h):
    items = {i["sku"]: i["id"] for i in client.get("/inventory/items", headers=h).json()}
    locs = {l["name"]: l["id"] for l in client.get("/inventory/locations", headers=h).json()}
    sups = client.get("/inventory/suppliers", headers=h).json()
    return items, locs, sups


def test_full_flow_keeps_ledger_consistent(client, store, worker):
    items, locs, sups = _ids(client, store)
    main = locs["Main store"]

    # employee requests supplies; storekeeper issues part, then the rest
    rid = client.post(
        "/inventory/requests", json={"department": "housekeeping", "lines": {items["AMN-SH"]: 20, items["AMN-SP"]: 10}}, headers=worker
    ).json()["id"]
    mine = client.get("/inventory/requests", headers=worker).json()
    assert any(r["id"] == rid for r in mine) and all(r["requested_by"] == "HS05" for r in mine)
    assert (
        client.post(
            f"/inventory/requests/{rid}/fulfil", json={"issued": {items["AMN-SH"]: 5}, "from_location": main}, headers=store
        ).json()["status"]
        == "partial"
    )
    assert (
        client.post(
            f"/inventory/requests/{rid}/fulfil",
            json={"issued": {items["AMN-SH"]: 99, items["AMN-SP"]: 10}, "from_location": main},
            headers=store,
        ).json()["status"]
        == "issued"
    )

    # purchasing lifecycle with a partial GRN
    po = client.post("/inventory/pos", json={"supplier_id": sups[0]["id"], "lines": {items["LIN-BT"]: 40}}, headers=store).json()["id"]
    assert (
        client.post(f"/inventory/pos/{po}/receive", json={"received": {items["LIN-BT"]: 1}, "location_id": main}, headers=store).status_code
        == 422
    )  # draft cannot be received
    client.post(f"/inventory/pos/{po}/status", json={"status": "approved"}, headers=store)
    client.post(f"/inventory/pos/{po}/status", json={"status": "sent"}, headers=store)
    assert (
        client.post(f"/inventory/pos/{po}/receive", json={"received": {items["LIN-BT"]: 15}, "location_id": main}, headers=store).json()[
            "status"
        ]
        == "partial"
    )
    assert (
        client.post(f"/inventory/pos/{po}/receive", json={"received": {items["LIN-BT"]: 25}, "location_id": main}, headers=store).json()[
            "status"
        ]
        == "received"
    )

    # negative stock is refused; wastage needs a reason; transfer needs two locations
    assert (
        client.post("/inventory/issue", json={"item_id": items["MNT-GE"], "location_id": main, "qty": 9999}, headers=store).status_code
        == 422
    )
    assert (
        client.post("/inventory/waste", json={"item_id": items["AMN-WB"], "location_id": main, "qty": 1}, headers=store).status_code == 422
    )
    assert (
        client.post(
            "/inventory/transfer", json={"item_id": items["AMN-WB"], "from_location": main, "to_location": main, "qty": 1}, headers=store
        ).status_code
        == 422
    )

    # stock count posts variance as adjustments
    cid = client.post("/inventory/counts", json={"location_id": main}, headers=store).json()["id"]
    v = client.post(f"/inventory/counts/{cid}/post", json={"counted": {items["LIN-HT"]: 10}}, headers=store).json()["variance_value"]
    assert isinstance(v, float)

    a = client.get("/inventory/analytics", headers=store).json()
    assert a["ledger_errors"] == [] and a["stock_value"] > 0


def test_forecast_aware_suggestions_catch_busy_weeks(client, store):
    s = client.get("/inventory/suggestions?rooms=45&occ=0.95,0.95,0.95,0.95,0.95,0.95,0.95", headers=store).json()
    shampoo = next(x for x in s if x["sku"] == "AMN-SH")
    assert shampoo["forecast_usage"] > 0
    assert any(x["forecast_qty"] > x["static_qty"] for x in s)


def test_catalog_validation(client, store):
    _, _, sups = _ids(client, store)
    r = client.post(
        "/inventory/items",
        json={"sku": "AMN-SH", "name": "dup", "category": "Linen", "unit_cost": 1, "par": 1, "reorder_point": 0},
        headers=store,
    )
    assert r.status_code == 422  # duplicate SKU
    r = client.post(
        "/inventory/items",
        json={
            "sku": "NEW-1",
            "name": "Comb",
            "category": "Guest amenities",
            "unit_cost": 4,
            "par": 10,
            "reorder_point": 20,
            "supplier_id": sups[0]["id"],
        },
        headers=store,
    )
    assert r.status_code == 422  # reorder point above par
    r = client.post(
        "/inventory/items",
        json={
            "sku": "NEW-1",
            "name": "Comb",
            "category": "Guest amenities",
            "unit_cost": 4,
            "par": 100,
            "reorder_point": 20,
            "supplier_id": sups[0]["id"],
        },
        headers=store,
    )
    assert r.status_code == 201
