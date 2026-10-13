"""Shared page shell: page config, CSS, top pill nav, sidebar controls, error banners, name resolution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from . import access, auth, data, nav, platform, tenancy, theme, tour
from .api_client import ApiError
from .config import current_settings

PAGES = access.HOTEL_PAGES  # kept for older imports


def setup(page_file: str, title: str, *, employee: bool = False) -> None:
    """Every page starts here: tenant, CSS, access check, top bar, sidebar, tour."""
    t = tenancy.bootstrap()
    st.markdown(theme.CSS, unsafe_allow_html=True)
    st.markdown(f"<style>:root{{--brand:{theme.esc(t['brand_color'])}}}</style>", unsafe_allow_html=True)
    u = auth.current()
    if u is None:  # deep link while signed out (or after a browser refresh): show sign-in here
        from . import login_ui

        login_ui.render()
        st.stop()
    allowed = u is not None and (
        u["role"] == "worker"
        if employee
        else auth.can_open(page_file) or page_file.startswith("console/") and u["role"] == "platform_admin"
    )
    _topbar(page_file, t, u)
    if not allowed:
        html(theme.banner("<b>You do not have access to this page.</b> Ask your hotel admin if you need it.", "red", "shield"))
        st.stop()
    if not employee:
        _sidebar(t, u)
        tour.render(page_file)


def _topbar(page_file: str, t: dict, u: dict | None) -> None:
    s = current_settings()
    mode_cls = "mock" if s.use_mocks else "live"
    who = ""
    if u:
        who = f'<span class="ss-userchip">{theme.icon("user", 14)}{theme.esc(u["username"])} · {theme.esc(auth.ROLES[u["role"]].split(" (")[0])}</span>'
    st.markdown(
        f'<div class="ss-topbar"><div class="ss-brand"><span class="ss-brand-mark" style="background:var(--brand)">{theme.icon("bed", 20, "#fff")}</span>'
        f'<span>HOI <span class="ss-brand-long">Hospitality Operations Intelligence</span></span></div>'
        f'<div class="ss-util">{who}<span class="ss-tenant"><i style="background:var(--brand)"></i>{theme.esc(t["name"])}</span>'
        f'<span class="ss-mode {mode_cls}">{s.mode_label}</span></div></div>',
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
