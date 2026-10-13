import plotly.graph_objects as go
import streamlit as st

from lib import api_client as api
from lib import charts, data, theme, ui

ui.setup("pages/3_Employee_Detail.py", "Employee")

scores = ui.safe(data.scores, ui.week(), what="load risk scores")
if not scores:
    if scores is not None:
        ui.empty("No scores available.")
    ui.footer()
    st.stop()

by_id = {s.employee_id: s for s in scores}
names = data.hero_names()
heroes = [e for e in names if e in by_id]
others = sorted(e for e in by_id if e not in names)
options = heroes + others
default = st.session_state.get("selected_employee") or (heroes[0] if heroes else options[0])

c_sel, c_hint = st.columns([2, 3])
with c_sel:
    emp = st.selectbox(
        "Employee (search by ID, or a demo hero's name)",
        options,
        index=options.index(default) if default in options else 0,
        format_func=ui.display_name,
    )
st.session_state["selected_employee"] = emp
with c_hint:
    ui.html(
        '<div style="height:26px"></div>'
        + " ".join(f'<span class="ss-tag" style="margin-right:4px">{theme.esc(n)}</span>' for n in names.values())
        + '<span style="color:#6b6a65;font-size:.78rem;margin-left:6px">scripted demo heroes · everyone else is shown by ID only</span>'
    )

s = by_id[emp]
dept = data.dept_map().get(emp)
hero = next((h for h in (ui.safe(data.heroes, what="load hero trajectories") or []) if h.employee_id == emp), None)

# ------------------------------------------------------------------ header card
with st.container(key="card_head"):
    a, b = st.columns([1.4, 2])
    with a:
        ui.html(
            f'<div class="ss-person">{ui.avatar_img(dept, 64)}<div><div style="font-size:1.6rem;font-weight:600;letter-spacing:-.03em">'
            f'{theme.esc(ui.display_name(emp))}</div><div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">'
            f"{theme.band_chip(s.band, theme.BAND[s.band]['label'] + ' · flagged for review' if s.band == 'high' else None)}"
            f"{theme.basis_tag(s.band_basis)}{theme.contract_tag(s.contract_type)}</div>"
            f'<div style="color:#52514e;font-size:.88rem;margin-top:8px;max-width:420px">{theme.esc(hero.story if hero else "")}</div></div></div>'
        )
    with b:
        ui.html(
            theme.kv(
                [
                    ("Risk (90-day)", f"{s.risk:.3f}"),
                    ("Rank", f"{s.rank} / {s.group_size}" + (" (tied)" if s.rank_is_tied else "")),
                    ("Department", theme.esc(theme.dept_label(dept) if dept else "—")),
                    ("Contract", s.contract_type),
                    ("Model", theme.esc(s.model)),
                    ("Scoring week", s.week_start),
                ]
            )
        )
        st.caption(
            "Role and tenure are not returned by the score API, so they are not shown. Risk is a calibrated probability "
            "on synthetic data; the band is a within-week ranking."
        )

# ------------------------------------------------------------------ season-end callout (separate from resignation framing)
if s.contract_type == "seasonal":
    ui.html(
        theme.banner(
            "<b>Season-end, not resignation.</b> This person is on a seasonal contract, so the band uses the "
            "<b>contract-date rule</b>, not the resignation model. "
            + (
                "The contract end falls inside the 30-day window, so a renewal or retainer decision is due now. "
                if s.band == "high"
                else ""
            )
            + "Days remaining: <i>the API does not expose the contract end date</i>, so it is not shown here.",
            "amber",
            "calendar",
        )
    )

# ------------------------------------------------------------------ trajectory
ui.html(theme.section("Last 12 weeks", "Trajectory"))
if hero and hero.weeks:
    if hero.illustrative:
        st.caption("Illustrative trajectory from heroes.json, anchored to today's live score. The API serves only the current week.")
    xs = [w.week_start for w in hero.weeks]
    t1, t2 = st.columns(2)
    with t1:
        fig = go.Figure(
            go.Scatter(
                x=xs,
                y=[w.risk for w in hero.weeks],
                mode="lines+markers",
                name="risk",
                line=dict(color="#2a78d6", width=2),
                marker=dict(size=9, color=[theme.BAND_COLOR[w.band] for w in hero.weeks], line=dict(color="#fff", width=2)),
                customdata=[[w.band, w.rank] for w in hero.weeks],
                hovertemplate="%{x}<br>risk %{y:.3f}<br>band %{customdata[0]} · rank %{customdata[1]}<extra></extra>",
            )
        )
        for w in hero.weeks:
            if w.note:
                fig.add_annotation(
                    x=w.week_start,
                    y=w.risk,
                    text=w.note,
                    showarrow=True,
                    arrowhead=0,
                    ay=-36,
                    ax=-10,
                    font=dict(size=11, color="#52514e"),
                    bgcolor="#fff",
                    bordercolor="#e6e5e0",
                )
        fig.update_layout(title="Risk score (marker color = band that week)")
        st.plotly_chart(theme.style_fig(fig, 300, legend=False), width="stretch", config={"displayModeBar": False})
    with t2:
        fig = go.Figure(
            go.Scatter(
                x=xs,
                y=[w.rank for w in hero.weeks],
                mode="lines+markers",
                line=dict(color="#52514e", width=2, shape="hv"),
                marker=dict(size=8, color="#52514e", line=dict(color="#fff", width=2)),
                hovertemplate="%{x}<br>rank %{y}<extra></extra>",
            )
        )
        fig.update_layout(title=f"Rank within group (1 = highest risk, of {s.group_size})")
        theme.style_fig(fig, 300, legend=False)
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    if any(w.overtime_hours is not None for w in hero.weeks):
        last = hero.weeks[-1]
        first = hero.weeks[0]
        st.caption(
            f"Overtime moved from {first.overtime_hours} h/week to {last.overtime_hours} h/week over the period; "
            f"weeks since a weekend off: {last.weeks_since_weekend_off}."
        )
else:
    ui.empty(
        "No weekly history is available for this employee. The API serves the current week only; trajectories exist "
        "for the five demo heroes."
    )

# ------------------------------------------------------------------ drivers
ui.html(theme.section("Why this person is flagged", "Drivers", "Contribution to the model's log-odds; bars right of zero push risk up."))
pb = data.playbook()
d1, d2 = st.columns([1.4, 1])
with d1:
    if s.drivers:
        st.plotly_chart(
            charts.driver_bars(s.drivers, height=max(260, 80 * len(s.drivers) + 80)), width="stretch", config={"displayModeBar": False}
        )
    else:
        ui.empty("No active risk drivers." if s.contract_type == "permanent" else "Seasonal: banded by contract date, no driver breakdown.")
with d2:
    st.markdown("**In plain language**", help=theme.SUPPORT_HELP)
    for d in s.drivers:
        expl = (pb.get(d.category) or {}).get("explanation", "")
        ui.html(
            f'<div class="ss-card" style="padding:14px 16px;margin-bottom:8px"><div style="display:flex;justify-content:space-between;gap:8px">'
            f"<b>{theme.esc(d.title)}</b>{theme.support_chip(d.support_level)}</div>"
            f'<div style="font-size:.88rem;margin-top:6px">{theme.esc(d.reason)}</div>'
            f'<div style="font-size:.8rem;color:#6b6a65;margin-top:4px">{theme.esc(expl)}</div></div>'
        )
    mr = pb.get("manager_relationship") or {}
    ui.html(
        f'<div class="ss-card" style="padding:14px 16px;opacity:.75"><div style="display:flex;justify-content:space-between">'
        f'<b>Manager relationship</b>{theme.support_chip("unsupported")}</div><div style="font-size:.8rem;color:#6b6a65;margin-top:4px">'
        f"{theme.esc(mr.get('explanation', 'No manager signal in the data; never shown as a cause.'))}</div></div>"
    )

# ------------------------------------------------------------------ interventions
ui.html(theme.section("Suggested interventions", "Playbook", "Top 2 actions per active driver. Each creates a task for the owner."))
actions = []
for d in s.drivers:
    acts = [a for a in s.actions if a.driver == d.category]
    if not acts:  # fall back to the playbook when the API returned none for this driver
        acts = [api_a for api_a in (pb.get(d.category) or {}).get("actions", [])]
        acts = [
            type(
                "A",
                (),
                {
                    "driver": d.category,
                    "action": x["action"],
                    "owner": x.get("owner", "manager"),
                    "check_after_weeks": x.get("check_after_weeks"),
                    "expected_effect": x.get("expected_effect", ""),
                },
            )
            for x in acts
        ]
    actions += [(d, a) for a in acts[:2]]
if s.contract_type == "seasonal" and not actions:
    actions = [
        (
            None,
            type(
                "A",
                (),
                {
                    "driver": "season_end_exit",
                    "action": x["action"],
                    "owner": x.get("owner", "manager"),
                    "check_after_weeks": x.get("check_after_weeks"),
                    "expected_effect": x.get("expected_effect", ""),
                },
            ),
        )
        for x in (pb.get("season_end_exit") or {}).get("actions", [])[:2]
    ]
if not actions:
    ui.empty("No interventions suggested: there are no active risk drivers.")
created = st.session_state.setdefault("created_tasks", {})
for i, (d, a) in enumerate(actions):
    key = f"ui:{emp}:{a.driver}:{i}"
    with st.container(key=f"card_act_{i}"):
        x, y = st.columns([4, 1.2])
        with x:
            done = key in created
            ui.html(
                f'<div style="display:flex;gap:10px;align-items:flex-start">{theme.icon("check" if done else "flag", 20, "#0ca30c" if done else "#1f6fe5")}'
                f'<div><b>{theme.esc(a.action)}</b><div style="font-size:.8rem;color:#6b6a65">{theme.esc(theme.dept_label(a.driver))} · owner: '
                f"{theme.esc(a.owner)}{f' · check after {a.check_after_weeks} wk' if a.check_after_weeks else ''}</div>"
                f'<div style="font-size:.78rem;color:#6b6a65">{theme.esc(a.expected_effect)}</div></div></div>'
            )
        with y:
            if key in created:
                st.button(f"Task #{created[key]} created", key=f"b_{key}", disabled=True)
            elif st.button("Create task", key=f"b_{key}", type="primary", icon=":material/add_task:"):
                t = ui.safe(
                    api.create_task,
                    key,
                    f"{a.action} ({emp})",
                    a.owner or "manager",
                    employee_id=emp,
                    description=f"Driver: {a.driver}. Expected effect: {a.expected_effect}",
                    due_in_minutes=int((a.check_after_weeks or 1) * 7 * 24 * 60),
                    what="create the task",
                )
                if t:
                    created[key] = t.get("id")
                    st.toast(f"Task #{t.get('id')} created for {a.owner}", icon=":material/task_alt:")
                    st.rerun()
    ui.html(f"<style>.st-key-card_act_{i}{{background:#fff;border-radius:18px;padding:12px 16px;margin-bottom:8px}}</style>")

ui.footer()
