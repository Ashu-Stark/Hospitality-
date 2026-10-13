"""Demo workspace: the FICTIONAL "Himsagar Ridge Resort, Mussoorie" (SYNTHETIC data), its 24 rooms, 20 staff (ids
and role titles only), demo accounts, hotel profile and four weeks of inventory history.

The staff list matches the backend's SYNTHETIC hotel dataset (ml/data/hotels/himsagar/hotel.json: ids, departments,
contract types and skills of the demo week). Ids only: no names or personal attributes. Every value is ASSUMED.

`ensure_demo()` runs at startup. A demo tenant seeded by an older version (the former "Riverside Retreat" demo hotel) is
detected by its `demo_version` and rebuilt: every document of the demo tenant is deleted first (`reset_demo()`), other
tenants are never touched. CLI (e.g. to reseed a real cluster):  python -m hoi_platform.seed --reset-demo
"""

from __future__ import annotations

import os
import re
import sys

from . import config, mongo
from .services import inventory, profiles, rooms, tenants, users

DEMO_ID = "org_demo"
DEMO_VERSION = "himsagar-v2"  # bump to rebuild the demo tenant on the next start
DEFAULT_OPS_API = "https://hoi-ops.onrender.com"  # the ML / ops backend; override with env OPS_API_URL
HOTEL_NAME = "Himsagar Ridge Resort, Mussoorie (fictional)"
TENANT_NAME = "Himsagar Ridge Resort (fictional demo)"
REGION = "Mussoorie, Uttarakhand"
FLOORS, ROOMS_PER_FLOOR = 3, 8  # rooms 101-108, 201-208, 301-308
LOGO_URL = "/shared/brand/himsagar-logo.svg"

# employee_id, department, role title, contract type, skills (space-separated). HS01 = hotel manager (owner side,
# not rostered). The rest are the demo week's staff of ml/data/hotels/himsagar (SYNTHETIC).
STAFF = [
    ("HS01", "management", "Hotel manager", "permanent", ""),
    ("HS02", "housekeeping", "Executive housekeeper", "permanent", "deep_clean room_cleaning turndown"),
    ("HS03", "housekeeping", "Housekeeping supervisor", "permanent", "laundry turndown"),
    ("HS04", "housekeeping", "Housekeeping attendant", "permanent", "laundry turndown"),
    ("HS05", "housekeeping", "Housekeeping attendant", "permanent", "laundry"),
    ("HS06", "housekeeping", "Housekeeping attendant", "seasonal", "deep_clean laundry"),
    ("HS07", "housekeeping", "Housekeeping attendant", "seasonal", "room_cleaning"),
    ("HS08", "front_office", "Front office manager", "permanent", "cash_handling fo_system form_c_reporting"),
    ("HS09", "front_office", "Front office associate", "permanent", "cash_handling fo_system form_c_reporting"),
    ("HS10", "front_office", "Front office associate", "permanent", "cash_handling fo_system"),
    ("HS11", "fnb_service", "F&B supervisor", "permanent", "banquet bar table_service"),
    ("HS12", "fnb_service", "Restaurant server", "permanent", "banquet table_service"),
    ("HS13", "fnb_service", "Restaurant server", "seasonal", "bar table_service"),
    ("HS14", "kitchen", "Head chef", "permanent", "baking prep tandoor"),
    ("HS15", "kitchen", "Cook", "permanent", "baking continental tandoor"),
    ("HS16", "kitchen", "Kitchen helper", "seasonal", "continental prep tandoor"),
    ("HS17", "maintenance", "Maintenance supervisor", "permanent", "boiler_geyser electrical plumbing"),
    ("HS18", "maintenance", "Maintenance technician", "permanent", "boiler_geyser electrical plumbing"),
    ("HS19", "security", "Security supervisor", "permanent", "first_aid_fire patrol"),
    ("HS20", "security", "Security guard", "permanent", "first_aid_fire patrol"),
]


def slug(title: str) -> str:
    """Avatar key = role slug ("F&B supervisor" -> "fnb-supervisor"); the images live under /shared/."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower().replace("&", "n")).strip("-")


def staff_rows() -> list[dict]:
    return [
        {"employee_id": e, "department": d, "role_title": t, "avatar": slug(t), "contract_type": c, "skills": s} for e, d, t, c, s in STAFF
    ]


def ops_api_url() -> str:
    return (os.getenv("OPS_API_URL") or DEFAULT_OPS_API).strip().rstrip("/")


def ensure_admin() -> None:
    """Create the platform admin ("platform") on first start when HOI_ADMIN_PASSWORD is set (required in production)."""
    s = config.settings
    if s.admin_password and not users.has_platform_admin():
        users.create("platform", s.admin_password, "platform_admin", None)


def reset_demo() -> None:
    """Delete every document of the demo tenant (not its audit log, not other tenants)."""
    d = mongo.db()
    for name in tenants.TENANT_COLLECTIONS:
        d[name].delete_many({"tenant_id": DEMO_ID})
    uids = [u["id"] for u in d.users.find({"tenant_id": DEMO_ID}, {"id": 1})]
    if uids:
        d.refresh_tokens.delete_many({"user_id": {"$in": uids}})
    d.users.delete_many({"tenant_id": DEMO_ID})
    d.tenants.delete_one({"id": DEMO_ID})


def _create_demo() -> None:
    tenants.create_tenant(
        TENANT_NAME,
        plan="growth",
        brand_color="#2f6f8f",
        use_mocks=False,  # the dashboard shows the live backend's numbers for the demo hotel
        is_demo=True,
        tid=DEMO_ID,
        api_base_url=ops_api_url(),
    )
    prop = tenants.add_property(DEMO_ID, HOTEL_NAME, REGION, FLOORS * ROOMS_PER_FLOOR, FLOORS)
    tenants.update_tenant(DEMO_ID, onboarded=True, onboarding_step=6, settings={"assign_mode": "auto", "offer_seconds": 30})
    mongo.col("tenants").update_one({"id": DEMO_ID}, {"$set": {"demo_version": DEMO_VERSION, "logo_url": LOGO_URL}})
    tenants.import_staff(DEMO_ID, staff_rows())
    rooms.bulk_add(DEMO_ID, FLOORS, ROOMS_PER_FLOOR, prop["id"])
    # 18 of 24 occupied (synthetic): rooms ending in 3 or 6 are ready for arrivals
    occupied = [r["id"] for r in rooms.list_rooms(DEMO_ID) if r["number"][-1] not in "36"]
    mongo.col("rooms").update_many({"tenant_id": DEMO_ID, "id": {"$in": occupied}}, {"$set": {"status": "occupied"}})


def ensure_demo() -> None:
    s = config.settings
    ensure_admin()
    if not s.seed_demo:
        return
    current = mongo.col("tenants").find_one({"id": DEMO_ID}, {"demo_version": 1})
    if current is not None and current.get("demo_version") != DEMO_VERSION:
        reset_demo()  # an older demo hotel: rebuild it as the current one
        current = None
    if current is None:
        _create_demo()
    inventory.seed_demo(DEMO_ID, rooms=FLOORS * ROOMS_PER_FLOOR)
    profiles.seed_demo(DEMO_ID)  # SYNTHETIC hotel profile for the guest concierge
    if s.demo_login:
        users.ensure_demo_users(DEMO_ID, s.admin_password)


def main(argv: list[str]) -> int:
    if argv[:1] != ["--reset-demo"]:
        print("usage: python -m hoi_platform.seed --reset-demo   (rebuilds only the demo tenant org_demo)")
        return 2
    reset_demo()
    ensure_demo()
    t = tenants.get_tenant(DEMO_ID)
    print(
        f"demo tenant rebuilt on {mongo.backend()}: {t['name']}, {len(rooms.list_rooms(DEMO_ID))} rooms, "
        f"{len(tenants.staff(DEMO_ID))} staff, {len(users.list_for_tenant(DEMO_ID))} users (SYNTHETIC)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
