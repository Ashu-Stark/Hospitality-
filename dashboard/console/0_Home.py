"""Super-admin portal home: a short summary of the platform and shortcuts to the console pages."""

import streamlit as st

from lib import config, nav, platform, portal, theme, ui

ui.setup("console/0_Home.py", "Home")
ui.html(
    theme.hero(
        "HOI platform console",
        "Onboard hotel groups, set plans and modules, follow how each hotel uses HOI, and review the audit log. Hotel teams work "
        "in the separate hotel admin portal.",
        eyebrow="Platform admin",
        variant="dark",
    )
)

ts = ui.safe(platform.tenants, what="load hotel groups") or []
active = [t for t in ts if t["status"] != "suspended"]
ui.html(
    theme.tiles(
        [
            theme.tile("Hotel groups", str(len(ts)), f"{len(active)} active · {len(ts) - len(active)} suspended", "home"),
            theme.tile("Properties", str(sum(t["counts"]["properties"] for t in ts)), "across all groups", "bed"),
            theme.tile("Staff", str(sum(t["counts"]["staff"] for t in ts)), "on hotel rosters", "users"),
            theme.tile("Setup pending", str(sum(1 for t in ts if not t["onboarded"])), "groups still onboarding", "flag"),
        ]
    )
)

quick = [p for p in st.session_state.get("_nav", []) if p[0] != "console/0_Home.py"]
with st.container(key="ss_quick"):
    for col, (f, label, ic) in zip(st.columns(max(len(quick), 1)), quick):
        with col:
            st.page_link(nav.page(f), label=label, icon=ic)
ui.html("""<style>
.st-key-ss_quick { background:#fff; border-radius:22px; padding:16px 10px; margin-top:12px; }
.st-key-ss_quick [data-testid="stPageLink-NavLink"] { flex-direction:column; gap:8px; align-items:center; text-align:center; border-radius:16px; padding:8px 4px; }
.st-key-ss_quick [data-testid="stPageLink-NavLink"]:hover { background:#f4f4f2; }
.st-key-ss_quick [data-testid="stPageLink-NavLink"] span[data-testid="stIconMaterial"] { display:flex !important; align-items:center; justify-content:center;
  width:48px !important; min-width:48px; height:48px; border-radius:999px; background:#e6edff; color:#0f1f3d; font-size:24px !important; }
</style>""")

c1, c2 = st.columns([1.4, 1])
with c1:
    ui.html(theme.section("Recent activity", "Audit log"))
    rows = (ui.safe(platform.platform_audit, None, 8, what="load the audit log") or [])[:8]
    names = {t["id"]: t["name"] for t in ts}
    if rows:
        st.dataframe(
            [
                {
                    "When": r["at"][:16].replace("T", " "),
                    "Hotel": names.get(r["tenant_id"], "platform"),
                    "User": r["actor"],
                    "Action": r["action"],
                }
                for r in rows
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        ui.empty("No audit entries yet.")
with c2:
    ui.html(theme.section("Hotel admin portal", "Where hotel teams work"))
    ui.html(
        f'<div class="ss-card">Owners, HR, department heads, storekeepers and employees sign in at '
        f"<b>{portal.link(config.hotel_portal_url())}</b>.<div style='color:#6b6a65;font-size:.85rem;margin-top:8px'>"
        "To look inside a hotel, sign in there with your platform account and choose the hotel. That access is audited "
        "and shows a banner on every page.</div></div>"
    )
    st.link_button("Open the hotel admin portal", portal.hotel_portal_link(), icon=":material/open_in_new:", width="stretch")
ui.footer()
