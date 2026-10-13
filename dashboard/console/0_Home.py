"""Super-admin portal home: a short summary of the platform and shortcuts to the console pages."""

import streamlit as st

from lib import config, platform, portal, theme, ui

ui.setup("console/0_Home.py", "Home")
ui.page_head("Home", "All hotels at a glance.")

ts = ui.safe(platform.tenants, what="load the hotels") or []
active = [t for t in ts if t["status"] != "suspended"]
setting_up = [t for t in ts if not t["onboarded"] and t["status"] != "suspended"]
ui.verdict(
    len(setting_up),
    ok_text="The active hotel is set up and running." if len(active) == 1 else f"All {len(active)} active hotels are set up and running.",
    bad_text=f"{len(setting_up)} hotel{'s are' if len(setting_up) != 1 else ' is'} still setting up: "
    + ", ".join(t["name"] for t in setting_up[:3])
    + (" …" if len(setting_up) > 3 else "")
    + ".",
)
ui.html(
    theme.tiles(
        [
            theme.tile("Hotels", str(len(ts)), f"{len(active)} active · {len(ts) - len(active)} paused", "home"),
            theme.tile("Buildings", str(sum(t["counts"]["properties"] for t in ts)), "across all hotels", "bed"),
            theme.tile("Staff", str(sum(t["counts"]["staff"] for t in ts)), "across all hotels", "users"),
            theme.tile("Still setting up", str(sum(1 for t in ts if not t["onboarded"])), "hotels not finished", "flag"),
        ]
    )
)

c1, c2 = st.columns([1.4, 1])
with c1:
    ui.html(theme.section("Recent activity", "Activity log"))
    rows = (ui.safe(platform.platform_audit, None, 8, what="load the activity log") or [])[:8]
    names = {t["id"]: t["name"] for t in ts}
    if rows:
        st.dataframe(
            [
                {
                    "When": r["at"][:16].replace("T", " "),
                    "Hotel": names.get(r["tenant_id"], "platform"),
                    "User": r["actor"],
                    "What happened": ui.action_label(r["action"]),
                }
                for r in rows
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        ui.empty("Nothing in the activity log yet.")
with c2:
    ui.html(theme.section("Hotel sign-in", "Where hotel teams work"))
    ui.html(
        f'<div class="ss-card">Owners, managers and staff sign in at '
        f"<b>{portal.link(config.hotel_portal_url())}</b>.<div style='color:#6b6a65;font-size:.85rem;margin-top:8px'>"
        "To look inside a hotel, sign in there with your HOI team account and pick the hotel. This is saved in the "
        "activity log, and a banner shows on every page.</div></div>"
    )
    st.link_button("Open the hotel sign-in", portal.hotel_portal_link(), icon=":material/open_in_new:", width="stretch")
ui.footer()
