"""Portal-specific chrome: the super-admin portal (navy, "Platform admin") and the hotel admin portal (hotel brand).

Both portals run from the same code; lib.config.portal() decides which one this process is (ADMIN_PORTAL).
"""

from __future__ import annotations

import base64
import functools
from pathlib import Path
from urllib.parse import urlencode

import streamlit as st

from . import access, auth, config, nav, platform, tenancy, theme

NAVY = "#0f1f3d"

SUPER_CSS = f"""<style>
.stApp {{ border-top: 6px solid {NAVY}; }}
.ss-topbar.ss-super {{ background:{NAVY}; color:#fff; border-radius:22px; padding:12px 18px; }}
.ss-topbar.ss-super .ss-brand, .ss-topbar.ss-super .ss-util {{ color:#fff; }}
.ss-topbar.ss-super .ss-brand-mark {{ background:#2a4a8a !important; }}
.ss-topbar.ss-super .ss-brand-long {{ color:rgba(255,255,255,.72); }}
.ss-hero.dark {{ background: radial-gradient(120% 140% at 90% 0%, #3d5f9e 0%, #1b315e 50%, #0b1630 100%); }}
.ss-topbar.ss-super .ss-userchip {{ color:#fff; }}
.ss-topbar.ss-super .ss-mode {{ border-color:rgba(255,255,255,.7); }}
.ss-portal-badge {{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:4px 10px; font-size:.72rem;
  font-weight:600; letter-spacing:.06em; text-transform:uppercase; white-space:nowrap; }}
.ss-super .ss-portal-badge {{ background:#e6edff; color:{NAVY}; }}
.ss-navactive {{ background:{NAVY} !important; }}
.ss-hoi-mark {{ border-radius:11px; display:block; flex:none; }}
</style>"""

HOTEL_CSS = """<style>
.ss-portal-badge { display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:4px 10px; font-size:.72rem;
  font-weight:600; letter-spacing:.06em; text-transform:uppercase; white-space:nowrap; background:var(--brand); color:#fff; }
.ss-hotel-logo { height:44px; width:auto; display:block; }
.ss-hoi-mark { border-radius:11px; display:block; flex:none; }
.ss-poweredby { display:inline-flex; align-items:center; gap:6px; text-transform:none; letter-spacing:0; font-size:.78rem; color:var(--muted); }
.ss-poweredby img { border-radius:6px; }
.ss-imp { display:flex; align-items:center; gap:10px; background:#fff4e0; border:1.5px solid #d48a00; color:#5a3b00;
  border-radius:16px; padding:10px 14px; font-size:.9rem; }
</style>"""


def css() -> str:
    return SUPER_CSS if config.is_super() else HOTEL_CSS


def brand_color(t: dict) -> str:
    return NAVY if config.is_super() else t["brand_color"]


def logo_src(t: dict) -> str | None:
    """The hotel's logo (tenant or hotel profile `logo_url`), served by the platform API. None -> show the name."""
    url = str(t.get("logo_url") or "")
    if url.startswith("https://"):
        return url
    return platform.asset_data_uri(url) if url.startswith("/") else None


BRAND_DIR = Path(__file__).resolve().parent.parent / "static" / "brand"


@functools.cache
def hoi_mark_uri() -> str:
    """The HOI platform logo (blue-violet tile, white mountain-wave mark) as a data: URI."""
    try:
        return "data:image/svg+xml;base64," + base64.b64encode((BRAND_DIR / "hoi-mark.svg").read_bytes()).decode()
    except OSError:
        return ""


def hoi_mark(size: int = 36) -> str:
    uri = hoi_mark_uri()
    if not uri:
        return f'<span class="ss-brand-mark">{theme.icon("shield", 20, "#fff")}</span>'
    return f'<img class="ss-hoi-mark" src="{uri}" alt="HOI" width="{size}" height="{size}">'


def page_icon() -> str:
    """Browser-tab icon for both portals (the HOI logo PNG)."""
    p = BRAND_DIR / "hoi-icon-32.png"
    return str(p) if p.exists() else ":material/hotel:"


def brand_html(t: dict) -> str:
    """Left side of the top bar. HOI mark = platform brand; a hotel's own logo stays the hotel brand on its pages."""
    if config.is_super():
        return (
            f'<div class="ss-brand">{hoi_mark()}'
            '<span>HOI <span class="ss-brand-long">Platform Admin</span></span>'
            f'<span class="ss-portal-badge">{theme.icon("shield", 13)}Platform admin</span></div>'
        )
    if t.get("id"):
        props = tenancy.properties()
        prop = tenancy.current_property() or {}
        other = len(props) > 1 and prop.get("id") != props[0]["id"]  # a second property (e.g. the homestay): its own name, no group logo
        src = None if other else logo_src(t)
        name = prop.get("name") if other else t["name"]
        mark = (
            f'<img class="ss-hotel-logo" src="{theme.esc(src)}" alt="{theme.esc(name)}">'
            if src
            else f'<span class="ss-brand-mark" style="background:var(--brand)">{theme.icon("bed", 20, "#fff")}</span>'
            f"<span>{theme.esc(name)}</span>"
        )
        badge = "Homestay" if tenancy.is_homestay() else "Hotel admin"
        return f'<div class="ss-brand">{mark}<span class="ss-portal-badge">{badge}</span></div>'
    return f'<div class="ss-brand">{hoi_mark()}<span>HOI <span style="font-weight:500">Hotel Admin</span></span></div>'


def link(url: str) -> str:
    return f'<a href="{theme.esc(url)}" target="_blank" rel="noopener">{theme.esc(url)}</a>'


# ------------------------------------------------------------------ super-admin portal: hotels open in the hotel portal
def hotel_portal_link(tid: str | None = None) -> str:
    base = config.hotel_portal_url() + "/"
    return base + ("?" + urlencode({"hotel": tid}) if tid else "")


def open_hotel_help() -> None:
    """One-line instructions above a list of "Open in hotel portal" buttons (super-admin portal)."""
    st.markdown(
        theme.banner(
            f"<b>To open a hotel</b>, go to {link(config.hotel_portal_url())}, sign in with your HOI team account and pick the "
            "hotel. This is saved in the activity log.",
            "blue",
            "info",
        ),
        unsafe_allow_html=True,
    )


def open_hotel_control(container, tid: str, *, disabled: bool = False, key: str | None = None) -> None:
    """Super-admin portal: a link to the hotel portal (the admin signs in there and chooses the hotel).
    Hotel portal: the in-app audited impersonation (open_workspace)."""
    if config.is_super():
        container.link_button(
            "Open hotel",
            hotel_portal_link(tid),
            type="primary",
            icon=":material/open_in_new:",
            width="stretch",
            disabled=disabled,
            help="Opens the hotel sign-in in a new tab. Sign in with your HOI team account and pick this hotel. This is logged.",
        )
        return
    if container.button("Open this hotel", key=key, type="primary", icon=":material/login:", width="stretch", disabled=disabled):
        open_hotel(tid)


def open_hotel(tid: str) -> None:
    auth.open_workspace(tid)  # audited server-side
    tenancy.on_tenant_change()
    st.session_state.pop("want_hotel", None)
    st.switch_page(nav.page("home.py"))  # app.py registers Home while the picker is shown


def exit_hotel() -> None:
    auth.exit_workspace()
    st.switch_page(nav.page(access.PICK_PAGE[0]))  # app.py registers the picker while a hotel is open


# ------------------------------------------------------------------ hotel portal: platform admin viewing a hotel
def impersonation_banner(t: dict) -> None:
    u = auth.current() or {}
    a, b = st.columns([5, 1], vertical_alignment="center")
    a.markdown(
        f'<div class="ss-imp">{theme.icon("shield", 18)}<span><b>Viewing as HOI team.</b> '
        f"You ({theme.esc(u.get('username', ''))}) are inside <b>{theme.esc(t['name'])}</b>. What you do here is saved in "
        "the activity log.</span></div>",
        unsafe_allow_html=True,
    )
    if b.button("Exit", key="imp_exit", icon=":material/logout:", width="stretch", help="Close this hotel and choose another"):
        exit_hotel()
