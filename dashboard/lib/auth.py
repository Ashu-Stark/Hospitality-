"""Browser-session side of sign-in. Credentials are checked by the platform API; this module keeps the tokens
and decides which pages a role may open (the API enforces the same rules again on every call).

Platform admins hold two tokens: an unscoped console token and a hotel-scoped one obtained by audited
impersonation, so hotel pages always run with a tenant-scoped token.
"""

from __future__ import annotations

import streamlit as st

from . import platform

ROLES = {
    "platform_admin": "Platform admin (HOI staff)",
    "owner": "Owner / GM",
    "hr": "HR",
    "dept_head": "Department head",
    "storekeeper": "Storekeeper",
    "worker": "Employee",
}
HOTEL_ROLES = ["owner", "hr", "dept_head", "storekeeper", "worker"]

# Which hotel pages each role can open (employee app and console are separate page sets).
ACCESS = {
    "home.py": {"owner", "hr", "dept_head", "storekeeper"},
    "pages/1_Overview.py": {"owner", "hr", "dept_head"},
    "pages/2_Risk_List.py": {"owner", "hr"},
    "pages/3_Employee_Detail.py": {"owner", "hr"},
    "pages/4_What_If_Simulator.py": {"owner", "hr"},
    "pages/5_Roster.py": {"owner", "dept_head"},
    "pages/6_Closed_Loop.py": {"owner", "hr"},
    "pages/10_Dispatch.py": {"owner", "dept_head"},
    "pages/14_Rooms.py": {"owner", "dept_head"},
    "pages/11_Worker_App.py": {"owner", "dept_head"},
    "pages/13_Inventory.py": {"owner", "dept_head", "storekeeper"},
    "pages/7_Tasks.py": {"owner", "hr", "dept_head"},
    "pages/8_Voice_Ingest.py": {"owner", "dept_head"},
    "pages/12_Setup.py": {"owner"},
    "pages/15_Hotel_Setup.py": {"owner"},
    "pages/9_Admin.py": {"owner"},
}
DEMO_TENANT = "org_demo"


COOKIE = "hoi_rt"


def _start(sess: dict) -> None:
    u = sess["user"]
    st.session_state["user"] = u
    st.session_state["auth_token"] = sess["token"]
    if sess.get("refresh_token"):
        st.session_state["refresh_token"] = sess["refresh_token"]
        st.session_state["_rt_dirty"] = True
    st.session_state["tenant"] = sess.get("tenant")
    if u["role"] == "platform_admin":
        st.session_state["platform_token"] = sess["token"]
        open_workspace(DEMO_TENANT)
    from . import tenancy

    tenancy.on_tenant_change()


def login(username: str, password: str) -> str | None:
    try:
        _start(platform.login(username, password))
        return None
    except platform.PlatformError as e:
        return e.message


def register(code: str, username: str, password: str, employee_id: str | None) -> str | None:
    try:
        _start(platform.register(code, username, password, employee_id))
        return None
    except platform.PlatformError as e:
        return e.message


def demo_accounts() -> list[dict]:
    try:
        return platform.demo_accounts()
    except platform.PlatformError:
        return []


def demo_login(username: str) -> str | None:
    try:
        _start(platform.demo_login(username))
        return None
    except platform.PlatformError as e:
        return e.message


def open_workspace(tid: str) -> None:
    """Platform admin: switch the hotel-scoped token to another tenant (audited server-side)."""
    sess = platform.impersonate(tid, st.session_state["platform_token"])
    st.session_state["auth_token"] = sess["token"]
    st.session_state["tenant"] = sess["tenant"]


def logout() -> None:
    rt = st.session_state.get("refresh_token")
    if rt:
        platform.logout_token(rt)  # revoke server-side
    for k in list(st.session_state.keys()):
        if k != "_smoke_page":
            del st.session_state[k]
    st.session_state["_rt_clear"] = True


# ------------------------------------------------------------------ "stay signed in" across browser refreshes
def restore() -> None:
    """On a new browser session, exchange the refresh-token cookie for a fresh session (once per session)."""
    if current() or st.session_state.get("_restore_tried") or st.session_state.get("_rt_clear"):
        return
    st.session_state["_restore_tried"] = True
    try:
        rt = st.context.cookies.get(COOKIE)
    except Exception:  # noqa: BLE001 - no browser context (tests)
        rt = None
    if not isinstance(rt, str) or not 20 <= len(rt) <= 200 or not all(c.isalnum() or c in "-_" for c in rt):
        return
    st.session_state["refresh_token"] = rt
    if platform.try_refresh():
        from . import tenancy

        tenancy.on_tenant_change()


def sync_cookie() -> None:
    """Write (or clear) the refresh-token cookie in the browser after login, rotation or sign-out.

    SameSite=Strict, Secure on HTTPS, 14-day lifetime. The token rotates on every use and reuse revokes the
    whole session family server-side, which limits the damage if the cookie is ever copied.
    """
    import streamlit.components.v1 as components

    if st.session_state.pop("_rt_clear", False):
        components.html(f"<script>document.cookie='{COOKIE}=; Max-Age=0; path=/; SameSite=Strict';</script>", height=0)
    elif st.session_state.pop("_rt_dirty", False) and st.session_state.get("refresh_token"):
        tok = st.session_state["refresh_token"]
        if all(c.isalnum() or c in "-_" for c in tok):  # token_urlsafe alphabet only, nothing to escape
            components.html(
                "<script>document.cookie='" + COOKIE + "=" + tok + "; Max-Age=1209600; path=/; SameSite=Strict'"
                " + (location.protocol === 'https:' ? '; Secure' : '');</script>",
                height=0,
            )


def current() -> dict | None:
    return st.session_state.get("user") if st.session_state.get("auth_token") else None


def role() -> str | None:
    u = current()
    return u["role"] if u else None


def can_open(page_file: str) -> bool:
    r = role()
    if r is None:
        return False
    return r == "platform_admin" or r in ACCESS.get(page_file, set())
