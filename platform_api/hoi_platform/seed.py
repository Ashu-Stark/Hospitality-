"""Demo workspace: a synthetic hill hotel with one property, demo accounts and four weeks of inventory history."""

from __future__ import annotations

from . import config, mongo
from .services import inventory, profiles, rooms, tenants, users

DEMO_ID = "org_demo"
DEFAULT_API = "https://hospitality-management-9jdk.onrender.com"


def ensure_admin() -> None:
    """Create the platform admin ("platform") on first start when HOI_ADMIN_PASSWORD is set (required in production)."""
    s = config.settings
    if s.admin_password and not users.has_platform_admin():
        users.create("platform", s.admin_password, "platform_admin", None)


def ensure_demo() -> None:
    s = config.settings
    ensure_admin()
    if not s.seed_demo:
        return
    try:
        tenants.get_tenant(DEMO_ID)
    except Exception:  # noqa: BLE001 - first run
        tenants.create_tenant(
            "Himalayan Stays (Demo)",
            plan="growth",
            brand_color="#f07a2c",
            use_mocks=True,
            is_demo=True,
            tid=DEMO_ID,
            api_base_url=DEFAULT_API,
        )
        tenants.add_property(DEMO_ID, "Riverside Retreat", "Rishikesh, Uttarakhand", 45, 4)
        tenants.update_tenant(DEMO_ID, onboarded=True, onboarding_step=6, settings={"assign_mode": "auto", "offer_seconds": 30})
    inventory.seed_demo(DEMO_ID)
    if not rooms.list_rooms(DEMO_ID):  # 45 rooms on 4 floors, about two thirds occupied (synthetic)
        rooms.bulk_add(DEMO_ID, 3, 12)
        for i in range(1, 10):
            rooms.add_room(DEMO_ID, f"4{i:02d}", 4)
        occupied = [r["id"] for k, r in enumerate(rooms.list_rooms(DEMO_ID)) if k % 3 != 0]
        mongo.col("rooms").update_many({"tenant_id": DEMO_ID, "id": {"$in": occupied}}, {"$set": {"status": "occupied"}})
    profiles.seed_demo(DEMO_ID)  # SYNTHETIC hotel profile for the guest concierge
    if s.demo_login:
        users.ensure_demo_users(DEMO_ID, s.admin_password)
