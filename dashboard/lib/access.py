"""Which pages each signed-in user sees: portal (ADMIN_PORTAL) ∩ role (auth.ACCESS) ∩ modules enabled for the tenant's plan.

super-admin portal: SUPER_PAGES (home summary + console), platform admins only
hotel portal:       HOTEL_PAGES by role and plan, EMPLOYEE_PAGES for workers; platform admins first PICK_PAGE a hotel
"""

from __future__ import annotations

from . import auth, config, tenancy

HOTEL_PAGES = [
    ("home.py", "Today", ":material/today:"),
    ("pages/10_Dispatch.py", "Jobs", ":material/bolt:"),
    ("pages/7_Tasks.py", "Tasks", ":material/task_alt:"),
    ("pages/1_Overview.py", "Week numbers", ":material/dashboard:"),
    ("pages/8_Voice_Ingest.py", "Voice note", ":material/mic:"),
    ("pages/19_Staff.py", "Staff on shift", ":material/badge:"),
    ("pages/21_Work_Log.py", "Work log", ":material/schedule:"),
    ("pages/5_Roster.py", "Shift plan", ":material/calendar_month:"),
    ("pages/18_Recognition.py", "Thank-you points", ":material/workspace_premium:"),
    ("pages/20_Extra_Staff.py", "Extra staff", ":material/group_add:"),
    ("pages/2_Risk_List.py", "May leave soon?", ":material/volunteer_activism:"),
    ("pages/3_Employee_Detail.py", "Employee", ":material/person:"),
    ("pages/4_What_If_Simulator.py", "Try a change", ":material/tune:"),
    ("pages/6_Closed_Loop.py", "Support plan", ":material/sync:"),
    ("pages/14_Rooms.py", "Rooms", ":material/bed:"),
    ("pages/17_Guest_Services.py", "Guest requests", ":material/room_service:"),
    ("pages/16_Hotel_Profile.py", "Hotel profile", ":material/storefront:"),
    ("pages/11_Worker_App.py", "Staff app preview", ":material/smartphone:"),
    ("pages/13_Inventory.py", "Stock", ":material/inventory_2:"),
    ("pages/12_Setup.py", "Settings", ":material/settings:"),
    ("pages/15_Hotel_Setup.py", "Setup by voice", ":material/record_voice_over:"),
    ("pages/9_Admin.py", "System", ":material/dns:"),
]
# The hotel portal's navigation: at most five sections (top row), each with its pages (second row).
# Pages in HIDDEN_IN_NAV stay routable (drill-downs) but get no button of their own.
SECTIONS = [
    (
        "Today",
        ":material/today:",
        ["home.py", "pages/10_Dispatch.py", "pages/7_Tasks.py", "pages/1_Overview.py", "pages/8_Voice_Ingest.py"],
    ),
    (
        "People",
        ":material/groups:",
        [
            "pages/19_Staff.py",
            "pages/21_Work_Log.py",
            "pages/5_Roster.py",
            "pages/18_Recognition.py",
            "pages/20_Extra_Staff.py",
            "pages/2_Risk_List.py",
            "pages/3_Employee_Detail.py",
            "pages/4_What_If_Simulator.py",
            "pages/6_Closed_Loop.py",
        ],
    ),
    (
        "Rooms & guests",
        ":material/bed:",
        ["pages/14_Rooms.py", "pages/17_Guest_Services.py", "pages/16_Hotel_Profile.py", "pages/11_Worker_App.py"],
    ),
    ("Stock", ":material/inventory_2:", ["pages/13_Inventory.py"]),
    ("Settings", ":material/settings:", ["pages/12_Setup.py", "pages/15_Hotel_Setup.py", "pages/9_Admin.py"]),
]
HIDDEN_IN_NAV = {"pages/3_Employee_Detail.py"}
# Homestay mode (small properties): a minimal app with plain words. Everything else is hidden (not routable).
HOMESTAY_PAGES = {
    "home.py",
    "pages/19_Staff.py",
    "pages/14_Rooms.py",
    "pages/17_Guest_Services.py",
    "pages/16_Hotel_Profile.py",
    "pages/13_Inventory.py",
    "pages/12_Setup.py",
}
HOMESTAY_LABELS = {"pages/19_Staff.py": "Our team", "pages/13_Inventory.py": "Stock basics"}
CONSOLE_PAGES = [
    ("console/1_Tenants.py", "Hotels", ":material/apartment:"),
    ("console/3_Insights.py", "Insights", ":material/insights:"),
    ("console/2_Audit.py", "Activity log", ":material/receipt_long:"),
]
EMPLOYEE_PAGES = [
    ("employee/1_My_Day.py", "My day", ":material/today:"),
    ("employee/2_Jobs.py", "Jobs", ":material/bolt:"),
    ("employee/3_Supplies.py", "Supplies", ":material/inventory_2:"),
    ("employee/4_My_Tasks.py", "My tasks", ":material/task_alt:"),
]
SUPER_PAGES = [("console/0_Home.py", "Home", ":material/home:"), *CONSOLE_PAGES]
PICK_PAGE = ("pick_hotel.py", "Choose a hotel", ":material/apartment:")
LOGIN_PAGE = ("login.py", "Sign in", ":material/login:")

MODULE_PAGES = {
    "retention": {"pages/2_Risk_List.py", "pages/3_Employee_Detail.py", "pages/4_What_If_Simulator.py", "pages/6_Closed_Loop.py"},
    "roster": {"pages/5_Roster.py", "pages/20_Extra_Staff.py"},
    "dispatch": {"pages/10_Dispatch.py", "pages/11_Worker_App.py", "pages/14_Rooms.py", "pages/18_Recognition.py", "pages/21_Work_Log.py"},
    "inventory": {"pages/13_Inventory.py"},
    "voice": {"pages/8_Voice_Ingest.py"},
}
MODULE_LABELS = {
    "retention": "May leave soon? (check-ins, try a change, support plan)",
    "roster": "Shift plan",
    "dispatch": "Jobs, rooms and photo proof",
    "inventory": "Stock",
    "voice": "Voice notes into tasks",
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


def portal_pages() -> list[tuple[str, str, str]]:
    """Every page this portal can route (used for deep links while signed out)."""
    return SUPER_PAGES if config.is_super() else [*HOTEL_PAGES, PICK_PAGE, *EMPLOYEE_PAGES]


def visible_pages() -> list[tuple[str, str, str]]:
    r = auth.role()
    if r is None or not auth.allowed_here(r):
        return [LOGIN_PAGE]
    if config.is_super():
        return SUPER_PAGES  # platform admins only (allowed_here)
    if r == "worker":
        return EMPLOYEE_PAGES
    if auth.needs_hotel():
        return [PICK_PAGE]
    t = tenancy.active()
    pages = [p for p in HOTEL_PAGES if auth.can_open(p[0]) and (r == "platform_admin" or page_enabled(p[0], t))]
    if tenancy.mode() == "homestay":
        pages = [(f, HOMESTAY_LABELS.get(f, label), ic) for f, label, ic in pages if f in HOMESTAY_PAGES]
    return pages


def sections(nav: list[tuple[str, str, str]]) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
    """Group a visible page list into the (at most five) navigation sections; empty sections are dropped."""
    by = {f: (f, label, ic) for f, label, ic in nav}
    out = []
    for name, ic, files in SECTIONS:
        pages = [by[f] for f in files if f in by]
        if pages:
            out.append((name, ic, pages))
    return out


def section_of(page_file: str) -> str | None:
    return next((name for name, _, files in SECTIONS if page_file in files), None)
