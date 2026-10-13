"""Which pages each signed-in user sees: role (auth.ACCESS) ∩ modules enabled for the tenant's plan."""

from __future__ import annotations

from . import auth, tenancy

HOTEL_PAGES = [
    ("home.py", "Home", ":material/home:"),
    ("pages/1_Overview.py", "Overview", ":material/dashboard:"),
    ("pages/2_Risk_List.py", "Risk", ":material/flag:"),
    ("pages/3_Employee_Detail.py", "Employee", ":material/person:"),
    ("pages/4_What_If_Simulator.py", "What-if", ":material/tune:"),
    ("pages/5_Roster.py", "Roster", ":material/calendar_month:"),
    ("pages/6_Closed_Loop.py", "Closed loop", ":material/sync:"),
    ("pages/10_Dispatch.py", "Dispatch", ":material/bolt:"),
    ("pages/14_Rooms.py", "Rooms", ":material/bed:"),
    ("pages/17_Guest_Services.py", "Guest services", ":material/room_service:"),
    ("pages/11_Worker_App.py", "Worker preview", ":material/smartphone:"),
    ("pages/13_Inventory.py", "Inventory", ":material/inventory_2:"),
    ("pages/7_Tasks.py", "Tasks", ":material/task_alt:"),
    ("pages/8_Voice_Ingest.py", "Voice", ":material/mic:"),
    ("pages/16_Hotel_Profile.py", "Hotel profile", ":material/storefront:"),
    ("pages/12_Setup.py", "Setup", ":material/add_business:"),
    ("pages/15_Hotel_Setup.py", "Hotel setup (voice)", ":material/record_voice_over:"),
    ("pages/9_Admin.py", "Admin", ":material/settings:"),
]
CONSOLE_PAGES = [
    ("console/1_Tenants.py", "Hotels", ":material/apartment:"),
    ("console/3_Insights.py", "Insights", ":material/insights:"),
    ("console/2_Audit.py", "Audit log", ":material/receipt_long:"),
]
EMPLOYEE_PAGES = [
    ("employee/1_My_Day.py", "My day", ":material/today:"),
    ("employee/2_Jobs.py", "Jobs", ":material/bolt:"),
    ("employee/3_Supplies.py", "Supplies", ":material/inventory_2:"),
    ("employee/4_My_Tasks.py", "My tasks", ":material/task_alt:"),
]
LOGIN_PAGE = ("login.py", "Sign in", ":material/login:")

MODULE_PAGES = {
    "retention": {"pages/2_Risk_List.py", "pages/3_Employee_Detail.py", "pages/4_What_If_Simulator.py", "pages/6_Closed_Loop.py"},
    "roster": {"pages/5_Roster.py"},
    "dispatch": {"pages/10_Dispatch.py", "pages/11_Worker_App.py", "pages/14_Rooms.py"},
    "inventory": {"pages/13_Inventory.py"},
    "voice": {"pages/8_Voice_Ingest.py"},
}
MODULE_LABELS = {
    "retention": "Retention (risk, what-if, closed loop)",
    "roster": "Roster solver",
    "dispatch": "Dispatch, rooms + photo proof",
    "inventory": "Inventory",
    "voice": "Voice to task",
}
PLAN_MODULES = {
    "starter": ["roster", "dispatch", "inventory"],
    "growth": ["roster", "dispatch", "inventory", "retention", "voice"],
    "chain": list(MODULE_PAGES),
}


def modules_for(t: dict) -> list[str]:
    return t.get("modules") or tenancy.settings_of(t).get("modules") or PLAN_MODULES.get(t.get("plan", "starter"), PLAN_MODULES["starter"])


def page_enabled(page_file: str, t: dict) -> bool:
    mods = modules_for(t)
    return not any(page_file in pages and m not in mods for m, pages in MODULE_PAGES.items())


def visible_pages() -> list[tuple[str, str, str]]:
    r = auth.role()
    if r is None:
        return [LOGIN_PAGE]
    if r == "worker":
        return EMPLOYEE_PAGES
    t = tenancy.active()
    hotel = [p for p in HOTEL_PAGES if auth.can_open(p[0]) and (r == "platform_admin" or page_enabled(p[0], t))]
    return (CONSOLE_PAGES if r == "platform_admin" else []) + hotel
