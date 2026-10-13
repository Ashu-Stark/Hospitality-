from collections import Counter
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import api_client as api
from lib import auth, data, models, nav, theme, ui
from lib.config import current_settings

ui.setup("pages/5_Roster.py", "Roster")
ui.page_head(
    "Weekly roster", "Who works which shift this week. The solver keeps rest, leave, weekly offs and skills; you see any gaps first."
)


def shortage_prefill(dept: str | None, day: str | None, hours: float = 8.0, source: str = "roster_shortage") -> dict:
    """Fill the Extra staff form from a roster gap: department, that day, about one person per 8 hours short (ASSUMED)."""
    d = day or date.today().isoformat()
    return {
        "department": dept or "housekeeping",
        "date_from": d,
        "date_to": d,
        "openings": max(1, round(hours / 8)),
        "note": f"Roster short by about {hours:.0f} h on {d}.",
        "source": source,
    }


def request_staff_button(pre: dict, key: str) -> None:
    if auth.can_open("pages/20_Extra_Staff.py") and st.button("Request staff", key=key, type="primary", icon=":material/group_add:"):
        st.session_state["staffing_prefill"] = pre
        st.switch_page(nav.page("pages/20_Extra_Staff.py"))


week0 = data.demo_week() or ui.ensure_demo_week()
s = current_settings()

# ------------------------------------------------------------------ controls (search-bar card)
with st.container(key="card_controls"):
    c1, c4 = st.columns([3, 1], vertical_alignment="bottom")
    with c1:
        opts = data.week_options(week0) if week0 else []
        wk = st.selectbox("Week starting (Monday)", opts, index=0, help="Defaults to the cached demo week.") if opts else None
    with c4:
        gen = st.button("Make roster", type="primary", icon=":material/auto_awesome:", width="stretch")
    with st.expander("Options"):
        protect = st.toggle(
            "Give flagged staff a weekend off",
            value=False,
            help="Passes the high-band permanent staff as protected_ids, so the solver gives them a weekend off.",
        )
        infeasible = st.toggle(
            "Practice: show a week that cannot be staffed",
            value=False,
            disabled=not s.use_mocks,
            help="MOCK only: rehearse how the page reports a week that cannot be staffed under the hard rules.",
        )

if gen:
    protected = []
    if protect:
        sc = ui.safe(data.scores, ui.week(), what="load scores for protection") or []
        protected = [x.employee_id for x in sc if x.band == "high" and x.contract_type == "permanent"]
    with st.spinner("Solving… the CP-SAT solver may use its full 10-second limit."):
        raw = ui.safe(api.generate_roster, None if wk == week0 else wk, protected, True, True, infeasible, what="generate the roster")
    if raw:
        st.session_state["roster_raw"] = raw
        if raw.get("id"):
            st.session_state["last_roster_id"] = raw["id"]
        data.clear()

raw = st.session_state.get("roster_raw")
ro: models.Roster | None = models.parse_roster(raw) if raw else None
if ro is None:
    rid = data.current_roster_id()
    if rid is not None:
        ro = ui.safe(data.roster, rid, what=f"load roster {rid}")
if ro is None:
    ui.empty("No roster yet. Press Make roster.")
    ui.footer()
    st.stop()

# ------------------------------------------------------------------ infeasible: honest red banner, no fake roster
if not ro.feasible:
    items = (
        "".join(
            f"<li><b>{theme.esc(theme.dept_label(c.get('department')))}</b> · {theme.esc(c.get('date') or c.get('day'))} · "
            f"{theme.esc(c.get('shift', ''))}: {theme.esc(c.get('reason', ''))}"
            + (f" (needs {c.get('required')}, {c.get('available')} available)" if c.get("required") is not None else "")
            + "</li>"
            if isinstance(c, dict)
            else f"<li>{theme.esc(c)}</li>"
            for c in ro.causes
        )
        or "<li>No cause was reported.</li>"
    )
    ui.html(
        theme.banner(
            f"<b>This week cannot be staffed under the hard rules (status: {theme.esc(ro.status)}).</b> "
            f"No roster was published, because a partial one would break a rule. Short shifts:<ul style='margin:6px 0 0'>{items}</ul>",
            "red",
            "alert",
        )
    )
    c0 = next((c for c in ro.causes if isinstance(c, dict)), {})
    gap = float(c0.get("required") or 1) - float(c0.get("available") or 0)
    request_staff_button(shortage_prefill(c0.get("department"), c0.get("date"), max(8.0, 8 * gap)), "req_staff_infeasible")
    ui.footer()
    st.stop()

# ------------------------------------------------------------------ summary first
cost = ro.cost
fair = [p.get("fairness_score") for p in ro.people if p.get("fairness_score") is not None]
short_n = int(cost.get("understaffed_shifts", 0) or 0)
ui.big_numbers(
    [
        (
            "Shifts covered",
            ui.pct(ro.coverage_ratio, 0),
            "of the hours the forecast needs",
            "ok" if (ro.coverage_ratio or 0) >= 0.97 else "warn",
        ),
        (
            "Short shifts",
            short_n,
            f"{cost.get('understaffed_hours', 0):,.0f} hours without enough people" if short_n else "Every shift has enough people",
            "bad" if short_n else "ok",
        ),
        (
            "Overtime",
            f"{cost.get('overtime_hours', 0):,.0f} h",
            f"{sum(1 for p in ro.people if p.get('overtime_hours'))} people work extra",
            "warn" if cost.get("overtime_hours") else "ok",
        ),
        ("Week cost", ui.inr(cost.get("total_cost_inr")), f"incl. overtime {ui.inr(cost.get('overtime_cost_inr'))}", "info"),
    ]
)
if short_n:
    worst = max(ro.short_by_cell().items(), key=lambda kv: kv[1], default=None)
    if worst:
        (wd, wi, wsh), wh = worst
        wday = ro.dates[wi] if 0 <= wi < len(ro.dates) else None
        ui.html(
            theme.banner(
                f"<b>Short: {theme.esc(theme.dept_label(wd))}</b>, {theme.esc(wday or '')} {theme.esc(wsh)} shift, about {wh:.0f} h. "
                "You can ask local staffing partners for help.",
                "amber",
                "alert",
            )
        )
        request_staff_button(shortage_prefill(wd, wday, wh), "req_staff_short")
if ro.protected_ids:
    st.caption("Weekend off protected for: " + ", ".join(ui.short_name(e) for e in ro.protected_ids))
with st.expander("Solver details"):
    st.caption(f"{ro.method} · {ro.status} · roster #{ro.id} · solved in {(ro.solve_seconds or 0):.1f} s")

# ------------------------------------------------------------------ grid
ui.takeaway(
    "Each cell = people assigned. Red or amber cells are short of hours." if short_n else "Every department is fully covered this week."
)
shift = st.segmented_control("Shift", ["All shifts"] + models.SHIFT_ORDER, default="All shifts")
dates = ro.dates
people = ro.cell_people()
short = ro.short_by_cell()
depts = [c.get("department") for c in ro.coverage] or sorted({k[0] for k in people})
shifts = models.SHIFT_ORDER if shift in (None, "All shifts") else [shift]
cell_txt, cell_tone = {}, {}
for dpt in depts:
    for i, d in enumerate(dates):
        n = sum(len(people.get((dpt, d, sh), [])) for sh in shifts)
        h = sum(short.get((dpt, i, sh), 0) for sh in shifts)
        cell_txt[(dpt, d)] = f"{n}" + (f"  (−{h:.0f}h)" if h > 0.5 else "")
        cell_tone[(dpt, d)] = "high" if h > 9 else "watch" if h > 0.5 else "low"
day_cols = [f"{models.DAY_NAMES[date.fromisoformat(d).weekday()]} {date.fromisoformat(d).day}" for d in dates]
grid = pd.DataFrame([[cell_txt[(dpt, d)] for d in dates] for dpt in depts], index=[theme.dept_label(x) for x in depts], columns=day_cols)
tones = pd.DataFrame([[cell_tone[(dpt, d)] for d in dates] for dpt in depts], index=grid.index, columns=day_cols)


def style_cells(_):
    return tones.map(lambda t: f"background-color:{theme.BAND[t]['bg']};color:{theme.BAND[t]['fg']};font-weight:600")


st.dataframe(grid.style.apply(style_cells, axis=None), width="stretch")
ui.html(
    " ".join(
        [theme.band_chip("low", "fully covered"), theme.band_chip("watch", "< 1 shift short"), theme.band_chip("high", "≥ 1 shift short")]
    )
)

with st.expander("Look inside one shift"):
    a, b, c = st.columns(3)
    with a:
        cd = st.selectbox("Department", depts, format_func=theme.dept_label)
    with b:
        cday = st.selectbox("Day", dates, format_func=lambda d: f"{models.DAY_NAMES[date.fromisoformat(d).weekday()]} {d}")
    with c:
        csh = st.selectbox("Shift", models.SHIFT_ORDER)
    ids = people.get((cd, cday, csh), [])
    hs = short.get((cd, dates.index(cday), csh), 0)
    ui.html(
        f'<div style="margin-top:6px"><b>{len(ids)} assigned</b>'
        + (f" · {theme.band_chip('high', f'{hs:.1f} h short')}" if hs > 0.5 else "")
        + '</div><div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">'
        + "".join(f'<span class="ss-tag">{ui.avatar_img(cd, 20)}{theme.esc(ui.short_name(e))}</span>' for e in ids)
        + "</div>"
    )

# ------------------------------------------------------------------ fairness + soft goals (secondary)
with st.expander("Fairness and trade-offs"):
    f1, f2 = st.columns([1.2, 1])
    with f1:
        ui.html(theme.section("Fairness distribution", "Per person", "Weekend & night duty spread vs department average (1 = fairest)."))
        if fair:
            fig = go.Figure(
                go.Histogram(
                    x=fair,
                    nbinsx=12,
                    marker=dict(color="#2a78d6", line=dict(color="#fff", width=2), cornerradius=4),
                    hovertemplate="score %{x}<br>%{y} people<extra></extra>",
                )
            )
            st.plotly_chart(theme.style_fig(fig, 260, legend=False), width="stretch", config={"displayModeBar": False})
        else:
            ui.empty("No fairness scores returned.")
    with f2:
        ui.html(theme.section("Soft goals not fully met", "Trade-offs"))
        labels = {
            "understaffed": "shifts understaffed",
            "overtime": "people with overtime",
            "weekend_spread": "departments with uneven weekend duty",
            "night_spread": "departments with uneven night duty",
            "protected_weekend_off": "protected people who could not get a full weekend off",
        }
        counts = Counter(g.get("goal") for g in ro.violated_soft_goals)
        if not counts:
            ui.html(theme.banner("All soft goals met.", "blue", "check"))
        for goal, n in counts.most_common():
            ui.html(
                f'<div class="ss-card" style="padding:12px 16px;margin-bottom:8px;display:flex;justify-content:space-between">'
                f"<span>{theme.esc(labels.get(goal, models.pretty(goal)))}</span><b>{n}</b></div>"
            )
        over = [g for g in ro.violated_soft_goals if g.get("goal") == "protected_weekend_off"]
        if over:
            st.caption("Could not protect: " + ", ".join(ui.short_name(g.get("employee_id")) for g in over))
        if ro.hard_violations:
            ui.html(theme.banner(f"{len(ro.hard_violations)} hard-rule violations reported.", "red", "alert"))

# ------------------------------------------------------------------ baseline vs protected (secondary)
with st.expander("Compare two rosters"):
    ui.html(theme.section("Baseline vs protected", "Compare", "Rosters from the closed loop, or any two roster IDs."))
    loop = st.session_state.get("loop_raw") or {}
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        base_id = st.number_input("Baseline roster ID", min_value=0, step=1, value=int(loop.get("baseline_roster_id") or 0))
    with c2:
        prot_id = st.number_input("Protected roster ID", min_value=0, step=1, value=int(loop.get("protected_roster_id") or 0))
    with c3:
        ui.html('<div style="height:26px"></div>')
        compare = st.button("Compare", icon=":material/compare_arrows:", disabled=not (base_id and prot_id))
    if not loop:
        st.caption("Tip: run the Closed loop page once and the two roster IDs are filled in for you.")
    if compare or (loop and base_id and prot_id):
        rb = ui.safe(data.roster, base_id, what=f"load roster {base_id}")
        rp = ui.safe(data.roster, prot_id, what=f"load roster {prot_id}")
        if rb and rp:
            rows = []
            for label, r in (("Baseline", rb), ("Protected", rp)):
                rows.append(
                    {
                        "Roster": f"{label} #{r.id}",
                        "Coverage": r.coverage_ratio,
                        "Total cost ₹": r.cost.get("total_cost_inr"),
                        "Overtime h": r.cost.get("overtime_hours"),
                        "Understaffed shifts": r.cost.get("understaffed_shifts"),
                        "Protected": len(r.protected_ids),
                    }
                )
            st.dataframe(
                pd.DataFrame(rows).style.format({"Coverage": "{:.1%}", "Total cost ₹": "{:,.0f}"}), hide_index=True, width="stretch"
            )
            ab = {(a["employee_id"], a["date"]): a["shift"] for a in rb.assignments}
            ap = {(a["employee_id"], a["date"]): a["shift"] for a in rp.assignments}
            changes = []
            for k in sorted(set(ab) | set(ap)):
                if ab.get(k) != ap.get(k):
                    changes.append(
                        {
                            "Role": ui.avatar_uri(rp.dept_of.get(k[0]) or rb.dept_of.get(k[0])),
                            "Employee": ui.short_name(k[0]),
                            "Date": k[1],
                            "Baseline": ab.get(k, "off"),
                            "Protected": ap.get(k, "off"),
                            "Protected person": "yes" if k[0] in rp.protected_ids else "",
                        }
                    )
            st.markdown(
                f"**{len(changes)} shift changes** between the two rosters"
                + (f", {sum(1 for c in changes if c['Protected person'])} of them for protected people." if changes else ".")
            )
            if changes:
                st.dataframe(
                    pd.DataFrame(changes),
                    hide_index=True,
                    width="stretch",
                    height=300,
                    column_config={"Role": st.column_config.ImageColumn("Role", width="small")},
                )

ui.footer()
