"""Browser-session side of sign-in. Credentials are checked by the platform API; this module keeps the tokens
and decides which pages a role may open (the API enforces the same rules again on every call).

Platform admins hold two tokens: an unscoped console token and, in the hotel portal only, a hotel-scoped one
obtained by audited impersonation after they choose a hotel, so hotel pages always run with a tenant-scoped token.

Two portals run from this code (lib.config.portal()): the super-admin portal accepts platform admins only; the
hotel portal accepts hotel staff, and platform admins who then pick a hotel.
"""

from __future__ import annotations

import streamlit as st

from . import config, platform

ROLES = {
    "platform_admin": "HOI team",
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
    "pages/2_Risk_List.py": {"owner", "hr", "dept_head"},  # dept_head: own department only, no pay reasons (lib.privacy)
    "pages/3_Employee_Detail.py": {"owner", "hr", "dept_head"},
    "pages/4_What_If_Simulator.py": {"owner", "hr"},
    "pages/5_Roster.py": {"owner", "dept_head"},
    "pages/6_Closed_Loop.py": {"owner", "hr"},
    "pages/10_Dispatch.py": {"owner", "dept_head"},
    "pages/14_Rooms.py": {"owner", "dept_head"},
    "pages/17_Guest_Services.py": {"owner", "dept_head", "hr"},
    "pages/16_Hotel_Profile.py": {"owner", "dept_head", "hr", "storekeeper"},  # hr + storekeeper read-only
    "pages/11_Worker_App.py": {"owner", "dept_head"},
    "pages/13_Inventory.py": {"owner", "dept_head", "storekeeper"},
    "pages/7_Tasks.py": {"owner", "hr", "dept_head"},
    "pages/8_Voice_Ingest.py": {"owner", "dept_head"},
    "pages/12_Setup.py": {"owner"},
    "pages/15_Hotel_Setup.py": {"owner"},
    "pages/9_Admin.py": {"owner"},
    "pages/18_Recognition.py": {"owner", "hr", "dept_head"},
    "pages/19_Staff.py": {"owner", "hr", "dept_head"},
    "pages/20_Extra_Staff.py": {"owner", "hr", "dept_head"},
}
DEMO_TENANT = "org_demo"


def _cookie() -> str:
    """Separate refresh cookies per portal: on one host (e.g. localhost:8501 and :8502) cookies are shared across ports."""
    return "hoi_rt_admin" if config.is_super() else "hoi_rt"


class WrongPortal(Exception):
    pass


def allowed_here(role: str | None) -> bool:
    """Which roles may sign in to this portal (UX guard; the API enforces roles on every call regardless)."""
    return role == "platform_admin" if config.is_super() else role is not None


def wrong_portal_message(role: str) -> str:
    if role == "platform_admin":
        return f"HOI team accounts sign in here: [{config.super_portal_url()}]({config.super_portal_url()})"
    url = config.hotel_portal_url()
    return f"This page is for the HOI team only. {ROLES.get(role, role)} accounts sign in to the hotel page: [{url}]({url})"


def _start(sess: dict) -> None:
    u = sess["user"]
    if not allowed_here(u["role"]):
        if sess.get("refresh_token"):
            try:
                platform.logout_token(sess["refresh_token"])  # do not leave a live session behind
            except platform.PlatformError:
                pass
        raise WrongPortal(wrong_portal_message(u["role"]))
    st.session_state["user"] = u
    st.session_state["auth_token"] = sess["token"]
    if sess.get("refresh_token"):
        st.session_state["refresh_token"] = sess["refresh_token"]
        st.session_state["_rt_dirty"] = True
    st.session_state["tenant"] = sess.get("tenant")
    if u["role"] == "platform_admin":
        # no hotel is opened automatically: the console needs none, and in the hotel portal the admin chooses one (audited)
        st.session_state["platform_token"] = sess["token"]
        st.session_state["tenant"] = None
    from . import tenancy

    tenancy.on_tenant_change()


def login(username: str, password: str) -> str | None:
    try:
        _start(platform.login(username, password))
        return None
    except platform.PlatformError as e:
        return e.message
    except WrongPortal as e:
        return str(e)


def register(code: str, username: str, password: str, employee_id: str | None) -> str | None:
    try:
        _start(platform.register(code, username, password, employee_id))
        return None
    except platform.PlatformError as e:
        return e.message
    except WrongPortal as e:
        return str(e)


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
    except WrongPortal as e:
        return str(e)


def open_workspace(tid: str) -> None:
    """Platform admin, hotel portal only: switch the hotel-scoped token to another tenant (audited server-side)."""
    if config.is_super():
        raise RuntimeError("Open hotels from the hotel sign-in page, not from the HOI team console.")
    sess = platform.impersonate(tid, st.session_state["platform_token"])
    st.session_state["auth_token"] = sess["token"]
    st.session_state["tenant"] = sess["tenant"]
    st.session_state["imp_tid"] = tid


def exit_workspace() -> None:
    """Platform admin in the hotel portal: close the hotel and go back to choosing one."""
    st.session_state["auth_token"] = st.session_state.get("platform_token")
    st.session_state["tenant"] = None
    st.session_state.pop("imp_tid", None)
    from . import tenancy

    tenancy.on_tenant_change()


def impersonating() -> bool:
    """A platform admin viewing a hotel in the hotel portal."""
    return role() == "platform_admin" and not config.is_super() and bool(st.session_state.get("imp_tid"))


def needs_hotel() -> bool:
    """A platform admin signed in to the hotel portal who has not chosen a hotel yet."""
    return role() == "platform_admin" and not config.is_super() and not st.session_state.get("imp_tid")


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
        rt = st.context.cookies.get(_cookie())
    except Exception:  # noqa: BLE001 - no browser context (tests)
        rt = None
    if not isinstance(rt, str) or not 20 <= len(rt) <= 200 or not all(c.isalnum() or c in "-_" for c in rt):
        return
    st.session_state["refresh_token"] = rt
    if platform.try_refresh():
        if not allowed_here(role()):  # e.g. a hotel account's cookie reaching the platform console
            logout()
            return
        from . import tenancy

        tenancy.on_tenant_change()


def sync_cookie() -> None:
    """Write (or clear) the refresh-token cookie in the browser after login, rotation or sign-out.

    SameSite=Strict, Secure on HTTPS, 14-day lifetime. The token rotates on every use and reuse revokes the
    whole session family server-side, which limits the damage if the cookie is ever copied.
    """
    import streamlit.components.v1 as components

    if st.session_state.pop("_rt_clear", False):
        components.html(f"<script>document.cookie='{_cookie()}=; Max-Age=0; path=/; SameSite=Strict';</script>", height=0)
    elif st.session_state.pop("_rt_dirty", False) and st.session_state.get("refresh_token"):
        tok = st.session_state["refresh_token"]
        if all(c.isalnum() or c in "-_" for c in tok):  # token_urlsafe alphabet only, nothing to escape
            components.html(
                "<script>document.cookie='" + _cookie() + "=" + tok + "; Max-Age=1209600; path=/; SameSite=Strict'"
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
