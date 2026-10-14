import io
import random

import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import auth, dispatch, nav, platform, tenancy, theme, timefmt, ui
from lib.config import DEFAULT_API, Settings, current_settings

ui.setup("pages/12_Setup.py", "Setup")
T = tenancy.refresh()
STEPS = ["Your business", "Hotel", "Staff", "Data", "Team", "Done"]

ui.page_head("Settings", "How this hotel works, your thank-you budget, and the link to the tourism portal.")
IS_OWNER = auth.role() in ("owner", "platform_admin")
HOMESTAY = tenancy.is_homestay()
tab_prop, tab_ob, tab_team, tab_plan = st.tabs(["This hotel", "Setup steps", "Team & access", "Plan"])


def _save_photos(rows: list[dict]) -> bool:
    try:
        platform.save_photo_proof_settings(rows)
        return True
    except platform.PlatformError as e:
        st.error("Available after the next update." if e.status == 404 else f"Could not save. {e.message}")
        return False


def _photo_proof() -> None:
    """Photos staff must take: one row per job kind, a before and an after tick. Owner edits; everyone else reads."""
    can_edit = auth.role() == "owner"
    with st.container(key="card_photos"):
        st.markdown("**Photos staff must take**")
        try:
            cfg = platform.photo_proof_settings()
        except platform.PlatformError as e:
            if e.status == 404:
                st.caption("Available after the next update.")
            else:
                st.caption(f"Could not load the photo settings. {e.message}")
            return
        kinds = [k for k in (cfg or {}).get("kinds") or [] if isinstance(k, dict) and k.get("kind")]
        if not kinds:
            st.caption("No job types to set yet.")
            return
        st.caption(
            "For each type of job: does the staff app ask for a photo before the work, after it, or both? "
            + ("" if can_edit else "Only the owner can change this.")
        )
        rows = []
        for k in kinds:
            c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="center")  # on a phone these stack; each tick keeps its label
            c1.markdown(f"**{theme.esc(k.get('label') or str(k['kind']).replace('_', ' ').capitalize())}**")
            b = c2.checkbox("Photo before", value=bool(k.get("before")), key=f"pp_b_{k['kind']}", disabled=not can_edit)
            a = c3.checkbox("Photo after", value=bool(k.get("after")), key=f"pp_a_{k['kind']}", disabled=not can_edit)
            rows.append({"kind": k["kind"], "before": bool(b), "after": bool(a)})
        if not can_edit:
            return
        s1, s2, _ = st.columns([1, 1.4, 2])
        if s1.button("Save", key="act_photos", type="primary", width="stretch"):
            if _save_photos(rows):
                st.toast("Saved")
                st.rerun()
        if s2.button("Reset to recommended", key="act_photos_reset", width="stretch"):
            defaults = [
                {"kind": d["kind"], "before": bool(d.get("before")), "after": bool(d.get("after"))}
                for d in (cfg or {}).get("defaults") or []
                if isinstance(d, dict) and d.get("kind")
            ]
            if _save_photos(defaults):
                for k in kinds:  # let the ticks show the saved values again
                    st.session_state.pop(f"pp_b_{k['kind']}", None)
                    st.session_state.pop(f"pp_a_{k['kind']}", None)
                st.toast("Back to the recommended photos")
                st.rerun()


# ------------------------------------------------------------------ this property: mode, budget, recognition, portal key
with tab_prop:
    ui.property_picker(key="prop_pick_settings", label="Hotel")
    P = tenancy.current_property()
    if not P:
        ui.empty("Add a hotel first (Setup steps).")
    else:
        with st.container(key="card_mode"):
            st.markdown("**How should the app look?**")
            choice = st.radio(
                "Mode",
                ["homestay", "hotel"],
                index=0 if P.get("mode") == "homestay" else 1,
                horizontal=True,
                format_func=lambda m: (
                    "Homestay: simple, only the basics" if m == "homestay" else "Hotel: everything (shift plan, jobs, numbers)"
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
            st.markdown("**Thank-you budget**")
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
                "Points only go up and are never used to punish. Each person gets their share of the points × this budget (with a limit)."
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
                + "Paste the key from your portal business account so Extra staff requests can be sent. It is never shown again."
            )
            key = st.text_input("Portal key", type="password", key="portal_key_in", disabled=not IS_OWNER)
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

        _photo_proof()


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
                "This is the <b>practice hotel</b>. Real hotels are added by the HOI team; the owner then finishes setup here.",
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
            name = st.text_input("Business name", value=T["name"])
            color = st.color_picker("Brand color", value=T["brand_color"])
            st.caption(f"Plan: {tenancy.PLANS.get(T['plan'], {}).get('label', T['plan'])} (changed by HOI on request).")
            if st.button("Continue", type="primary", disabled=not name.strip()):
                if ui.safe(platform.update_workspace, name=name.strip(), brand_color=color, what="save the name"):
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
                pname = c1.text_input("Hotel name", placeholder="Riverside Retreat")
                region = c2.text_input("Region", placeholder="Rishikesh, Uttarakhand")
                rooms = c3.number_input("Rooms", 1, 2000, 45)
                floors = c4.number_input("Floors", 1, 60, 4)
                add = st.form_submit_button("Add hotel", icon=":material/add:")
            if add and pname:
                if ui.safe(platform.add_property, pname, region, int(rooms), int(floors), what="add the hotel"):
                    tenancy.refresh()
                    st.rerun()
            b1, b2 = st.columns([1, 6])
            if b1.button("Back"):
                go(0)
            if b2.button("Continue", type="primary", disabled=not props):
                go(2)
        elif step == 2:
            st.markdown(
                "**Add staff by ID only.** Columns: `employee_id, department, skills, contract_type`. "
                "Files with personal details (name, gender, religion, caste, health, family, phone…) are not accepted."
            )
            tmpl = pd.DataFrame(
                [
                    {"employee_id": "E001", "department": "housekeeping", "skills": "deep_clean;linen", "contract_type": "permanent"},
                    {"employee_id": "E002", "department": "maintenance", "skills": "electrical", "contract_type": "seasonal"},
                ]
            )
            c1, c2 = st.columns(2)
            c1.download_button(
                "Download an empty sheet (CSV)", tmpl.to_csv(index=False).encode(), "hoi_staff_template.csv", icon=":material/download:"
            )
            if c2.button("Add 30 practice staff", icon=":material/group_add:"):
                rows = [{"employee_id": f"S{i:03d}", "department": random.Random(i).choice(dispatch.DEPARTMENTS)} for i in range(1, 31)]
                if ui.safe(platform.import_staff, rows, what="add practice staff"):
                    st.rerun()
            f = st.file_uploader("Staff sheet (CSV)", type=["csv"])
            if f is not None:
                try:
                    df = pd.read_csv(io.BytesIO(f.getvalue())).fillna("")
                except Exception as e:  # noqa: BLE001 - show any parse problem to the user
                    st.error(f"Could not read the sheet: {e}")
                    df = None
                if df is not None:
                    st.dataframe(df.head(10), hide_index=True, width="stretch")
                    if st.button(f"Add {len(df)} staff", type="primary"):
                        r = ui.safe(platform.import_staff, df.astype(str).to_dict("records"), what="add staff")
                        if r:
                            st.success(f"Added {r['imported']} · {r['total']} staff in total.")
            n = len(ui.safe(platform.staff, what="count staff") or [])
            st.caption(f"{n} staff in total.")
            b1, b2 = st.columns([1, 6])
            if b1.button("Back"):
                go(1)
            if b2.button("Continue", type="primary", disabled=n == 0):
                go(3)
        elif step == 3:
            mode = st.radio(
                "Which data should we use for how full you'll be, the shift plan and check-ins?",
                ["Practice data", "My HOI server"],
                horizontal=True,
                index=0 if T["use_mocks"] else 1,
            )
            url = st.text_input("Server address", value=T.get("api_base_url") or DEFAULT_API, disabled=mode.startswith("Practice"))
            if st.button("Test connection", icon=":material/lan:"):
                s = Settings(**{**current_settings().__dict__, "use_mocks": mode.startswith("Practice"), "api_base_url": url.rstrip("/")})
                h = ui.safe(api.health, settings=s, what="reach the server")
                if h:
                    st.success(
                        "Connected. The server is working." if h.get("status") == "ok" else "Connected, but the server reports a problem."
                    )
            b1, b2 = st.columns([1, 6])
            if b1.button("Back"):
                go(2)
            if b2.button("Continue", type="primary"):
                if ui.safe(
                    platform.update_workspace,
                    use_mocks=mode.startswith("Practice"),
                    api_base_url=url.rstrip("/"),
                    what="save the data choice",
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
                    f"<b>{theme.esc(T['name'])} is ready.</b> {len(props)} hotel(s), "
                    f"{'practice data' if T['use_mocks'] else 'your own data'}.",
                    "blue",
                    "check",
                )
            )
            c1, c2, c3 = st.columns(3)
            if c1.button("Open week numbers", type="primary", width="stretch"):
                nav.go("pages/1_Overview.py")
            if c2.button("Open jobs", width="stretch"):
                nav.go("pages/10_Dispatch.py")
            if c3.button("Edit setup", width="stretch"):
                go(0)

# ------------------------------------------------------------------ team & access
with tab_team:
    ui.html(
        theme.section(
            "Team & access",
            "Users",
            "Everyone who can sign in. Staff only see the staff app. The owner/GM and HR see the whole 'May leave soon?' page; department heads see only their own team, without pay reasons.",
        )
    )
    me_user = auth.current() or {}
    for u in ui.safe(platform.users, what="load users") or []:
        a, b, c = st.columns([3, 1.4, 1])
        a.markdown(
            f"**{u['username']}**"
            + (f" · {u['employee_id']}" if u["employee_id"] else "")
            + f"  \n<span style='color:#6b6a65;font-size:.8rem'>last sign-in {timefmt.stamp(u['last_login']) if u['last_login'] else 'never'}</span>",
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
    ui.html(theme.section("Plan", "Packaging", "What each plan includes. Prices are agreed with each hotel, so none are shown."))
    cols = st.columns(3)
    for col, (k, p) in zip(cols, tenancy.PLANS.items()):
        with col:
            ui.html(
                f'<div class="ss-card ss-anim" style="min-height:230px;{"outline:2px solid #1f6fe5" if k == T["plan"] else ""}">'
                f'<div style="font-size:1.4rem;font-weight:600;letter-spacing:-.03em">{p["label"]}{" · current" if k == T["plan"] else ""}</div>'
                f'<div style="color:#6b6a65;margin:4px 0 12px">{p["properties"] or "Any number of"} hotels · {p["staff"] or "any number of"} staff</div>'
                + "".join(f'<div style="margin:6px 0">{theme.icon("check", 16, "#0ca30c")} {theme.esc(m)}</div>' for m in p["modules"])
                + "</div>"
            )

ui.footer()
