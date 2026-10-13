"""The demo workspace is the FICTIONAL Himsagar Ridge Resort, Mussoorie (SYNTHETIC): rooms, staff, accounts, profile,
inventory, and the rebuild of a demo tenant seeded by an older version."""

import json
from pathlib import Path

from conftest import auth

from hoi_platform import mongo, seed
from hoi_platform.schemas import HotelProfileIn
from hoi_platform.services import inventory, profiles, tenants

ROOMS = [f"{f}{i:02d}" for f in (1, 2, 3) for i in range(1, 9)]
STAFF_IDS = [f"HS{n:02d}" for n in range(1, 21)]
HOTEL_JSON = Path(__file__).resolve().parents[2] / "ml" / "data" / "hotels" / "himsagar" / "hotel.json"
PERSONAL = ("name", "gender", "age", "religion", "caste", "health", "family", "phone", "email", "dob")


def test_property_rooms_and_staff(client, owner):
    ws = client.get("/workspace", headers=owner).json()
    assert "fictional" in ws["name"].lower() and "Riverside" not in json.dumps(ws)
    props = client.get("/workspace/properties", headers=owner).json()
    assert [(p["name"], p["rooms"], p["floors"]) for p in props] == [("Himsagar Ridge Resort, Mussoorie (fictional)", 24, 3)]
    rooms = client.get("/rooms", headers=owner).json()
    assert sorted(r["number"] for r in rooms["rooms"]) == ROOMS and rooms["summary"]["total"] == 24
    # other test files import extra test staff into the demo tenant: check the seeded HS ids
    staff = [s for s in client.get("/workspace/staff", headers=owner).json() if s["employee_id"] in STAFF_IDS]
    assert [s["employee_id"] for s in staff] == STAFF_IDS
    for s in staff:
        assert s["role_title"] and s["avatar"] == seed.slug(s["role_title"])
        assert not [k for k in s if k.lower() in PERSONAL or k.lower().endswith("_name")]
    counts = {}
    for s in staff:
        counts[s["department"]] = counts.get(s["department"], 0) + 1
    assert counts == {
        "management": 1,
        "front_office": 3,
        "housekeeping": 6,
        "fnb_service": 3,
        "kitchen": 3,
        "maintenance": 2,
        "security": 2,
    }
    assert {s["contract_type"] for s in staff} == {"permanent", "seasonal"}
    fo = [s for s in staff if s["department"] == "front_office"]
    assert all("fo_system" in s["skills"] for s in fo)  # the roster rule: a holder on every front-office shift


def test_staff_match_the_ml_hotel_dataset():
    if not HOTEL_JSON.exists():  # the platform deploys on its own; the check runs in the monorepo
        return
    record = json.loads(HOTEL_JSON.read_text(encoding="utf-8"))
    ml = [(s["employee_id"], s["department"], s["role_title"], s["contract_type"], " ".join(s["skills"])) for s in record["staff"]]
    assert ml == seed.STAFF


def test_demo_accounts(client):
    names = {a["username"] if isinstance(a, dict) else a[0] for a in client.get("/auth/demo-accounts").json()}
    assert {"demo.owner", "demo.hr", "demo.housekeeping", "demo.frontoffice", "demo.store", "HS05"} <= names
    assert "E134" not in names
    fo = auth(client, "demo.frontoffice")
    assert client.get("/dispatch/performance", headers=fo).json() is not None
    me = client.get("/auth/me", headers=auth(client, "HS05")).json()["user"]
    assert me["employee_id"] == "HS05" and me["role"] == "worker"


def test_profile_logo_and_fictional_label(client, owner):
    p = client.get("/hotel/profile", headers=owner).json()
    assert p["exists"] and p["logo_url"] == "/shared/brand/himsagar-logo.svg" and "fictional" in p["display_name"]
    assert p["wifi"]["network"] == "Himsagar-Guest" and p["synthetic"]
    assert len(p["dining"]) >= 10 and all(d["price_inr"] for d in p["dining"])
    assert all(("approx." in n["distance_note"]) or not n["distance_note"] for n in p["nearby"])
    HotelProfileIn.model_validate(profiles.DEMO_PROFILE)
    tok = client.get("/rooms", headers=owner).json()["rooms"][0]["guest_token"]
    pub = client.get(f"/public/guest/{tok}").json()["profile"]
    assert pub["logo_url"] == "/shared/brand/himsagar-logo.svg" and "fictional" in pub["display_name"]


def test_inventory_sized_for_24_rooms():
    items = {i["sku"]: i for i in inventory.items(seed.DEMO_ID)}
    assert items["LIN-BT"]["par"] == round(180 * 24 / 45)
    assert inventory.check_invariant(seed.DEMO_ID) == []


def test_old_demo_tenant_is_rebuilt_and_others_untouched(client):
    other = tenants.create_tenant("Other hotel (test)")
    tenants.add_property(other["id"], "Other property", "Nainital", 10)
    mongo.col("tenants").update_one({"id": seed.DEMO_ID}, {"$set": {"demo_version": "riverside-v0"}})
    mongo.col("properties").insert_one({"id": "prop_old", "tenant_id": seed.DEMO_ID, "name": "Riverside Retreat", "rooms": 45})
    seed.ensure_demo()
    props = tenants.properties(seed.DEMO_ID)
    assert [p["name"] for p in props] == ["Himsagar Ridge Resort, Mussoorie (fictional)"]
    assert [s["employee_id"] for s in tenants.staff(seed.DEMO_ID)] == STAFF_IDS and len(
        mongo.find("rooms", {"tenant_id": seed.DEMO_ID})
    ) == 24
    assert [p["name"] for p in tenants.properties(other["id"])] == ["Other property"]
    assert auth(client, "demo.owner")  # demo accounts recreated


def test_logo_in_login_and_me(client):
    s = client.post("/auth/demo/HS05").json()
    assert s["tenant"]["logo_url"] == "/shared/brand/himsagar-logo.svg"
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {s['token']}"}).json()
    assert me["tenant"]["logo_url"] == "/shared/brand/himsagar-logo.svg"
    assert [tenants.same_origin_path(v) for v in ("https://evil.example/x.svg", "//evil/x.svg", "/a/../b.svg", None)] == [None] * 4


def test_guest_requests_carry_department_not_staff(client, owner):
    tok = client.get("/rooms", headers=owner).json()["rooms"][5]["guest_token"]
    client.post(f"/public/guest/{tok}/requests", json={"key": "tea"})
    reqs = client.get(f"/public/guest/{tok}/requests").json()["requests"]
    assert reqs and reqs[0]["department"] == "fnb_service"
    assert not {"assigned_to", "offer_to", "employee_id"} & set(reqs[0])
    view = client.get(f"/public/guest/{tok}").json()
    assert view["requests"][0]["department"] == "fnb_service" and "HS" not in str(view["requests"])


def test_demo_tenant_uses_the_live_ops_backend():
    t = tenants.get_tenant(seed.DEMO_ID)
    assert t["use_mocks"] is False and t["api_base_url"] == seed.ops_api_url() == "https://hoi-ops.onrender.com"
