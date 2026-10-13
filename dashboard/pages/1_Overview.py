"""Week numbers: how full we will be (one simple bar chart), where shifts are short, and what the week costs.
Answer first; the older technical views (likely-range chart, department table, cost assumption) sit under Details."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import charts, data, tenancy, theme, today, ui
from lib.config import current_settings

ui.setup("pages/1_Overview.py", "Overview")
ui.page_head("Week numbers", "How full we will be, where we are short of people, and what the week costs.")
ROOMS = tenancy.rooms()
rc = int(st.session_state.get("replacement_cost", current_settings().replacement_cost_inr))
week = data.demo_week() or ui.ensure_demo_week()

# ------------------------------------------------------------------ how full (the one chart)
answer = st.empty()  # the answer line sits above the chart; reserved now so it does not push the page later
answer.markdown('<div class="ss-verdict" style="background:#fff;color:#9b9a96">Loading the week…</div>', unsafe_allow_html=True)
ui.html('<h3 class="ss-h3">How full will we be?</h3>')
fc = None
if week:
    d0 = date.fromisoformat(week)
    fc = ui.safe(data.forecast, d0.isoformat(), (d0 + timedelta(days=6)).isoformat(), what="load how full we'll be")
if fc and fc.days:
    days = [date.fromisoformat(x.date) for x in fc.days]
    full = [round(x.mean * ROOMS) for x in fc.days]
    bi = max(range(len(full)), key=lambda i: full[i])
    with answer.container():
        ui.html(
            f'<div class="ss-verdict ok" style="background:#eaf2fe;color:#123a8a">{theme.icon("bed", 22)}'
            f"<span>Busiest day: {days[bi].strftime('%A %d %b')}, about {full[bi]} of {ROOMS} rooms full.</span></div>"
        )
    ui.simple_bars(
        [x.strftime("%a %d") for x in days],
        full,
        highlight=bi,
        fmt="{:.0f} rooms",
        hover="%{x}: about %{y} rooms full",
        y_max=ROOMS * 1.12,
    )
    st.caption(f"Rooms likely full each night (of {ROOMS}). A guess from past bookings, right on about 2 of 3 past days.")
    with ui.details("Details: likely range"):
        st.plotly_chart(charts.forecast_band(fc, 280), width="stretch", config={"displayModeBar": False})
        st.caption("Shaded area = likely range (as a share of rooms). Triangles mark very busy or quiet days.")
else:
    answer.empty()
    ui.empty("We could not load how full we will be this week. Press Refresh.")

# ------------------------------------------------------------------ shifts and money
ui.html('<h3 class="ss-h3">Shifts and money</h3>')
m = ui.safe(data.metrics, float(rc), what="load this week's numbers")
rid = (m.roster_id if m else None) or st.session_state.get("last_roster_id")
ro = ui.safe(data.roster, rid, what="load the shift plan") if rid is not None else None
if m:
    cells = [((dpt, i, sh), h) for (dpt, i, sh), h in (ro.short_by_cell().items() if ro else []) if h > 0.5]
    hours_short = sum(h for _, h in cells)
    one = sum(1 for (_, _, sh), h in cells if today.people_for_hours(ro, sh, h) == 1)
    ui.big_numbers(
        [
            (
                "Shift slots short of people",
                m.understaffed_shifts,
                f"About {hours_short:,.0f} hours short in all"
                if cells
                else ("See the shift plan" if m.understaffed_shifts else "Every shift has enough people"),
                "warn" if m.understaffed_shifts else "ok",
            ),
            (
                "Extra pay for overtime",
                ui.inr(m.overtime_cost_inr),
                f"{m.overtime_hours:,.0f} hours of overtime",
                "warn" if m.overtime_hours else "ok",
            ),
            ("Shift plan cost", ui.inr(m.total_roster_cost_inr), "Wages for the week, incl. overtime", "info"),
        ]
    )
    if cells:
        gap_words = "Each needs only 1 more person." if one == len(cells) else f"{one} of {len(cells)} need only 1 more person."
        ui.takeaway(
            f"These are shift slots with fewer people than ideal, not broken rules. {gap_words}"
            if ro and not ro.hard_violations
            else f"These are shift slots with fewer people than ideal. {gap_words}"
        )
    if m.roster_id is None:
        st.caption("No shift plan yet. Make one on the Shift plan page to fill these numbers.")

# ------------------------------------------------------------------ where we are short (plain sentences; table under Details)
scores = ui.safe(data.scores, ui.week(), what="load the check-in list") or []
if rid is None:
    ui.empty("Make a shift plan first to see each team.")
    if st.button("Make the shift plan for this week", type="primary", icon=":material/calendar_month:"):
        with st.spinner("Making the shift plan (about 10 seconds)…"):
            r = ui.safe(api.generate_roster, week, what="make the shift plan")
        if r:
            st.session_state["last_roster_id"] = r.get("id")
            data.clear()
            st.rerun()
else:
    if ro:
        short = sorted((c for c in ro.coverage if c.get("understaffed_shifts")), key=lambda c: -c["understaffed_shifts"])
        if short:
            ui.takeaway(
                "Short of people most in: "
                + ", ".join(f"{theme.dept_label(c['department'])} ({c['understaffed_shifts']} shifts)" for c in short[:3])
                + "."
            )
        else:
            ui.takeaway("Every team has enough people this week.")
        with ui.details("Details: each team, and the cost guess"):
            dept = ro.dept_of
            flagged: dict[str, int] = {}
            for s in scores:
                if s.band == "high":
                    k = dept.get(s.employee_id, "unknown")
                    flagged[k] = flagged.get(k, 0) + 1
            heads = pd.Series(list(dept.values())).value_counts().to_dict()
            rows = []
            for c in ro.coverage:
                d = c.get("department")
                ratio = (c.get("required_hours", 0) / c["scheduled_hours"]) if c.get("scheduled_hours") else None
                rows.append(
                    {
                        "Team": theme.dept_label(d),
                        "People": heads.get(d, 0),
                        "Shifts short of people": c.get("understaffed_shifts"),
                        "Hours needed for each hour planned": "—" if ratio is None else f"{ratio:.2f}",
                        "Hours filled": "—" if c.get("coverage") is None else f"{c['coverage']:.0%}",
                        "Check in this week": flagged.get(d, 0),
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption("Above 1.10 hours needed for each hour planned means too few people.")
            if m:
                st.markdown(
                    f"**Cost if {m.flagged_still_employed} people leave: about {ui.inr(m.roi_inr)}** "
                    f"({m.flagged_still_employed} people to check in with × {ui.inr(rc)}, our guess of the cost of replacing one person)."
                )
                rc_new = st.number_input("Cost of replacing one person who leaves (₹, our guess)", min_value=0, step=5000, value=rc)
                if rc_new != rc:
                    st.session_state["replacement_cost"] = rc_new
                    st.rerun()
                if m.roi_note:
                    st.caption(m.roi_note)
                if m.tasks_on_time_rate is not None:
                    st.caption(f"Tasks on time this week: {ui.pct(m.tasks_on_time_rate)} of {m.tasks_total}.")

ui.footer()
