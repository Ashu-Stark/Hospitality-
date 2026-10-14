from collections import Counter
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import api_client as api
from lib import auth, data, models, nav, theme, today, ui
from lib.config import current_settings

ui.setup("pages/5_Roster.py", "Shift plan")
ui.page_head("Shift plan", "Who works which shift this week, and where we are short of people.")


def shortage_prefill(dept: str | None, day: str | None, hours: float = 8.0, source: str = "roster_shortage") -> dict:
    """Fill the Extra staff form from a roster gap: department, that day, about one person per 8 hours short (ASSUMED)."""
    gap = day or date.today().isoformat()
    d = request_day(gap)
    return {
        "department": dept or "housekeeping",
        "date_from": d,
        "date_to": d,
        "openings": max(1, round(hours / 8)),
        "note": f"Shift plan short by about {hours:.0f} hours on {date.fromisoformat(gap).strftime('%A')}.",
        "source": source,
        "gap_day": gap,
    }


def request_day(day: str) -> str:
    """The tourism portal takes requests from today up to 180 days ahead. The demo shift plan is a SYNTHETIC future week
    (2029), so a gap outside that range is asked for on the same weekday in the coming week (the form can still change it)."""
    d, t = date.fromisoformat(day), date.today()
    if t <= d <= t + timedelta(days=180):
        return day
    return (t + timedelta(days=(d.weekday() - t.weekday()) % 7 or 7)).isoformat()


def request_staff_button(pre: dict, key: str) -> None:
    if auth.can_open("pages/20_Extra_Staff.py") and st.button("Request staff", key=key, type="primary", icon=":material/group_add:"):
        st.session_state["staffing_prefill"] = pre
        nav.go("pages/20_Extra_Staff.py")


week0 = data.demo_week() or ui.ensure_demo_week()
s = current_settings()

# ------------------------------------------------------------------ controls (search-bar card)
with st.container(key="card_controls"):
    c1, c4 = st.columns([3, 1], vertical_alignment="bottom")
    with c1:
        opts = data.week_options(week0) if week0 else []
        wk = st.selectbox("Week (starts Monday)", opts, index=0, format_func=ui.week_label) if opts else None
    with c4:
        gen = st.button("Make shift plan", type="primary", icon=":material/auto_awesome:", width="stretch")
    with st.expander("Options"):
        protect = st.toggle(
            "Give a weekend off to people on the check-in list",
            value=False,
            help="People in 'Check in this week' get a full weekend off if possible.",
        )
        infeasible = st.toggle(
            "Practice: show a week without enough people",
            value=False,
            disabled=not s.use_mocks,
            help="Practice data only: see what the page shows when there are not enough people.",
        )

if gen:
    protected = []
    if protect:
        sc = ui.safe(data.scores, ui.week(), what="load the check-in list") or []
        protected = [x.employee_id for x in sc if x.band == "high" and x.contract_type == "permanent"]
    with st.spinner("Making the shift plan… this can take up to 10 seconds."):
        raw = ui.safe(api.generate_roster, None if wk == week0 else wk, protected, True, True, infeasible, what="make the shift plan")
    if raw:
        st.session_state["roster_raw"] = raw
        if raw.get("id"):
            st.session_state["last_roster_id"] = raw["id"]
        data.clear()
        made = models.parse_roster(raw)
        if made is not None and made.status != "infeasible":  # publishing happens here, when the plan is made
            err = data.publish_plan(made)
            ui.flash("Shift plan made and sent to staff phones." if err is None else f"Shift plan made. Not sent to staff: {err}", ok=err is None)

raw = st.session_state.get("roster_raw")
ro: models.Roster | None = models.parse_roster(raw) if raw else None
if ro is None:
    rid = data.current_roster_id()
    if rid is not None:
        ro = ui.safe(data.roster, rid, what="load the shift plan")
if ro is None:
    ui.empty("No shift plan yet. Press Make shift plan.")
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
        or "<li>No reason was given.</li>"
    )
    ui.html(
        theme.banner(
            "<b>Not enough people for this week.</b> "
            "No shift plan was made, because it would break a rule (rest, leave or weekly off). Shifts short of people:"
            f"<ul style='margin:6px 0 0'>{items}</ul>",
            "red",
            "alert",
        )
    )
    c0 = next((c for c in ro.causes if isinstance(c, dict)), {})
    gap = float(c0.get("required") or 1) - float(c0.get("available") or 0)
    request_staff_button(shortage_prefill(c0.get("department"), c0.get("date"), max(8.0, 8 * gap)), "req_staff_infeasible")
    ui.footer()
    st.stop()

# ------------------------------------------------------------------ answer first: where are we short?
cost = ro.cost
fair = [p.get("fairness_score") for p in ro.people if p.get("fairness_score") is not None]
short_n = int(cost.get("understaffed_shifts", 0) or 0)
gaps = sorted(ro.short_by_cell().items(), key=lambda kv: -kv[1])
gaps = [((dpt, i, sh), h) for (dpt, i, sh), h in gaps if h > 0.5 and 0 <= i < len(ro.dates)]
ui.verdict(
    len(gaps),
    ok_text="Every shift has enough people this week.",
    bad_text=f"Short of people on {short_n} shift{'s' if short_n != 1 else ''} this week." if short_n else None,
)
ui.big_numbers(
    [
        (
            "Shifts short of people",
            short_n,
            "Biggest gaps listed below" if short_n else "Every shift has enough people",
            "bad" if short_n else "ok",
        ),
        (
            "Extra pay for overtime",
            ui.inr(cost.get("overtime_cost_inr")),
            f"{sum(1 for p in ro.people if p.get('overtime_hours'))} people work extra",
            "warn" if cost.get("overtime_hours") else "ok",
        ),
        ("Week cost", ui.inr(cost.get("total_cost_inr")), "Wages for the week, incl. overtime", "info"),
    ]
)
if gaps:
    ui.html('<h3 class="ss-h3">Biggest gaps</h3>')
    for n_gap, ((dpt, i, sh), h) in enumerate(gaps[:4]):
        dday = ro.dates[i]
        people_n = today.people_for_hours(ro, sh, h)
        a, b = st.columns([4, 1.3], vertical_alignment="center")
        a.markdown(
            f'<div class="ss-donext"><b>Short of {people_n} {theme.esc(theme.dept_label(dpt).lower())} staff on '
            f"{date.fromisoformat(dday).strftime('%A')} {theme.esc(sh)}</b>"
            f"<span>About {h:.0f} hours not covered ({theme.esc(date.fromisoformat(dday).strftime('%d %b'))}).</span></div>",
            unsafe_allow_html=True,
        )
        with b:
            request_staff_button(shortage_prefill(dpt, dday, h), f"req_staff_gap_{n_gap}")
    if len(gaps) > 4:
        st.caption("Smaller gaps are in Details below.")
if ro.protected_ids:
    st.caption("Weekend off kept free for: " + ", ".join(ui.short_name(e) for e in ro.protected_ids))

# ------------------------------------------------------------------ grid (Details)
details_box = ui.details("Details: people on each shift, every day")
details_box.caption("Each box = number of people on shift. Red or yellow boxes need more people.")
with details_box:
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


details_box.dataframe(grid.style.apply(style_cells, axis=None), width="stretch")
details_box.markdown(
    " ".join(
        [
            theme.band_chip("low", "enough people"),
            theme.band_chip("watch", "a few hours short"),
            theme.band_chip("high", "1 shift or more short"),
        ]
    ),
    unsafe_allow_html=True,
)

with st.expander("Details: who works one shift"):
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
        f'<div style="margin-top:6px"><b>{len(ids)} people</b>'
        + (f" · {theme.band_chip('high', f'{hs:.1f} h short')}" if hs > 0.5 else "")
        + '</div><div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">'
        + "".join(f'<span class="ss-tag">{ui.avatar_img(cd, 20)}{theme.esc(ui.short_name(e))}</span>' for e in ids)
        + "</div>"
    )

# ------------------------------------------------------------------ fairness + soft goals (secondary)
with st.expander("Details: are weekends and nights shared fairly?"):
    f1, f2 = st.columns([1.2, 1])
    with f1:
        ui.html(theme.section("Fair share of weekends and nights", "Per person", "1 = fair share compared with the department."))
        if fair:
            fig = go.Figure(
                go.Histogram(
                    x=fair,
                    nbinsx=12,
                    marker=dict(color="#2a78d6", line=dict(color="#fff", width=2), cornerradius=4),
                    hovertemplate="fair share %{x}<br>%{y} people<extra></extra>",
                )
            )
            st.plotly_chart(theme.style_fig(fig, 260, legend=False), width="stretch", config={"displayModeBar": False})
        else:
            ui.empty("Nothing to show.")
    with f2:
        ui.html(theme.section("Wishes not fully met", "Trade-offs"))
        labels = {
            "understaffed": "shifts short of people",
            "overtime": "people with overtime",
            "weekend_spread": "departments where weekends are not shared fairly",
            "night_spread": "departments where nights are not shared fairly",
            "protected_weekend_off": "people who could not get the full weekend off we asked for",
        }
        counts = Counter(g.get("goal") for g in ro.violated_soft_goals)
        if not counts:
            ui.html(theme.banner("All wishes met.", "blue", "check"))
        for goal, n in counts.most_common():
            ui.html(
                f'<div class="ss-card" style="padding:12px 16px;margin-bottom:8px;display:flex;justify-content:space-between">'
                f"<span>{theme.esc(labels.get(goal, models.pretty(goal)))}</span><b>{n}</b></div>"
            )
        over = [g for g in ro.violated_soft_goals if g.get("goal") == "protected_weekend_off"]
        if over:
            st.caption("Could not give a weekend off to: " + ", ".join(ui.short_name(g.get("employee_id")) for g in over))
        if ro.hard_violations:
            ui.html(theme.banner(f"{len(ro.hard_violations)} rule(s) broken (rest, leave or weekly off).", "red", "alert"))

# ------------------------------------------------------------------ before vs with weekends off (secondary)
with st.expander("Details: compare two shift plans"):
    ui.html(theme.section("Before and with weekends off", "Compare", "Plans from the Support plan page, or any two plan numbers."))
    loop = st.session_state.get("loop_raw") or {}
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        base_id = st.number_input("First plan number", min_value=0, step=1, value=int(loop.get("baseline_roster_id") or 0))
    with c2:
        prot_id = st.number_input("Plan with weekends off (number)", min_value=0, step=1, value=int(loop.get("protected_roster_id") or 0))
    with c3:
        ui.html('<div style="height:26px"></div>')
        compare = st.button("Compare", icon=":material/compare_arrows:", disabled=not (base_id and prot_id))
    if not loop:
        st.caption("Tip: use the Support plan page once and both numbers are filled in for you.")
    if compare or (loop and base_id and prot_id):
        rb = ui.safe(data.roster, base_id, what="load the first plan")
        rp = ui.safe(data.roster, prot_id, what="load the second plan")
        if rb and rp:
            rows = []
            for label, r in (("Before", rb), ("With weekends off", rp)):
                rows.append(
                    {
                        "Shift plan": f"{label} #{r.id}",
                        "Shifts filled": r.coverage_ratio,
                        "Total cost ₹": r.cost.get("total_cost_inr"),
                        "Overtime hours": r.cost.get("overtime_hours"),
                        "Shifts short of people": r.cost.get("understaffed_shifts"),
                        "Weekends off given": len(r.protected_ids),
                    }
                )
            st.dataframe(
                pd.DataFrame(rows).style.format({"Shifts filled": "{:.1%}", "Total cost ₹": "{:,.0f}"}), hide_index=True, width="stretch"
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
                            "Before": ab.get(k, "off"),
                            "With weekends off": ap.get(k, "off"),
                            "Weekend off asked": "yes" if k[0] in rp.protected_ids else "",
                        }
                    )
            st.markdown(
                f"**{len(changes)} shift changes** between the two plans"
                + (f", {sum(1 for c in changes if c['Weekend off asked'])} of them for people given a weekend off." if changes else ".")
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
