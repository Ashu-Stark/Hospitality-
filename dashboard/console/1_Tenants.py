import pandas as pd
import streamlit as st

from lib import access, auth, nav, platform, tenancy, theme, ui
from lib.config import DEFAULT_API

ui.setup("console/1_Tenants.py", "Hotels")
ui.html(
    theme.hero(
        "Hotel groups on HOI",
        "Onboard a hotel group, set its plan and modules, hand the owner a one-time invite, and "
        "suspend or reactivate access. Every action here is audited.",
        eyebrow="Platform console",
        variant="dark",
    )
)

ts = ui.safe(platform.tenants, what="load hotel groups") or []
ui.html(
    theme.tiles(
        [
            theme.tile("Hotel groups", str(len(ts)), f"{sum(1 for t in ts if t['status'] != 'suspended')} active", "home"),
            theme.tile("Properties", str(sum(t["counts"]["properties"] for t in ts)), "across all groups", "bed"),
            theme.tile("Users", str(sum(t["counts"]["users"] for t in ts)), "hotel accounts", "users"),
            theme.tile("Dispatched jobs", str(sum(t["counts"]["jobs"] for t in ts)), "all time", "check"),
        ]
    )
)

# ------------------------------------------------------------------ onboard
ui.html(theme.section("Onboard a hotel group", "New customer"))
with st.form("onboard", clear_on_submit=True):
    c1, c2, c3 = st.columns([2, 1, 1])
    name = c1.text_input("Hotel group name", placeholder="Garhwal Heritage Hotels")
    plan = c2.selectbox("Plan", list(tenancy.PLANS), format_func=lambda p: tenancy.PLANS[p]["label"], index=1)
    color = c3.color_picker("Brand color", "#1f6fe5")
    c4, c5 = st.columns(2)
    pname = c4.text_input("First property", placeholder="Mussoorie Ridge Resort")
    rooms = c5.number_input("Rooms", 1, 3000, 40)
    data_src = st.radio("Data source", ["Demo data", "Their own HOI ML backend"], horizontal=True)
    url = st.text_input("ML backend URL", value=DEFAULT_API)
    go = st.form_submit_button("Create hotel group and owner invite", type="primary")
if go:
    res = ui.safe(
        platform.create_tenant,
        name=name,
        plan=plan,
        brand_color=color,
        use_mocks=data_src == "Demo data",
        api_base_url=url.rstrip("/"),
        first_property=pname or None,
        rooms=int(rooms),
        what="create the hotel group",
    )
    if res:
        st.session_state["new_invite"] = (res["tenant"]["name"], res["owner_invite"]["code"])
        st.rerun()
if inv := st.session_state.get("new_invite"):
    ui.html(
        theme.banner(
            f"<b>{theme.esc(inv[0])}</b> created. Send the owner this one-time invite code: "
            f"<code style='font-size:1.1rem'>{inv[1]}</code>. They sign up under <i>Join with invite code</i> and finish "
            "setup (staff import, team invites) themselves.",
            "blue",
            "check",
        )
    )

# ------------------------------------------------------------------ manage
ui.html(theme.section("All hotel groups", "Manage"))
for t in ts:
    c = t["counts"]
    suspended = t["status"] == "suspended"
    with st.container(key=f"card_t_{t['id']}"):
        a, b = st.columns([2.2, 2])
        with a:
            ui.html(
                f'<div class="ss-person"><span class="ss-brand-mark" style="background:{theme.esc(t["brand_color"])}">{theme.esc(t["name"][:1])}</span>'
                f'<div><b style="font-size:1.05rem">{theme.esc(t["name"])}</b> '
                + (theme.band_chip("high", "suspended") if suspended else theme.band_chip("low", "active"))
                + (' <span class="ss-tag">demo</span>' if t["is_demo"] else "")
                + f'<div style="color:#6b6a65;font-size:.8rem;margin-top:4px">{tenancy.PLANS.get(t["plan"], {}).get("label", t["plan"])} · '
                f"{c['properties']} properties · {c['staff']} staff · {c['users']} users · {c['jobs']} jobs · "
                f"{'demo data' if t['use_mocks'] else theme.esc(t.get('api_base_url') or '')} · "
                f"{'onboarded' if t['onboarded'] else 'setup step ' + str(t['onboarding_step']) + '/5'}</div></div></div>"
            )
        with b:
            x1, x2, x3 = st.columns(3)
            new_plan = x1.selectbox(
                "Plan",
                list(tenancy.PLANS),
                index=list(tenancy.PLANS).index(t["plan"]),
                format_func=lambda p: tenancy.PLANS[p]["label"],
                key=f"plan_{t['id']}",
                label_visibility="collapsed",
            )
            if new_plan != t["plan"]:
                ui.safe(platform.update_tenant, t["id"], plan=new_plan, what="change the plan")
                st.rerun()
            if not t["is_demo"] and x2.button("Reactivate" if suspended else "Suspend", key=f"sus_{t['id']}", width="stretch"):
                ui.safe(platform.update_tenant, t["id"], status="active" if suspended else "suspended", what="change status")
                st.rerun()
            if x3.button("Open", key=f"open_{t['id']}", type="primary", width="stretch", disabled=suspended):
                auth.open_workspace(t["id"])
                tenancy.on_tenant_change()
                st.switch_page(nav.page("home.py"))
        with st.expander("Modules and owner invite"):
            picked = st.multiselect(
                "Enabled modules",
                list(access.MODULE_PAGES),
                default=t["modules"],
                format_func=access.MODULE_LABELS.get,
                key=f"mods_{t['id']}",
            )
            m1, m2 = st.columns(2)
            if m1.button("Save modules", key=f"savem_{t['id']}"):
                if ui.safe(platform.update_tenant, t["id"], settings={**t["settings"], "modules": picked}, what="save modules"):
                    st.toast("Modules saved")
            if m2.button("New owner invite code", key=f"inv_{t['id']}"):
                inv = ui.safe(platform.platform_invite, t["id"], "owner", what="create the invite")
                if inv:
                    st.code(inv["code"])

rows = [{"Hotel group": t["name"], "Plan": t["plan"], "Status": t["status"], **t["counts"], "Created": t["created_at"][:10]} for t in ts]
if rows:
    st.download_button(
        "Export hotel list (CSV)", pd.DataFrame(rows).to_csv(index=False).encode(), "hoi_hotels.csv", icon=":material/download:"
    )
ui.footer()
