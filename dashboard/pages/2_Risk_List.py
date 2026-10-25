import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import auth, charts, data, platform, privacy, theme, ui
from lib.config import current_settings
from lib.models import based_on

ui.setup("pages/2_Risk_List.py", "May leave soon?")
ui.page_head(
    "May leave soon? Check in",
    "This is a list to check in with people, not a judgement.",
)

scores = ui.safe(data.scores_live, ui.week(), what="load the check-in list")
if scores is None:
    ui.footer()
    st.stop()
if not scores:
    ui.empty("No one to show for this week yet.")
    ui.footer()
    st.stop()

depts = data.dept_map()
scores, my_dept = privacy.team_scope(scores, depts)  # department heads: their own department only
if not scores:
    ui.empty(
        f"No one in {theme.dept_label(my_dept).lower()} to show for this week."
        if my_dept
        else "Your account is not linked to a department yet. Ask the owner to link it to your staff ID."
    )
    ui.footer()
    st.stop()
if my_dept:
    st.caption(f"Showing your department only: {theme.dept_label(my_dept)}. Reasons about pay are private (ask HR).")


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
    pts = [f"{d.title}. Ask how they feel about it." for d in sc.drivers[:3] if not privacy.is_pay_driver(d) or privacy.sees_pay()]
    return (pts + ["Ask how work is going for them this month.", "Ask if one thing would make their week easier."])[: max(2, len(pts))]


def _talk_block(emp: str, sc, plan: dict | None) -> None:
    # live scores: the points come from this score's reasons (the backend plan is for the demo week)
    points = plan["talking_points"] if plan and sc.data_source != "live" else _fallback_points(sc)
    st.markdown("**Talk to them**")
    for x in points:
        st.markdown(f"- {privacy.text(x)}")
    if plan and plan.get("talked"):
        st.success(f"Talk noted on {str(plan.get('talked_at') or '')[:10]}.", icon=":material/check_circle:")
        return
    if plan is None:
        st.caption("Saving a talk needs the live server.")
        return
    if st.button("We talked", key=f"talk_{emp}", icon=":material/forum:", help="Saves that the talk happened. No notes are stored."):
        try:
            api._http(
                "POST",
                "/retention/talks",
                current_settings(),
                json={"employee_id": emp, "week_start": plan["week_start"], "points": points},
            )
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
            st.session_state[key] = platform.call("GET", f"/staffing/cover/{emp}", params=platform._pid_params(), timeout=platform.SLOW_S)
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
                out = platform.call("POST", f"/staffing/cover/{emp}/post", params=platform._pid_params(), timeout=platform.SLOW_S)
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
    live = sc.data_source == "live"
    level = plan["level"] if plan and not live else {"watch": "moderate"}.get(sc.band, sc.band)
    label = {"low": "Low", "moderate": "Moderate", "high": "High"}.get(level, "Not known")
    ui.html(f"<div style='margin:6px 0'>Chance of leaving: {theme.band_chip(LEVEL_BAND.get(level, 'unknown'), label)}</div>")
    if level == "high" and auth.role() in privacy.WHOLE_HOTEL_ROLES:  # posting a job on the portal: owner / HR
        t, c = st.columns(2)
        with t:
            _talk_block(emp, sc, plan)
        with c:
            _cover_block(emp)
    else:
        _talk_block(emp, sc, plan)
    st.caption(f"{based_on(sc)}. The model was trained on SYNTHETIC (made-up) data. A prompt for a friendly chat, not a judgement.")


# ------------------------------------------------------------------ summary first
n_by = {b: sum(1 for x in scores if x.band == b) for b in ("high", "watch", "low")}
ui.big_numbers(
    [
        ("Check in this week", n_by["high"], "Start with a friendly chat", "warn" if n_by["high"] else "ok"),
        ("Keep an eye on", n_by["watch"], "Say hello, ask how things are", "info"),
        ("Doing fine", n_by["low"], "Nothing to do", "ok"),
    ]
)

SOURCES = ["shifts", "jobs", "thank-yous", "check-ins", "weekly answers", "leave marks"]
n_live = sum(1 for x in scores if x.data_source == "live")
if n_live:
    weeks = max(x.weeks_of_history or 0 for x in scores if x.data_source == "live")
    srcs = sorted(
        {y for x in scores if x.data_source == "live" for y in x.data_sources if y != "HR record"},
        key=lambda y: SOURCES.index(y) if y in SOURCES else len(SOURCES),
    )
    rest = len(scores) - n_live
    st.caption(
        f"Based on: {', '.join(srcs)} (up to {weeks} weeks) for {n_live} people"
        + (f"; example (made-up) data for {rest} without records yet." if rest else ".")
    )
else:
    st.caption("Based on: example (made-up) data, no records from your hotel yet.")

# ------------------------------------------------------------------ filters
f1, f4 = st.columns([2, 2])
dept_opts = sorted({depts.get(s.employee_id, "unknown") for s in scores})
with f1:
    sel_depts = st.multiselect("Department", dept_opts, default=[], format_func=theme.dept_label, placeholder="All departments")
with f4:
    q = st.text_input("Search by staff ID", placeholder="e.g. HS05")
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
            "Main reason": (privacy.drivers([td])[0].title if td and s.band != "low" else "—"),
            "Chance (90 days)": s.risk,
            "_band": s.band,
        }
    )
df = pd.DataFrame(rows)
order = {theme.BAND[k]["label"]: i for i, k in enumerate(["high", "watch", "low", "unknown"])}
if not df.empty:
    df = df.sort_values(["Contract", "Group", "Place"], key=lambda c: c.map(order) if c.name == "Group" else c).reset_index(drop=True)


def _person_card(emp: str, i: int) -> None:
    """Why this person may need support, and what to do next (one card per selected person)."""
    s = next(x for x in scores if x.employee_id == emp)
    ds = privacy.drivers(s.drivers)
    with st.container(key=f"card_drill_{i}"):
        a, b = st.columns([1.5, 1])
        with a:
            ui.html(
                f'<div class="ss-person">{ui.avatar_img(depts.get(emp), 46)}'
                f'<div><div style="font-weight:600;font-size:1.15rem">{theme.esc(ui.display_name(emp))}</div>'
                f'<div style="display:flex;gap:6px;margin-top:4px;flex-wrap:wrap">{theme.band_chip(s.band)}{theme.basis_tag(s.band_basis)}'
                f'{theme.contract_tag(s.contract_type)}<span class="ss-tag">place {s.rank} of {s.group_size}</span></div></div></div>'
            )
            if ds:
                st.plotly_chart(charts.driver_bars(ds), width="stretch", config={"displayModeBar": False}, key=f"bars_{emp}")
            elif s.contract_type == "seasonal":
                ui.empty("Seasonal staff are grouped by when their contract ends, so there is no list of reasons.")
            else:
                ui.empty("No reasons to show for this person.")
        with b:
            st.markdown("**How clear is each reason?**", help=theme.SUPPORT_HELP)
            ui.html(" ".join(theme.support_chip(k) for k in theme.SUPPORT))
            for d in ds:
                st.markdown(f"- **{d.title}**" + (f": {d.reason}" if d.reason else ""))
            if st.button("Open this person", icon=":material/person:", key=f"open_{emp}"):
                ui.go_to_employee(emp)
        st.divider()
        _next_steps(emp, s)


ui.takeaway(f"{len(df)} people. Tick Select for the people you want to talk to, then press Plan check-ins.")
if df.empty:
    ui.empty("No employees match these filters.")
else:

    def band_style(v):
        key = next((k for k, b in theme.BAND.items() if b["label"] == v), "unknown")
        b = theme.BAND[key]
        return f"background-color:{b['bg']};color:{b['fg']};font-weight:600"

    details = st.toggle("More columns", key="risk_details", help="Show place in the team, contract and the chance number")
    main = ["Select", "Role", "Employee", "Department", "Group", "Main reason"]
    show = df.drop(columns=["employee_id", "_band"])
    show.insert(0, "Select", False)
    if not details:
        show = show[main]
    # the table changes with the filters: a new key per row set, so a tick can never move to another person
    sel_key = "risk_sel_" + str(abs(hash(tuple(df["employee_id"]))) % 10**10)
    edited = st.data_editor(
        show.style.map(band_style, subset=["Group"]).format({"Chance (90 days)": "{:.0%}"} if details else {}),
        hide_index=True,
        width="stretch",
        height=min(560, 38 * len(df) + 40),
        disabled=[c for c in show.columns if c != "Select"],
        key=sel_key,
        column_config={
            "Select": st.column_config.CheckboxColumn(
                "Select", width="small", help="Tick the people you want to talk to, then press Plan check-ins"
            ),
            "Role": st.column_config.ImageColumn("Role", width="small", help="Department picture (a drawing, not a photo)"),
            "Chance (90 days)": st.column_config.ProgressColumn("Chance (90 days)", min_value=0, max_value=1, format="percent"),
            "Place": st.column_config.NumberColumn(width="small"),
            "of": st.column_config.NumberColumn(width="small"),
        },
    )
    picked = [df.iloc[i]["employee_id"] for i in range(len(df)) if bool(edited.iloc[i]["Select"])]
    e1, e2, e3 = st.columns([1.2, 1.2, 2.6], vertical_alignment="center")
    with e1:
        if st.button(
            f"Plan check-ins ({len(picked)})" if picked else "Plan check-ins",
            type="primary",
            key="plan_checkins",
            icon=":material/forum:",
            disabled=not picked,
            width="stretch",
            help="Shows why each ticked person may need support, what to talk about, and the next steps",
        ):
            st.session_state["risk_plan"] = picked
    with e2:
        export = df[["employee_id", "Department", "Contract", "Group", "Place", "of", "Based on", "Main reason", "Chance (90 days)"]]
        st.download_button(
            "Download (Excel/CSV)",
            export.to_csv(index=False).encode(),
            "hoi_check_in_list.csv",
            "text/csv",
            icon=":material/download:",
            help="IDs only, no names. Uses your filters.",
            width="stretch",
        )
    with e3:
        if not picked:
            st.caption("Tick one or more people in the Select column first.")
        if not depts:
            st.caption("Departments come from the shift plan. Make one to fill them in.")

    plan_ids = [e for e in st.session_state.get("risk_plan") or [] if e in set(df["employee_id"])]
    if plan_ids:
        ui.html(f'<h3 class="ss-h3">Check-in plan: {len(plan_ids)} {"person" if len(plan_ids) == 1 else "people"}</h3>')
        MAX_CARDS = 5  # keep the page short; plan the rest in a second round
        for i, emp in enumerate(plan_ids[:MAX_CARDS]):
            _person_card(emp, i)
        if len(plan_ids) > MAX_CARDS:
            st.caption(f"Showing the first {MAX_CARDS}. Untick them and plan the others next.")

ui.footer()
