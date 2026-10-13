"""Shared page shell: page config, CSS, top pill nav, sidebar controls, error banners, name resolution."""

from __future__ import annotations

import base64
import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import streamlit as st

from . import access, auth, config, data, nav, platform, portal, tenancy, theme, tour
from .api_client import ApiError
from .config import current_settings

PAGES = access.HOTEL_PAGES  # kept for older imports


def setup(page_file: str, title: str, *, employee: bool = False) -> None:
    """Every page starts here: tenant, CSS, access check, top bar, sidebar, tour."""
    t = tenancy.bootstrap()
    st.markdown(theme.CSS, unsafe_allow_html=True)
    st.markdown(f"<style>:root{{--brand:{theme.esc(portal.brand_color(t))}}}</style>{portal.css()}", unsafe_allow_html=True)
    u = auth.current()
    if u is None or not auth.allowed_here(u["role"]):  # signed out, deep link, or wrong portal: show sign-in here
        from . import login_ui

        login_ui.render()
        st.stop()
    # a page is open to this user only if it is in their navigation: portal ∩ role ∩ plan modules (the API re-checks)
    visible = access.visible_pages()
    allowed = page_file in [f for f, _, _ in visible] and (u["role"] == "worker") == employee
    if not allowed and (auth.needs_hotel() or auth.impersonating()):
        # platform admin in the hotel portal: Home and the hotel picker are registered across the switch (app.py), so a
        # stale URL can land on the one not allowed right now: go to the right one instead of showing "no access"
        st.switch_page(nav.page(visible[0][0]))
    _topbar(page_file, t, u)
    if not allowed:
        html(theme.banner("<b>You do not have access to this page.</b> Ask your hotel admin if you need it.", "red", "shield"))
        st.stop()
    if auth.impersonating():
        portal.impersonation_banner(t)
    if not employee and page_file != access.PICK_PAGE[0]:
        _sidebar(t, u)
        tour.render(page_file)


def _topbar(page_file: str, t: dict, u: dict | None) -> None:
    s = current_settings()
    mode_cls = "mock" if s.use_mocks else "live"
    who = ""
    if u:
        who = f'<span class="ss-userchip">{theme.icon("user", 14)}{theme.esc(u["username"])} · {theme.esc(auth.ROLES[u["role"]].split(" (")[0])}</span>'
    if config.is_super():
        where, cls = "", "ss-topbar ss-super"
    else:
        where, cls = "", "ss-topbar ss-hotel"
        if t.get("id"):
            where = f'<span class="ss-tenant"><i style="background:var(--brand)"></i>{theme.esc(t["name"])}</span>'
    st.markdown(
        f'<div class="{cls}">{portal.brand_html(t)}'
        f'<div class="ss-util">{who}{where}<span class="ss-mode {mode_cls}">{s.mode_label}</span></div></div>',
        unsafe_allow_html=True,
    )
    nav = st.session_state.get("_nav") or access.HOTEL_PAGES
    with st.container(key="ss_nav"):
        cols = st.columns(len(nav) + (1 if u else 0), gap="small")
        for col, (f, label, ic) in zip(cols, nav):
            with col:
                if f == page_file:
                    st.markdown(f'<div class="ss-navactive">{label}</div>', unsafe_allow_html=True)
                else:  # Page objects avoid path resolution (robust for deep-linked sessions)
                    st.page_link(st.session_state.get("_page_by_file", {}).get(f, f), label=label)
        if u:
            with cols[-1]:
                if st.button("Sign out", key="signout", type="tertiary"):
                    auth.logout()
                    st.rerun()


def _sidebar(t: dict, u: dict | None) -> None:
    s = current_settings()
    with st.sidebar:
        if config.is_super():  # platform console: no hotel workspace, no scoring week
            html(
                f'<div class="ss-card" style="padding:12px 14px"><div style="color:#6b6a65;font-size:.75rem">Portal</div>'
                f"<b>HOI Platform Admin</b><div style='font-size:.8rem;margin-top:6px'>Hotel admin portal: "
                f"{portal.link(config.hotel_portal_url())}</div></div>"
            )
            if st.button("Refresh", icon=":material/refresh:", width="stretch"):
                data.clear()
                st.rerun()
            st.divider()
            st.markdown(
                theme.banner("All hotel data is <b>synthetic</b>. Every console action is audited.", "gray", "shield"),
                unsafe_allow_html=True,
            )
            return
        if u and u["role"] == "platform_admin":
            try:
                ts = [x for x in platform.tenants() if x["status"] == "active"]
            except platform.PlatformError:
                ts = []
            ids = [x["id"] for x in ts]
            if ids:
                pick = st.selectbox(
                    "Hotel workspace (platform admin)",
                    ids,
                    index=ids.index(t["id"]) if t["id"] in ids else 0,
                    format_func=lambda i: next(x["name"] for x in ts if x["id"] == i),
                    key="ws_pick",
                )
                if pick != t["id"]:
                    auth.open_workspace(pick)  # audited server-side
                    tenancy.on_tenant_change()
                    st.rerun()
            if st.button("Exit to hotel selection", icon=":material/logout:", width="stretch", key="imp_exit_sb"):
                portal.exit_hotel()
        else:
            html(
                f'<div class="ss-card" style="padding:12px 14px"><div style="color:#6b6a65;font-size:.75rem">Workspace</div>'
                f"<b>{theme.esc(t['name'])}</b></div>"
            )
        st.markdown(f'<span class="ss-mode {"mock" if s.use_mocks else "live"}">{s.mode_label}</span>', unsafe_allow_html=True)
        st.caption("Demo data (captured from the API)." if s.use_mocks else f"Backend: {s.api_base_url}")
        anchor = ensure_demo_week()
        if anchor:
            opts = data.week_options(anchor)
            cur = st.session_state.get("week_start", anchor)
            st.selectbox(
                "Scoring week (Monday)",
                opts,
                index=opts.index(cur) if cur in opts else 0,
                key="week_start",
                help="Global week used by Risk list, Employee and Overview. The demo week is the latest week in the synthetic data.",
            )
            if s.use_mocks and st.session_state.get("week_start") != anchor:
                st.caption("Demo data only holds the demo week; other weeks need a live backend.")
        c1, c2 = st.columns(2)
        if c1.button("Refresh", icon=":material/refresh:", width="stretch"):
            data.clear()
            st.rerun()
        if t.get("is_demo") and (u is None or u["role"] in ("owner", "platform_admin")):
            if c2.button("Tour", icon=":material/explore:", width="stretch"):
                tour.start()
        st.divider()
        st.markdown(
            theme.banner(
                "All data is <b>synthetic</b>. Risk flags exist to <b>offer support</b>, never for adverse action. "
                "Bands are rankings, not predictions that someone will leave.",
                "gray",
                "shield",
            ),
            unsafe_allow_html=True,
        )


def ensure_demo_week() -> str | None:
    """Learn the backend's demo week once per session from the score table."""
    if "demo_week" not in st.session_state:
        try:
            rows = data.scores(None)
            st.session_state["demo_week"] = rows[0].week_start if rows else None
        except ApiError:
            st.session_state["demo_week"] = None
    return st.session_state.get("demo_week")


def week() -> str | None:
    """The globally selected scoring week (None means the backend default)."""
    w = st.session_state.get("week_start")
    return None if not w or w == st.session_state.get("demo_week") else w


def safe(fn: Callable[..., Any], *args, what: str = "load data", **kwargs) -> Any:
    """Run an API call; on failure show a plain-language banner and return None (never a stack trace)."""
    try:
        return fn(*args, **kwargs)
    except ApiError as e:
        st.markdown(theme.banner(f"<b>Could not {theme.esc(what)}.</b> {theme.esc(e.message)}", "red", "alert"), unsafe_allow_html=True)
        with st.expander("Technical detail"):
            st.write({"endpoint": e.endpoint, "status": e.status, "detail": e.detail})
        return None


def empty(msg: str) -> None:
    st.markdown(theme.banner(theme.esc(msg), "gray", "info"), unsafe_allow_html=True)


def html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


# ------------------------------------------------------------------ privacy-safe naming
def display_name(employee_id: str | None) -> str:
    """Hero display name (scripted demo staff only) or 'Employee E0xx'. No other name ever appears."""
    if not employee_id:
        return "—"
    n = data.hero_names().get(str(employee_id))
    return f"{n} ({employee_id})" if n else f"Employee {employee_id}"


def short_name(employee_id: str | None) -> str:
    n = data.hero_names().get(str(employee_id or ""))
    return n or str(employee_id or "—")


def initials(employee_id: str | None) -> str:
    if not employee_id:
        return "?"
    n = data.hero_names().get(employee_id)
    return n[0] if n else employee_id[-3:]


# ------------------------------------------------------------------ role avatars (no faces, names or gender)
# Illustrated badges per department / role. Same SVGs as platform_api/hoi_platform/static/shared/avatars (dashboard-local
# copy so the dashboard image stays self-contained). Embedded as data URIs: works in embedded and remote modes alike and
# needs no static file serving.
AVATAR_DIR = Path(__file__).resolve().parent.parent / "static" / "avatars"
AVATAR_ROLES = (
    "hotel_manager",
    "front_office",
    "housekeeping",
    "fnb_service",
    "kitchen",
    "maintenance",
    "security",
    "storekeeper",
    "generic",
)
_AVATAR_ALIAS = {
    "manager": "hotel_manager",
    "owner": "hotel_manager",
    "fnb": "fnb_service",
    "store": "storekeeper",
    "stores": "storekeeper",
}


def avatar_role(department: str | None) -> str:
    """The one place that maps a department / role to an avatar; unknown -> generic."""
    k = str(department or "").strip().lower()
    return k if k in AVATAR_ROLES else _AVATAR_ALIAS.get(k, "generic")


@functools.cache
def _avatar_uri(role: str) -> str:
    try:
        raw = (AVATAR_DIR / f"{role}.svg").read_bytes()
    except OSError:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode()


def avatar_uri(department: str | None) -> str:
    """data: URI of the role avatar (for st.column_config.ImageColumn or <img>)."""
    return _avatar_uri(avatar_role(department))


def avatar_img(department: str | None, size: int = 28, cls: str = "") -> str:
    """Small decorative <img> (the department label sits next to it as text)."""
    uri = avatar_uri(department)
    if not uri:
        return ""
    return f'<img class="ss-ravatar {cls}" src="{uri}" alt="" width="{size}" height="{size}">'


def go_to_employee(employee_id: str) -> None:
    st.session_state["selected_employee"] = employee_id
    st.switch_page(nav.page("pages/3_Employee_Detail.py"))


def footer() -> None:
    s = current_settings()
    html(
        f'<div class="ss-footer"><span>Hospitality Operations Intelligence (HOI) · AI-Tourism Hackathon 2026 · synthetic data, TRL 4</span>'
        f"<span>{s.mode_label} · {theme.esc(s.api_base_url if not s.use_mocks else 'dashboard/mocks')}</span></div>"
    )


def inr(v: float | None) -> str:
    if v is None:
        return "—"
    v = float(v)
    if abs(v) >= 1e5:
        return f"₹{v / 1e5:.2f} L"
    return f"₹{v:,.0f}"


def pct(v: float | None, digits: int = 0) -> str:
    return "—" if v is None else f"{float(v) * 100:.{digits}f}%"


# ------------------------------------------------------------------ platform API calls with friendly failures
NEEDS_API = "missing"  # returned by api() when the platform API has no such route yet


def needs_api_banner(what: str) -> None:
    html(
        theme.banner(
            f"<b>This feature needs the updated platform API.</b> The server you are connected to does not offer "
            f"{theme.esc(what)} yet. Update and restart the platform API, then press Refresh.",
            "amber",
            "info",
        )
    )


def api(fn: Callable[..., Any], *args, what: str = "load data", feature: str | None = None, **kwargs) -> Any:
    """Call a lib.platform function. Missing route (404) -> amber 'needs the updated platform API' banner and NEEDS_API;
    any other failure -> red banner and None. Never raises."""
    try:
        return fn(*args, **kwargs)
    except platform.PlatformError as e:
        if platform.feature_missing(e):
            needs_api_banner(feature or what)
            return NEEDS_API
        html(theme.banner(f"<b>Could not {theme.esc(what)}.</b> {theme.esc(e.message)}", "red", "alert"))
        return None


def as_list(x: Any, *keys: str) -> list:
    """Accept either a bare list or an object wrapping it under one of `keys` (API responses vary by endpoint)."""
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for k in keys:
            if isinstance(x.get(k), list):
                return x[k]
    return []


def pick(d: Any, *paths: str, default: Any = None) -> Any:
    """First non-None value among dotted paths, e.g. pick(h, 'jobs.on_time_pct', 'on_time_pct')."""
    for p in paths:
        cur = d
        for part in p.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur is not None:
            return cur
    return default


def stars(rating: Any) -> str:
    try:
        r = max(0, min(5, round(float(rating))))
    except (TypeError, ValueError):
        return "—"
    return "★" * r + "☆" * (5 - r)


def paginate(rows: list, key: str, per_page: int = 20) -> list:
    """Show `per_page` rows at a time with a small page picker underneath when there are more."""
    if len(rows) <= per_page:
        return rows
    pages = (len(rows) + per_page - 1) // per_page
    n = st.number_input(f"Page (of {pages})", 1, pages, 1, key=key)
    st.caption(f"Showing {(n - 1) * per_page + 1}–{min(n * per_page, len(rows))} of {len(rows)}")
    return rows[(n - 1) * per_page : n * per_page]
