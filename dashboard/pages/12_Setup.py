import io
import random

import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import auth, dispatch, nav, platform, tenancy, theme, ui
from lib.config import DEFAULT_API, Settings, current_settings

ui.setup("pages/12_Setup.py", "Setup")
T = tenancy.refresh()
STEPS = ["Organization", "Property", "Staff", "Data source", "Team", "Done"]

ui.page_head("Settings", "How this property works, your thank-you budget, and the link to the tourism portal.")
IS_OWNER = auth.role() in ("owner", "platform_admin")
HOMESTAY = tenancy.is_homestay()
tab_prop, tab_ob, tab_team, tab_plan = st.tabs(["This property", "Setup steps", "Team & access", "Plan"])

# ------------------------------------------------------------------ this property: mode, budget, recognition, portal key
with tab_prop:
    ui.property_picker(key="prop_pick_settings", label="Property")
    P = tenancy.current_property()
    if not P:
        ui.empty("Add a property first (Setup steps).")
    else:
        with st.container(key="card_mode"):
            st.markdown("**How should the app look?**")
            choice = st.radio(
                "Mode",
                ["homestay", "hotel"],
                index=0 if P.get("mode") == "homestay" else 1,
                horizontal=True,
                format_func=lambda m: (
                    "Homestay: simple, only the basics" if m == "homestay" else "Hotel: everything (roster, analytics, dispatch)"
                ),
                disabled=not IS_OWNER,
                key="mode_pick",
            )
            st.caption("Small places (up to 10 rooms) start as a homestay. You can switch any time; no data is lost.")
            if choice != P.get("mode") and st.button("Switch mode", type="primary", key="act_mode", disabled=not IS_OWNER):
                if ui.safe(platform.update_property, P["id"], mode=choice, what="switch the mode"):
                    tenancy.refresh()
                    st.rerun()
        with st.container(key="card_budget"):
            st.markdown("**Thank-you budget (recognition)**")
            a, b = st.columns(2)
            cap = a.number_input(
                "Monthly budget (₹)", 0, 10_000_000, int(P.get("incentive_monthly_budget_cap") or 0), step=500, disabled=not IS_OWNER
            )
            board = b.toggle(
                "Show a team board to staff",
                value=bool(P.get("recognition_leaderboard_opt_in")),
                disabled=not IS_OWNER,
                help="Off by default: each person sees only their own points plus team totals.",
            )
            st.caption(
                "Points are positive only and never used for discipline. Each person's reward = their share of points × this budget (capped)."
            )
            if st.button("Save budget", key="act_budget", disabled=not IS_OWNER):
                if ui.safe(
                    platform.update_property,
                    P["id"],
                    incentive_monthly_budget_cap=int(cap),
                    recognition_leaderboard_opt_in=board,
                    what="save",
                ):
                    tenancy.refresh()
                    st.toast("Saved")
                    st.rerun()
        with st.container(key="card_portal"):
            st.markdown("**Uttarakhand tourism portal**")
            st.caption(
                ("A key is saved. " if P.get("portal_key_set") else "No key saved yet. ")
                + "Paste the business API key from your portal account so Extra staff requests can be sent. It is never shown again."
            )
            key = st.text_input("Portal API key", type="password", key="portal_key_in", disabled=not IS_OWNER)
            c1, c2 = st.columns(2)
            if c1.button("Save key", key="act_key", disabled=not IS_OWNER or not key.strip()):
                if ui.safe(platform.update_property, P["id"], portal_api_key=key.strip(), what="save the key"):
                    tenancy.refresh()
                    st.toast("Key saved")
                    st.rerun()
            if P.get("portal_key_set") and c2.button("Remove key", key="act_key_rm", disabled=not IS_OWNER):
                if ui.safe(platform.update_property, P["id"], portal_api_key="", what="remove the key"):
                    tenancy.refresh()
                    st.rerun()


def go(n: int) -> None:
    ui.safe(platform.update_workspace, onboarding_step=n, onboarded=n >= len(STEPS) - 1, what="save progress")
    tenancy.refresh()
    st.rerun()


# ------------------------------------------------------------------ onboarding wizard
with tab_ob:
    step = int(T.get("onboarding_step") or 0)
    if T.get("is_demo"):
        ui.html(
            theme.banner(
                "This is the <b>demo workspace</b>. Real hotel groups are created by HOI in the platform console; "
                "their owner then finishes setup here.",
                "amber",
                "info",
            )
        )
    ui.html(
        '<div class="ss-stepper">'
        + "".join(
            f'<div class="s {"on" if i == step else "done" if i < step else ""}"><span>{i + 1 if i >= step else "✓"}</span>{n}</div>'
            for i, n in enumerate(STEPS)
        )
        + "</div>"
    )
    with st.container(key="card_ob"):
        if step == 0:
            name = st.text_input("Organization / hotel group name", value=T["name"])
            color = st.color_picker("Brand color", value=T["brand_color"])
            st.caption(f"Plan: {tenancy.PLANS.get(T['plan'], {}).get('label', T['plan'])} (changed by HOI on request).")
            if st.button("Continue", type="primary", disabled=not name.strip()):
                if ui.safe(platform.update_workspace, name=name.strip(), brand_color=color, what="save the organization"):
                    go(1)
        elif step == 1:
            props = T.get("properties") or []
            for p in props:
                ui.html(
                    f'<div class="ss-wrow">{theme.icon("bed", 18)}<b style="flex:1">{theme.esc(p["name"])}</b>'
                    f'<span class="ss-tag">{theme.esc(p["region"])}</span><span class="ss-tag">{p["rooms"]} rooms · {p["floors"]} floors</span></div>'
                )
            with st.form("prop", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                pname = c1.text_input("Property name", placeholder="Riverside Retreat")
                region = c2.text_input("Region", placeholder="Rishikesh, Uttarakhand")
                rooms = c3.number_input("Rooms", 1, 2000, 45)
                floors = c4.number_input("Floors", 1, 60, 4)
                add = st.form_submit_button("Add property", icon=":material/add:")
            if add and pname:
                if ui.safe(platform.add_property, pname, region, int(rooms), int(floors), what="add the property"):
                    tenancy.refresh()
                    st.rerun()
            b1, b2 = st.columns([1, 6])
            if b1.button("Back"):
                go(0)
            if b2.button("Continue", type="primary", disabled=not props):
                go(2)
        elif step == 2:
            st.markdown(
                "**Import staff by ID only.** Columns: `employee_id, department, skills, contract_type`. "
                "Files with personal columns (name, gender, religion, caste, health, family, phone…) are rejected by the server."
            )
            tmpl = pd.DataFrame(
                [
                    {"employee_id": "E001", "department": "housekeeping", "skills": "deep_clean;linen", "contract_type": "permanent"},
                    {"employee_id": "E002", "department": "maintenance", "skills": "electrical", "contract_type": "seasonal"},
                ]
            )
            c1, c2 = st.columns(2)
            c1.download_button(
                "Download CSV template", tmpl.to_csv(index=False).encode(), "hoi_staff_template.csv", icon=":material/download:"
            )
            if c2.button("Use 30 sample staff", icon=":material/group_add:"):
                rows = [{"employee_id": f"S{i:03d}", "department": random.Random(i).choice(dispatch.DEPARTMENTS)} for i in range(1, 31)]
                if ui.safe(platform.import_staff, rows, what="import sample staff"):
                    st.rerun()
            f = st.file_uploader("Staff CSV", type=["csv"])
            if f is not None:
                try:
                    df = pd.read_csv(io.BytesIO(f.getvalue())).fillna("")
                except Exception as e:  # noqa: BLE001 - show any parse problem to the user
                    st.error(f"Could not read the CSV: {e}")
                    df = None
                if df is not None:
                    st.dataframe(df.head(10), hide_index=True, width="stretch")
                    if st.button(f"Import {len(df)} staff", type="primary"):
                        r = ui.safe(platform.import_staff, df.astype(str).to_dict("records"), what="import staff")
                        if r:
                            st.success(f"Imported {r['imported']} · {r['total']} staff in this workspace.")
            n = len(ui.safe(platform.staff, what="count staff") or [])
            st.caption(f"{n} staff in this workspace.")
            b1, b2 = st.columns([1, 6])
            if b1.button("Back"):
                go(1)
            if b2.button("Continue", type="primary", disabled=n == 0):
                go(3)
        elif step == 3:
            mode = st.radio(
                "Where does this workspace get its forecast, roster and risk data?",
                ["Demo data (offline)", "My HOI ML backend"],
                horizontal=True,
                index=0 if T["use_mocks"] else 1,
            )
            url = st.text_input("ML backend URL", value=T.get("api_base_url") or DEFAULT_API, disabled=mode.startswith("Demo"))
            if st.button("Test connection", icon=":material/lan:"):
                s = Settings(**{**current_settings().__dict__, "use_mocks": mode.startswith("Demo"), "api_base_url": url.rstrip("/")})
                h = ui.safe(api.health, settings=s, what="reach the backend")
                if h:
                    st.success(f"Connected · status {h.get('status')} · {len(h.get('models', []))} models")
            b1, b2 = st.columns([1, 6])
            if b1.button("Back"):
                go(2)
            if b2.button("Continue", type="primary"):
                if ui.safe(
                    platform.update_workspace, use_mocks=mode.startswith("Demo"), api_base_url=url.rstrip("/"), what="save the data source"
                ):
                    tenancy.on_tenant_change()
                    go(4)
        elif step == 4:
            st.markdown(
                "**Invite your team** in the *Team & access* tab: each invite is a one-time code for a role. No email addresses are stored."
            )
            b1, b2 = st.columns([1, 6])
            if b1.button("Back"):
                go(3)
            if b2.button("Finish setup", type="primary"):
                go(5)
        else:
            props = T.get("properties") or []
            ui.html(
                theme.banner(
                    f"<b>{theme.esc(T['name'])} is ready.</b> {len(props)} property(ies), data source: "
                    f"{'demo data' if T['use_mocks'] else theme.esc(T.get('api_base_url') or '')}.",
                    "blue",
                    "check",
                )
            )
            c1, c2, c3 = st.columns(3)
            if c1.button("Open overview", type="primary", width="stretch"):
                st.switch_page(nav.page("pages/1_Overview.py"))
            if c2.button("Open dispatch", width="stretch"):
                st.switch_page(nav.page("pages/10_Dispatch.py"))
            if c3.button("Edit setup", width="stretch"):
                go(0)

# ------------------------------------------------------------------ team & access
with tab_team:
    ui.html(
        theme.section(
            "Team & access",
            "Users",
            "Everyone who can sign in to this hotel group. Employees only see the employee app; "
            "risk scores are visible to owner/GM and HR only.",
        )
    )
    me_user = auth.current() or {}
    for u in ui.safe(platform.users, what="load users") or []:
        a, b, c = st.columns([3, 1.4, 1])
        a.markdown(
            f"**{u['username']}**"
            + (f" · {u['employee_id']}" if u["employee_id"] else "")
            + f"  \n<span style='color:#6b6a65;font-size:.8rem'>last sign-in {(u['last_login'] or 'never')[:16].replace('T', ' ')}</span>",
            unsafe_allow_html=True,
        )
        b.markdown(theme.band_chip("low" if u["active"] else "high", auth.ROLES.get(u["role"], u["role"])), unsafe_allow_html=True)
        if u["id"] != me_user.get("id") and c.button("Disable" if u["active"] else "Enable", key=f"tog_{u['id']}", width="stretch"):
            ui.safe(platform.set_user_active, u["id"], not u["active"], what="change access")
            st.rerun()
    st.divider()
    c1, c2 = st.columns([2, 1])
    role = c1.selectbox(
        "Invite a new user as", ["owner", "hr", "dept_head", "storekeeper", "worker"], format_func=lambda r: auth.ROLES[r], key="team_role"
    )
    if c2.button("Create invite code", key="team_inv", type="primary", width="stretch"):
        inv = ui.safe(platform.create_invite, role, what="create the invite")
        if inv:
            st.session_state["team_code"] = (role, inv["code"])
    if tc := st.session_state.get("team_code"):
        ui.html(
            theme.banner(
                f"One-time code for <b>{theme.esc(auth.ROLES[tc[0]])}</b>: <code style='font-size:1.1rem'>{tc[1]}</code>. "
                "They sign up at the sign-in page under <i>Join with invite code</i>.",
                "blue",
                "check",
            )
        )
    pending = ui.safe(platform.invites, what="load invites") or []
    if pending:
        st.caption("Unused invite codes: " + ", ".join(f"{i['code']} ({auth.ROLES.get(i['role'], i['role'])})" for i in pending[:10]))

# ------------------------------------------------------------------ plan
with tab_plan:
    ui.html(theme.section("Plan", "Packaging", "Tiers by scope. Pricing is set with pilot partners, so no prices are shown."))
    cols = st.columns(3)
    for col, (k, p) in zip(cols, tenancy.PLANS.items()):
        with col:
            ui.html(
                f'<div class="ss-card ss-anim" style="min-height:230px;{"outline:2px solid #1f6fe5" if k == T["plan"] else ""}">'
                f'<div style="font-size:1.4rem;font-weight:600;letter-spacing:-.03em">{p["label"]}{" · current" if k == T["plan"] else ""}</div>'
                f'<div style="color:#6b6a65;margin:4px 0 12px">{p["properties"] or "Unlimited"} properties · {p["staff"] or "unlimited"} staff</div>'
                + "".join(f'<div style="margin:6px 0">{theme.icon("check", 16, "#0ca30c")} {theme.esc(m)}</div>' for m in p["modules"])
                + "</div>"
            )

ui.footer()
