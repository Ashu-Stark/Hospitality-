"""Shared page shell: page config, CSS, top pill nav, sidebar controls, error banners, name resolution."""

from __future__ import annotations

import base64
import functools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import streamlit as st

from . import access, auth, config, data, i18n, nav, platform, portal, tenancy, theme, tour, wake
from .api_client import ApiError
from .config import current_settings

PAGES = access.HOTEL_PAGES  # kept for older imports


def setup(page_file: str, title: str, *, employee: bool = False) -> None:
    """Every page starts here: tenant, CSS, access check, top bar, sidebar, tour."""
    _wake()
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
    who = ""
    if u and config.is_super():  # hotel portal: the signed-in user is shown in the sidebar (a calmer top bar)
        who = f'<span class="ss-userchip">{theme.icon("user", 14)}{theme.esc(u["username"])} · {theme.esc(auth.ROLES[u["role"]].split(" (")[0])}</span>'
    if config.is_super():
        where, cls = "", "ss-topbar ss-super"
    else:
        where, cls = "", "ss-topbar ss-hotel"
        if t.get("id"):
            where += f'<span class="ss-poweredby">{portal.hoi_mark(20)}HOI</span>'
    st.markdown(
        f'<div class="{cls}">{portal.brand_html(t)}<div class="ss-util">{who}{where}</div></div>',
        unsafe_allow_html=True,
    )
    nav = st.session_state.get("_nav") or access.HOTEL_PAGES
    if config.is_super() or len(nav) <= 1:
        _flat_nav(nav, page_file, u)
    else:
        _section_nav(nav, page_file, u)


def _wake() -> None:
    """'Waking up the server…' while a sleeping API starts (inside the page: never before st.navigation, see wake.warm)."""
    wake.ensure_awake(platform.mode())
    if auth.current() and not config.is_super() and not current_settings().use_mocks:
        wake.ensure_awake(current_settings().api_base_url)


def _link(f: str, label: str, icon: str | None = None) -> None:
    st.page_link(st.session_state.get("_page_by_file", {}).get(f, f), label=label, icon=icon)  # Page objects: robust deep links


def _signout(col) -> None:
    with col:
        if st.button(i18n.t("Sign out"), key="signout", type="tertiary"):
            auth.logout()
            st.rerun()


def _flat_nav(nav: list, page_file: str, u: dict | None) -> None:
    """Super-admin portal (four pages) and single-page states: one pill row."""
    with st.container(key="ss_nav"):
        cols = st.columns(len(nav) + (1 if u else 0), gap="small")
        for col, (f, label, _ic) in zip(cols, nav):
            with col:
                if f == page_file:
                    st.markdown(f'<div class="ss-navactive">{label}</div>', unsafe_allow_html=True)
                else:
                    _link(f, label)
        if u:
            _signout(cols[-1])


def _section_nav(nav: list, page_file: str, u: dict | None) -> None:
    """Hotel portal: at most five sections on top; the active section's pages underneath (only when it has more than one)."""
    secs = access.sections(nav)
    active = access.section_of(page_file) or (secs[0][0] if secs else None)
    with st.container(key="ss_nav"):
        cols = st.columns(len(secs) + (2 if u else 0), gap="small")
        for col, (name, ic, pages) in zip(cols, secs):
            with col:
                if name == active:
                    st.markdown(f'<div class="ss-navactive">{theme.esc(i18n.t(name))}</div>', unsafe_allow_html=True)
                else:
                    _link(pages[0][0], i18n.t(name), ic)
        if u:
            with cols[-2]:
                i18n.toggle()  # English / हिंदी for Today and this menu
            _signout(cols[-1])
    sub = next((pages for name, _, pages in secs if name == active), [])
    sub = [p for p in sub if p[0] not in access.HIDDEN_IN_NAV or p[0] == page_file]
    if len(sub) > 1:
        with st.container(key="ss_subnav"):
            scols = st.columns(len(sub), gap="small")
            for col, (f, label, _ic) in zip(scols, sub):
                with col:
                    label = i18n.t("Overview" if label == active else label)  # the section tab above already says "Today"
                    if f == page_file:
                        st.markdown(f'<div class="ss-subactive">{theme.esc(label)}</div>', unsafe_allow_html=True)
                    else:
                        _link(f, label)


def _sidebar(t: dict, u: dict | None) -> None:
    s = current_settings()
    with st.sidebar:
        if config.is_super():  # platform console: no hotel workspace, no scoring week
            html(
                f'<div class="ss-card" style="padding:12px 14px"><div style="color:#6b6a65;font-size:.75rem">Portal</div>'
                f"<b>HOI Platform Admin</b><div style='font-size:.8rem;margin-top:6px'>Hotel sign-in: "
                f"{portal.link(config.hotel_portal_url())}</div></div>"
            )
            if st.button("Refresh", icon=":material/refresh:", width="stretch"):
                data.clear()
                st.rerun()
            return
        if u and u["role"] == "platform_admin":
            try:
                ts = [x for x in platform.tenants() if x["status"] == "active"]
            except platform.PlatformError:
                ts = []
            ids = [x["id"] for x in ts]
            if ids:
                pick = st.selectbox(
                    "Hotel",
                    ids,
                    index=ids.index(t["id"]) if t["id"] in ids else 0,
                    format_func=lambda i: next(x["name"] for x in ts if x["id"] == i),
                    key="ws_pick",
                )
                if pick != t["id"]:
                    auth.open_workspace(pick)  # recorded in the activity log server-side
                    tenancy.on_tenant_change()
                    st.rerun()
            if st.button("Back to all hotels", icon=":material/logout:", width="stretch", key="imp_exit_sb"):
                portal.exit_hotel()
        else:
            html(
                f'<div class="ss-card" style="padding:12px 14px"><div style="color:#6b6a65;font-size:.75rem">Signed in</div>'
                f"<b>{theme.esc(u['username'] if u else '')}</b> · {theme.esc(auth.ROLES.get((u or {}).get('role'), '').split(' (')[0])}"
                f'<div style="color:#6b6a65;font-size:.8rem;margin-top:4px">{theme.esc(t["name"])}</div></div>'
            )
        anchor = None if tenancy.is_homestay() else ensure_demo_week()  # homestay: no scoring week, no risk model
        if anchor:
            opts = data.week_options(anchor)
            cur = st.session_state.get("week_start", anchor)
            st.selectbox(
                "Week (starts Monday)",
                opts,
                index=opts.index(cur) if cur in opts else 0,
                key="week_start",
                format_func=week_label,
                help="The week shown on the check-in, person and week-numbers pages. The demo hotel's weeks are synthetic.",
            )
            if s.use_mocks and st.session_state.get("week_start") != anchor:
                st.caption("Practice data has only one week.")
        c1, c2 = st.columns(2)
        if c1.button("Refresh", icon=":material/refresh:", width="stretch"):
            data.clear()
            st.rerun()
        if t.get("is_demo") and not tenancy.is_homestay() and (u is None or u["role"] in ("owner", "platform_admin")):
            if c2.button("Tour", icon=":material/explore:", width="stretch"):
                tour.start()


def week_label(w: str | None) -> str:
    """'2029-12-24' -> 'Demo week: Mon 24 Dec' for the synthetic demo data, else 'Week of Mon 24 Dec'."""
    from datetime import date

    try:
        d = date.fromisoformat(str(w))
    except ValueError:
        return str(w)
    demo = bool(tenancy.active().get("is_demo")) or current_settings().use_mocks
    return f"Demo week: {d.strftime('%a %d %b')}" if demo else f"Week of {d.strftime('%a %d %b')}"


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
        with st.expander("More detail (for support)"):
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
    html('<div class="ss-footer"><span>HOI · hotel admin</span></div>')


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
            f"<b>This is not switched on yet.</b> {theme.esc(what).capitalize()} needs an update on the server. "
            "Ask your HOI contact, then press Refresh.",
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


# ------------------------------------------------------------------ simple-page building blocks (summary first)
def property_picker(key: str = "prop_pick", label: str = "Property") -> None:
    """Switch between the group's properties (only shown when there is more than one). The mode follows the property."""
    props = tenancy.properties()
    if len(props) < 2:
        return
    ids = [p["id"] for p in props]
    cur = tenancy.property_id()
    names = {p["id"]: f"{p['name']} · {'homestay' if p.get('mode') == 'homestay' else 'hotel'}" for p in props}
    pick = st.selectbox(label, ids, index=ids.index(cur) if cur in ids else 0, format_func=names.get, key=key)
    if pick != cur:
        tenancy.set_property(pick)
        data.clear()
        st.rerun()


def page_head(title: str, sub: str = "") -> None:
    """Plain page title + one line of meaning."""
    html(f'<div class="ss-phead"><h1>{theme.esc(title)}</h1>' + (f"<p>{theme.esc(sub)}</p>" if sub else "") + "</div>")


def big_numbers(items: list[tuple[str, Any, str, str]]) -> None:
    """Big numbers with one-line meanings: (label, value, meaning, tone in ok|warn|bad|info)."""
    cells = "".join(
        f'<div class="ss-big {theme.esc(tone)}"><div class="v">{theme.esc(v)}</div><div class="l">{theme.esc(label)}</div>'
        f'<div class="m">{theme.esc(meaning)}</div></div>'
        for label, v, meaning, tone in items
    )
    cls = "ss-bigs n4" if len(items) in (4, 7, 8) else "ss-bigs"
    html(f'<div class="{cls}">{cells}</div>')


def takeaway(text: str) -> None:
    """The one-line plain takeaway shown above a chart."""
    html(f'<div class="ss-takeaway">{theme.icon("info", 16)}<span>{theme.esc(text)}</span></div>')


def table(df, main: list[str], *, key: str, height: int | None = None, column_config: dict | None = None) -> None:
    """A table with only the main columns; technical columns behind a 'Details' toggle."""
    import pandas as pd  # local: keeps lib.ui import light

    if not isinstance(df, pd.DataFrame) or df.empty:
        empty("Nothing to show yet.")
        return
    extra = [c for c in df.columns if c not in main]
    show_all = bool(extra) and st.toggle("More columns", key=f"{key}_details", help="Show all columns")
    cols = [c for c in df.columns if c in main or show_all]
    kw = {"height": height} if height else {}
    st.dataframe(df[cols], hide_index=True, width="stretch", column_config=column_config or {}, **kw)


# ------------------------------------------------------------------ owner-first building blocks (answer first, one action per card)
def verdict(problems: int, ok_text: str = "Yes, everything looks fine today.", bad_text: str | None = None) -> None:
    """The one-line answer at the top of a page: green when nothing needs the owner, amber otherwise."""
    if problems:
        text = bad_text or f"{problems} thing{'s' if problems != 1 else ''} need{'s' if problems == 1 else ''} you today."
        html(f'<div class="ss-verdict warn">{theme.icon("alert", 22)}<span>{theme.esc(text)}</span></div>')
    else:
        html(f'<div class="ss-verdict ok">{theme.icon("check", 22)}<span>{theme.esc(ok_text)}</span></div>')


def tile_skeleton(n: int) -> str:
    """Grey placeholder tiles with the same size as the real ones (keeps the page from jumping while data loads)."""
    cells = "".join(
        '<div class="ss-big skel"><div class="v">…</div><div class="l">Loading</div><div class="m">&nbsp;</div></div>' for _ in range(n)
    )
    return f'<div class="ss-bigs ss-acts n{n}">{cells}</div>'


def action_tiles(items: list[dict], key: str = "acts") -> None:
    """Big-number tiles, each with ONE action button underneath.

    item = {label, value, meaning, tone (ok|warn|bad|info), button, target (page file | callable | None), key}
    A page target is skipped (button hidden) when that page is not in this user's navigation."""
    visible = {f for f, _, _ in st.session_state.get("_nav", [])}
    with st.container(key=f"ss_{key}"):
        cols = st.columns(len(items), gap="small")
        for col, it in zip(cols, items):
            with col:
                html(
                    f'<div class="ss-big act {theme.esc(it.get("tone", "info"))}"><div class="v">{theme.esc(it["value"])}</div>'
                    f'<div class="l">{theme.esc(it["label"])}</div><div class="m">{theme.esc(it.get("meaning", ""))}</div></div>'
                )
                tgt = it.get("target")
                if not it.get("button") or tgt is None or (isinstance(tgt, str) and tgt not in visible):
                    html('<div class="ss-actpad"></div>')
                    continue
                if st.button(it["button"], key=f"{key}_{it.get('key', it['label'])}", width="stretch", type=it.get("type", "secondary")):
                    if isinstance(tgt, str):
                        st.switch_page(nav.page(tgt))
                    try:
                        tgt()
                        st.toast("Done")
                    except platform.PlatformError as e:
                        st.toast(e.message)
                    data.clear()
                    st.rerun()


def details(label: str = "Details") -> Any:
    """Expander that holds the older, more technical view of a section."""
    return st.expander(label, icon=":material/info:")


def simple_bars(
    labels: list[str],
    values: list[float],
    *,
    highlight: int | None = None,
    fmt: str = "{:.0f}",
    height: int = 220,
    hover: str = "%{x}: %{y}",
    y_max: float | None = None,
) -> None:
    """One simple bar chart (one colour; the bar the takeaway talks about is darker and labelled). No legend, no gridlines."""
    import plotly.graph_objects as go  # local: keeps lib.ui import light

    base, strong = "#9cc3f0", "#1f6fe5"
    colors = [strong if i == highlight else base for i in range(len(values))]
    text = [fmt.format(v) if (highlight is None or i == highlight) else "" for i, v in enumerate(values)]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker=dict(color=colors, cornerradius=4, line=dict(color="#fff", width=2)),
            text=text,
            textposition="outside",
            cliponaxis=False,
            hovertemplate=hover + "<extra></extra>",
        )
    )
    theme.style_fig(fig, height, legend=False)
    fig.update_yaxes(showgrid=False, showticklabels=False, rangemode="tozero", **({"range": [0, y_max]} if y_max else {}))
    fig.update_layout(margin=dict(t=24, b=8, l=8, r=8), bargap=0.35)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "staticPlot": False})


ACTION_WORDS = {  # activity-log codes -> plain words (unknown codes fall back to the code with spaces)
    "login.ok": "Signed in",
    "login.demo": "Signed in (demo account)",
    "login.failed": "Sign-in failed",
    "platform.open_workspace": "HOI team opened this hotel",
    "platform.tenant_created": "Hotel added",
    "platform.tenant_updated": "Hotel settings changed",
    "platform.tenant_deleted": "Hotel removed",
    "platform.invite": "Owner invite made",
    "invite.created": "Invite made",
    "invite.redeemed": "Invite used (new account)",
    "user.created": "Account added",
    "user.disabled": "Account switched off",
    "user.enabled": "Account switched on",
    "staff.imported": "Staff list added",
    "workspace.updated": "Hotel settings changed",
    "property.added": "Building added",
    "property.settings": "Building settings changed",
    "hotel_profile.updated": "Hotel profile changed",
    "job.created": "Job made",
    "job.accepted": "Job taken",
    "job.done": "Job done",
    "job.inspected": "Room checked",
    "job.manual_offer": "Job sent to a person by hand",
    "job.retry": "Job sent again",
    "dispatch.reset": "Jobs cleared (demo)",
    "guest.express_checkout": "Guest booked a checkout",
    "guest.express_checkout_released": "Checkout room released",
    "guest.feedback": "Guest left a rating",
    "guest.late_checkout_requested": "Guest asked for late checkout",
    "guest.urgent_alert": "Guest sent an urgent alert",
    "inv.issue": "Stock given out",
    "inv.item_added": "Stock item added",
    "inv.request": "Stock asked for",
    "inv.reject": "Stock request turned down",
    "count.posted": "Stock count saved",
    "po.created": "Order made",
    "po.received": "Order delivered",
    "staffing.requested": "Extra staff asked for",
    "staffing.sent": "Extra staff request sent",
    "voice.report_issue": "Voice note problem reported",
    "retention.cover_checked": "Cover for a day off checked",
}


def action_label(code: str | None) -> str:
    c = str(code or "")
    if c in ACTION_WORDS:
        return ACTION_WORDS[c]
    if c.startswith("guest.late_checkout_"):
        return "Late checkout " + c.rsplit("_", 1)[-1]
    return c.replace(".", " · ").replace("_", " ").capitalize()
