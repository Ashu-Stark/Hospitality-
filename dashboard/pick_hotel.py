"""Hotel admin portal, platform admins only: choose the hotel to open (audited impersonation)."""

import streamlit as st

from lib import config, platform, portal, tenancy, theme, ui

ui.setup("pick_hotel.py", "Choose a hotel")
ui.html(
    theme.hero(
        "Choose a hotel to open",
        "You are signed in with an HOI team account. Pick a hotel below. Opening a hotel is saved in the activity log, "
        "and you can come back here at any time.",
        eyebrow="HOI team",
        variant="dark",
    )
)
ui.html(
    theme.banner(
        f"To add, change or pause hotels, use the HOI team console: {portal.link(config.super_portal_url())}",
        "gray",
        "info",
    )
)

ts = ui.safe(platform.tenants, what="load the hotels") or []
want = st.session_state.get("want_hotel")
ts.sort(key=lambda t: (t["id"] != want, t["status"] == "suspended", t["name"].lower()))
if not ts:
    ui.empty("No hotels yet. Add one in the HOI team console.")
for t in ts:
    suspended = t["status"] == "suspended"
    c = t.get("counts") or {}
    with st.container(key=f"card_pick_{t['id']}"):
        a, b = st.columns([4, 1], vertical_alignment="center")
        a.markdown(
            f'<div class="ss-person"><span class="ss-brand-mark" style="background:{theme.esc(t["brand_color"])}">{theme.esc(t["name"][:1])}</span>'
            f'<div><b style="font-size:1.05rem">{theme.esc(t["name"])}</b> '
            + (theme.band_chip("high", "paused") if suspended else theme.band_chip("low", "active"))
            + (' <span class="ss-tag">practice</span>' if t.get("is_demo") else "")
            + (' <span class="ss-tag">picked in the console</span>' if t["id"] == want else "")
            + f'<div style="color:#6b6a65;font-size:.8rem;margin-top:4px">{theme.esc(tenancy.PLANS.get(t["plan"], {}).get("label", t["plan"]))}'
            f" · {c.get('properties', 0)} buildings · {c.get('staff', 0)} staff · {c.get('users', 0)} users</div></div></div>",
            unsafe_allow_html=True,
        )
        if b.button(
            "Open this hotel",
            key=f"pick_{t['id']}",
            type="primary" if t["id"] == want or (not want and t.get("is_demo")) else "secondary",
            icon=":material/login:",
            width="stretch",
            disabled=suspended,
            help="Turn it back on in the HOI team console first" if suspended else "This is saved in the activity log",
        ):
            portal.open_hotel(t["id"])
ui.footer()
