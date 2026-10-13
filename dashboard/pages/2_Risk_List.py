import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import charts, data, platform, theme, ui
from lib.config import current_settings

ui.setup("pages/2_Risk_List.py", "May leave soon?")
ui.page_head(
    "May leave soon? Check in",
    "This is a list to check in with people, not a judgement.",
)

scores = ui.safe(data.scores, ui.week(), what="load the check-in list")
if scores is None:
    ui.footer()
    st.stop()
if not scores:
    ui.empty("No one to show for this week yet.")
    ui.footer()
    st.stop()

depts = data.dept_map()


# ------------------------------------------------------------------ what to do next (retention check-in)
# Low / moderate chance: talk to them (2-3 points from the model's reasons, then log the talk in the backend's closed loop).
# High chance: also look for someone on the tourism portal (platform API, which holds the portal key). If nobody fits,
# the owner posts ONE job with one click: never automatic, because a post cannot be taken back from here and agencies
# are told at once.
LEVEL_BAND = {"low": "low", "moderate": "watch", "high": "high"}


def _plan(emp: str) -> dict | None:
    """The backend's plan for this person (level, talking points, talk logged?). None when not available (demo data / old API)."""
    s = current_settings()
    if s.use_mocks:
        return None
    try:  # no wrapper in lib.api_client yet; the page owns this call
        rows = api._http("GET", "/retention/plan", s, params={"employee_id": emp, **({"week_start": ui.week()} if ui.week() else {})})
    except api.ApiError:
        return None
    return rows[0] if rows else None


def _fallback_points(sc) -> list[str]:
    pts = [f"{d.title}. Ask how they feel about it." for d in sc.drivers[:3]]
    return (pts + ["Ask how work is going for them this month.", "Ask if one thing would make their week easier."])[: max(2, len(pts))]


def _talk_block(emp: str, sc, plan: dict | None) -> None:
    points = plan["talking_points"] if plan else _fallback_points(sc)
    st.markdown("**Talk to them**")
    for x in points:
        st.markdown(f"- {x}")
    if plan and plan.get("talked"):
        st.success(f"Talk noted on {str(plan.get('talked_at') or '')[:10]}.", icon=":material/check_circle:")
        return
    if plan is None:
        st.caption("Saving a talk needs the live server.")
        return
    if st.button("We talked", key=f"talk_{emp}", icon=":material/forum:", help="Saves that the talk happened. No notes are stored."):
        try:
            api._http("POST", "/retention/talks", current_settings(), json={"employee_id": emp, "week_start": plan["week_start"], "points": points})
            st.toast("Talk noted.")
            st.rerun()
        except api.ApiError as e:
            st.error(e.message)


def _candidate_card(c: dict) -> None:
    skills = ", ".join(f"{x.get('label')} ({x.get('years', 0)} yrs)" for x in c.get("skills") or [])
    places = ", ".join(c.get("districts") or [])
    match = f"{c['match']}% match" if c.get("match") is not None else ""
    sample = " · sample profile" if c.get("synthetic") else ""
    st.markdown(f"**{c.get('code') or ''}** · {skills}")
    st.caption(f"{places} · {c.get('availability') or ''} · {match}{sample}")
    if c.get("open_url"):
        st.link_button("Contact via the portal", c["open_url"], icon=":material/open_in_new:")


def _cover_block(emp: str) -> None:
    st.markdown("**Look for someone who could help**")
    key = f"cover_{emp}"
    if st.button("Look on the job portal", key=f"look_{emp}", icon=":material/person_search:"):
        try:
            st.session_state[key] = platform.call("GET", f"/staffing/cover/{emp}", params=platform._pid_params())
        except platform.PlatformError as e:
            st.session_state[key] = {"status": "error", "message": e.message, "candidates": [], "job": None}
    res = st.session_state.get(key)
    if not res:
        st.caption("Checks the Uttarakhand Travel Guide for job seekers with the same skill near the hotel.")
        return
    job = res.get("job")
    if res["status"] == "matches":
        st.info(res["message"], icon=":material/group:")
        for c in res.get("candidates") or []:
            with st.container(border=True):
                _candidate_card(c)
        if res.get("search_url"):
            st.link_button("See all on the portal", res["search_url"], icon=":material/open_in_new:")
        st.caption(res.get("privacy") or "")
    elif job and job.get("status") == "sent":
        st.success("Job posted on the Uttarakhand Travel Guide.", icon=":material/check_circle:")
    elif res["status"] == "no_matches":
        st.warning(res["message"], icon=":material/person_off:")
        st.caption("Posts one opening for this role for the next 30 days. The post does not name anyone or say why.")
        if st.button("Post the job on the Uttarakhand Travel Guide", key=f"post_{emp}", type="primary", icon=":material/campaign:"):
            try:
                out = platform.call("POST", f"/staffing/cover/{emp}/post", params=platform._pid_params())
                st.session_state[key] = {**res, "job": out["job"]}
                st.toast(out["message"])
                st.rerun()
            except platform.PlatformError as e:
                st.error(e.message)
    else:
        st.info(res.get("message") or "The job portal could not be checked.", icon=":material/info:")
    if job and job.get("job_url"):
        st.link_button("Open the job post", job["job_url"], icon=":material/open_in_new:")
    elif job and job.get("status") == "pending_send":
        st.caption("A job is saved but not on the portal yet: " + (job.get("last_error") or "try again later."))


def _next_steps(emp: str, sc) -> None:
    plan = _plan(emp)
    level = plan["level"] if plan else {"watch": "moderate"}.get(sc.band, sc.band)
    label = {"low": "Low", "moderate": "Moderate", "high": "High"}.get(level, "Not known")
    ui.html(f"<div style='margin:6px 0'>Chance of leaving: {theme.band_chip(LEVEL_BAND.get(level, 'unknown'), label)}</div>")
    if level == "high":
        t, c = st.columns(2)
        with t:
            _talk_block(emp, sc, plan)
        with c:
            _cover_block(emp)
    else:
        _talk_block(emp, sc, plan)
    st.caption("Based on a model trained on SYNTHETIC (made-up) data. A prompt for a friendly chat, not a judgement.")



# ------------------------------------------------------------------ summary first
n_by = {b: sum(1 for x in scores if x.band == b) for b in ("high", "watch", "low")}
ui.big_numbers(
    [
        ("Check in this week", n_by["high"], "Start with a friendly chat", "warn" if n_by["high"] else "ok"),
        ("Keep an eye on", n_by["watch"], "Say hello, ask how things are", "info"),
        ("Doing fine", n_by["low"], "Nothing to do", "ok"),
    ]
)

# ------------------------------------------------------------------ filters
f1, f4 = st.columns([2, 2])
dept_opts = sorted({depts.get(s.employee_id, "unknown") for s in scores})
with f1:
    sel_depts = st.multiselect("Department", dept_opts, default=[], format_func=theme.dept_label, placeholder="All departments")
with f4:
    q = st.text_input("Search ID / name", placeholder="Search by staff ID, e.g. HS05")
with st.expander("More filters"):
    g1, g2 = st.columns(2)
    sel_bands = g1.multiselect(
        "Group", theme.BAND_ORDER, default=[], format_func=lambda b: theme.BAND[b]["label"], placeholder="All groups"
    )
    ctype = g2.segmented_control("Contract", ["All", "Permanent", "Seasonal"], default="All")

names = data.hero_names()
rows = []
for s in scores:
    d = depts.get(s.employee_id, "unknown")
    if sel_depts and d not in sel_depts:
        continue
    if sel_bands and s.band not in sel_bands:
        continue
    if ctype in ("Permanent", "Seasonal") and s.contract_type != ctype.lower():
        continue
    if q and q.lower() not in s.employee_id.lower() and q.lower() not in names.get(s.employee_id, "").lower():
        continue
    td = s.top_driver
    rows.append(
        {
            "employee_id": s.employee_id,
            "Role": ui.avatar_uri(d),
            "Employee": ui.display_name(s.employee_id),
            "Department": theme.dept_label(d),
            "Contract": s.contract_type,
            "Group": theme.BAND[s.band]["label"],
            "Place": s.rank,
            "of": s.group_size,
            "Same place": "yes" if s.rank_is_tied else "",
            "Based on": theme.BASIS[s.band_basis][0],
            "Main reason": td.title if td and s.band != "low" else "—",
            "Chance (90 days)": s.risk,
            "_band": s.band,
        }
    )
df = pd.DataFrame(rows)
order = {theme.BAND[k]["label"]: i for i, k in enumerate(["high", "watch", "low", "unknown"])}
if not df.empty:
    df = df.sort_values(["Contract", "Group", "Place"], key=lambda c: c.map(order) if c.name == "Group" else c).reset_index(drop=True)

ui.takeaway(f"{len(df)} people. Tap a row to see why, and what support may help.")
if df.empty:
    ui.empty("No employees match these filters.")
else:

    def band_style(v):
        key = next((k for k, b in theme.BAND.items() if b["label"] == v), "unknown")
        b = theme.BAND[key]
        return f"background-color:{b['bg']};color:{b['fg']};font-weight:600"

    details = st.toggle("More columns", key="risk_details", help="Show place in the team, contract and the chance number")
    main = ["Role", "Employee", "Department", "Group", "Main reason"]
    show = df.drop(columns=["employee_id", "_band"])
    if not details:
        show = show[main]
    ev = st.dataframe(
        show.style.map(band_style, subset=["Group"]).format({"Chance (90 days)": "{:.0%}"} if details else {}),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        height=min(560, 38 * len(df) + 40),
        column_config={
            "Role": st.column_config.ImageColumn("Role", width="small", help="Department picture (a drawing, not a photo)"),
            "Chance (90 days)": st.column_config.ProgressColumn("Chance (90 days)", min_value=0, max_value=1, format="percent"),
            "Place": st.column_config.NumberColumn(width="small"),
            "of": st.column_config.NumberColumn(width="small"),
        },
    )
    e1, e2 = st.columns([1, 4])
    with e1:
        export = df[["employee_id", "Department", "Contract", "Group", "Place", "of", "Based on", "Main reason", "Chance (90 days)"]]
        st.download_button(
            "Download (Excel/CSV)",
            export.to_csv(index=False).encode(),
            "hoi_check_in_list.csv",
            "text/csv",
            icon=":material/download:",
            help="IDs only, no names. Uses your filters.",
        )
    with e2:
        if not depts:
            st.caption("Departments come from the shift plan. Make one to fill them in.")

    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        emp = df.iloc[sel[0]]["employee_id"]
        s = next(x for x in scores if x.employee_id == emp)
        with st.container(key="card_drill"):
            a, b = st.columns([1.5, 1])
            with a:
                ui.html(
                    f'<div class="ss-person">{ui.avatar_img(depts.get(emp), 46)}'
                    f'<div><div style="font-weight:600;font-size:1.15rem">{theme.esc(ui.display_name(emp))}</div>'
                    f'<div style="display:flex;gap:6px;margin-top:4px">{theme.band_chip(s.band)}{theme.basis_tag(s.band_basis)}'
                    f'{theme.contract_tag(s.contract_type)}<span class="ss-tag">place {s.rank} of {s.group_size}</span></div></div></div>'
                )
                if s.drivers:
                    st.plotly_chart(charts.driver_bars(s.drivers), width="stretch", config={"displayModeBar": False})
                elif s.contract_type == "seasonal":
                    ui.empty("Seasonal staff are grouped by when their contract ends, so there is no list of reasons.")
                else:
                    ui.empty("No reasons to show for this person.")
            with b:
                st.markdown("**How clear is each reason?**", help=theme.SUPPORT_HELP)
                ui.html(" ".join(theme.support_chip(k) for k in theme.SUPPORT))
                for d in s.drivers:
                    st.markdown(f"- **{d.title}**: {d.reason}")
                if st.button("Open this person", icon=":material/person:"):
                    ui.go_to_employee(emp)
            st.divider()
            _next_steps(emp, s)

ui.footer()
