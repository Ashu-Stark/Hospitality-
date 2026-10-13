import plotly.graph_objects as go
import streamlit as st

from lib import api_client as api
from lib import charts, data, theme, ui
from lib.models import PLAIN_REASON

ui.setup("pages/3_Employee_Detail.py", "Employee")

scores = ui.safe(data.scores, ui.week(), what="load the check-in list")
if not scores:
    if scores is not None:
        ui.empty("Nothing to show yet.")
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
        "Person (search by ID or name)",
        options,
        index=options.index(default) if default in options else 0,
        format_func=ui.display_name,
    )
st.session_state["selected_employee"] = emp
with c_hint:
    ui.html(
        '<div style="height:26px"></div>'
        + " ".join(f'<span class="ss-tag" style="margin-right:4px">{theme.esc(n)}</span>' for n in names.values())
        + '<span style="color:#6b6a65;font-size:.78rem;margin-left:6px">example people · everyone else is shown by ID only</span>'
    )

s = by_id[emp]
dept = data.dept_map().get(emp)
hero = next((h for h in (ui.safe(data.heroes, what="load the last 12 weeks") or []) if h.employee_id == emp), None)

# ------------------------------------------------------------------ header card
with st.container(key="card_head"):
    a, b = st.columns([1.4, 2])
    with a:
        ui.html(
            f'<div class="ss-person">{ui.avatar_img(dept, 64)}<div><div style="font-size:1.6rem;font-weight:600;letter-spacing:-.03em">'
            f'{theme.esc(ui.display_name(emp))}</div><div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">'
            f"{theme.band_chip(s.band)}"
            f"{theme.basis_tag(s.band_basis)}{theme.contract_tag(s.contract_type)}</div>"
            f'<div style="color:#52514e;font-size:.88rem;margin-top:8px;max-width:420px">{theme.esc(hero.story if hero else "")}</div></div></div>'
        )
    with b:
        ui.html(
            theme.kv(
                [
                    ("Chance of leaving (90 days)", f"{s.risk:.0%}"),
                    ("Place in team", f"{s.rank} of {s.group_size}" + (" (shared)" if s.rank_is_tied else "")),
                    ("Department", theme.esc(theme.dept_label(dept) if dept else "—")),
                    ("Contract", s.contract_type),
                    ("Week", s.week_start),
                ]
            )
        )

# ------------------------------------------------------------------ season-end callout (separate from resignation framing)
if s.contract_type == "seasonal":
    ui.html(
        theme.banner(
            "<b>Season contract.</b> This person is grouped by when their contract ends. "
            + ("It ends within 30 days, so decide now whether to keep them on. " if s.band == "high" else ""),
            "amber",
            "calendar",
        )
    )

# ------------------------------------------------------------------ trajectory (secondary)
with ui.details("Details: last 12 weeks"):
    if hero and hero.weeks:
        if hero.illustrative:
            st.caption("Example history, to show how it works.")
        xs = [w.week_start for w in hero.weeks]
        t1, t2 = st.columns(2)
        with t1:
            fig = go.Figure(
                go.Scatter(
                    x=xs,
                    y=[w.risk for w in hero.weeks],
                    mode="lines+markers",
                    name="chance",
                    line=dict(color="#2a78d6", width=2),
                    marker=dict(size=9, color=[theme.BAND_COLOR[w.band] for w in hero.weeks], line=dict(color="#fff", width=2)),
                    customdata=[[w.band, w.rank] for w in hero.weeks],
                    hovertemplate="%{x}<br>chance %{y:.0%}<br>place %{customdata[1]}<extra></extra>",
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
            fig.update_layout(title="Chance of leaving (dot color = group that week)")
            fig.update_yaxes(tickformat=".0%")
            st.plotly_chart(theme.style_fig(fig, 300, legend=False), width="stretch", config={"displayModeBar": False})
        with t2:
            fig = go.Figure(
                go.Scatter(
                    x=xs,
                    y=[w.rank for w in hero.weeks],
                    mode="lines+markers",
                    line=dict(color="#52514e", width=2, shape="hv"),
                    marker=dict(size=8, color="#52514e", line=dict(color="#fff", width=2)),
                    hovertemplate="%{x}<br>place %{y}<extra></extra>",
                )
            )
            fig.update_layout(title=f"Place in team (1 = most likely to leave, of {s.group_size})")
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
        ui.empty("No weekly history for this person yet.")

# ------------------------------------------------------------------ drivers
ui.html('<h3 class="ss-h3">Why this person may need support</h3>')
if s.drivers:
    ui.takeaway(f"Biggest reason: {max(s.drivers, key=lambda d: d.contribution_logodds).title}.")
pb = data.playbook()
if not s.drivers:
    ui.empty("No reasons to show." if s.contract_type == "permanent" else "Season contract: grouped by when it ends, no list of reasons.")
for d in sorted(s.drivers, key=lambda d: -d.contribution_logodds):
    expl = (pb.get(d.category) or {}).get("explanation", "")
    ui.html(
        f'<div class="ss-card" style="padding:14px 16px;margin-bottom:8px"><div style="display:flex;justify-content:space-between;gap:8px">'
        f"<b>{theme.esc(d.title)}</b>{theme.support_chip(d.support_level)}</div>"
        f'<div style="font-size:.92rem;margin-top:6px">{theme.esc(d.reason)}</div>'
        f'<div style="font-size:.8rem;color:#6b6a65;margin-top:4px">{theme.esc(expl)}</div></div>'
    )
ui.html(
    '<div class="ss-card" style="padding:14px 16px;opacity:.75;margin-bottom:8px"><div style="display:flex;justify-content:space-between">'
    f'<b>Trouble with the manager</b>{theme.support_chip("unsupported")}</div><div style="font-size:.8rem;color:#6b6a65;margin-top:4px">'
    "We cannot see this in the numbers, so it is never shown as a reason. Ask the person.</div></div>"
)
if s.drivers:
    with ui.details("Details: how much each reason counts"):
        st.caption(theme.SUPPORT_HELP)
        st.plotly_chart(
            charts.driver_bars(s.drivers, height=max(260, 80 * len(s.drivers) + 80)), width="stretch", config={"displayModeBar": False}
        )

# ------------------------------------------------------------------ interventions
ui.html('<h3 class="ss-h3">What could help</h3>')
st.caption("Suggested next steps, up to two for each reason. Each one can become a task.")
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
    ui.empty("No next steps: there are no reasons to act on.")
created = st.session_state.setdefault("created_tasks", {})
for i, (d, a) in enumerate(actions):
    key = f"ui:{emp}:{a.driver}:{i}"
    with st.container(key=f"card_act_{i}"):
        x, y = st.columns([4, 1.2])
        with x:
            done = key in created
            ui.html(
                f'<div style="display:flex;gap:10px;align-items:flex-start">{theme.icon("check" if done else "flag", 20, "#0ca30c" if done else "#1f6fe5")}'
                f'<div><b>{theme.esc(a.action)}</b><div style="font-size:.8rem;color:#6b6a65">'
                f"{theme.esc(PLAIN_REASON.get(a.driver) or theme.dept_label(a.driver))} · who: "
                f"{theme.esc(a.owner)}{f' · check again in {a.check_after_weeks} weeks' if a.check_after_weeks else ''}</div></div></div>"
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
                    description=f"Reason: {PLAIN_REASON.get(a.driver) or a.driver}.",
                    due_in_minutes=int((a.check_after_weeks or 1) * 7 * 24 * 60),
                    what="create the task",
                )
                if t:
                    created[key] = t.get("id")
                    st.toast(f"Task #{t.get('id')} created for {a.owner}", icon=":material/task_alt:")
                    st.rerun()
    ui.html(f"<style>.st-key-card_act_{i}{{background:#fff;border-radius:18px;padding:12px 16px;margin-bottom:8px}}</style>")

ui.footer()
