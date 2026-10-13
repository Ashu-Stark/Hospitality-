from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import charts, data, theme, ui
from lib.config import current_settings

ui.setup("pages/1_Overview.py", "Overview")
ui.page_head("Week numbers", "Money, shifts and how full we'll be this week.")
rc = int(st.session_state.get("replacement_cost", current_settings().replacement_cost_inr))
m = ui.safe(data.metrics, float(rc), what="load this week's numbers")
if m:
    on_time = ui.pct(m.tasks_on_time_rate) if m.tasks_on_time_rate is not None else "—"
    ui.big_numbers(
        [
            (
                "Shifts short of people",
                m.understaffed_shifts,
                f"Shift plan cost {ui.inr(m.total_roster_cost_inr)}",
                "bad" if m.understaffed_shifts else "ok",
            ),
            ("Overtime", f"{m.overtime_hours:,.0f} h", f"{ui.inr(m.overtime_cost_inr)} extra pay", "warn" if m.overtime_hours else "ok"),
            ("Tasks on time", on_time, f"of {m.tasks_total} tasks", "info"),
            ("Money at stake", ui.inr(m.roi_inr), f"{m.flagged_still_employed} people to check in with × cost of replacing one", "info"),
        ]
    )
    if m.roster_id is None:
        st.caption("No shift plan yet. Make one on the Shift plan page to fill these numbers.")
with st.expander("Change the cost used here"):
    rc_new = st.number_input(
        "Cost of replacing one person who leaves (₹, our guess)",
        min_value=0,
        step=5000,
        value=rc,
        help="Money at stake = people to check in with × this cost.",
    )
    if rc_new != rc:
        st.session_state["replacement_cost"] = rc_new
        st.rerun()
    if m and m.roi_note:
        st.caption(m.roi_note)

# ------------------------------------------------------------------ forecast (the one chart)
week = data.demo_week() or ui.ensure_demo_week()
scores = ui.safe(data.scores, ui.week(), what="load the check-in list") or []
ui.html('<h3 class="ss-h3">How full will we be?</h3>')
if week:
    d0 = date.fromisoformat(week)
    fc = ui.safe(data.forecast, d0.isoformat(), (d0 + timedelta(days=6)).isoformat(), what="load how full we'll be")
    if fc and fc.days:
        busiest = max(fc.days, key=lambda d: d.mean)
        ui.takeaway(f"Busiest day: {date.fromisoformat(busiest.date).strftime('%A %d %b')}, about {busiest.mean:.0%} of rooms full.")
        st.plotly_chart(charts.forecast_band(fc, 280), width="stretch", config={"displayModeBar": False})
        st.caption("Shaded area = likely range. Right on about 2 of 3 past days, so use it as a guide.")
    elif fc:
        ui.empty("No days to show for this week.")
else:
    ui.empty("We could not find the week. Press Refresh.")

# ------------------------------------------------------------------ department table
ui.html('<h3 class="ss-h3">Departments</h3>')
rid = m.roster_id if m else None
rid = rid or st.session_state.get("last_roster_id")
if rid is None:
    ui.empty("Make a shift plan first to see each department.")
    if st.button("Make the shift plan for this week", type="primary", icon=":material/calendar_month:"):
        with st.spinner("Making the shift plan (about 10 seconds)…"):
            r = ui.safe(api.generate_roster, week, what="make the shift plan")
        if r:
            st.session_state["last_roster_id"] = r.get("id")
            data.clear()
            st.rerun()
else:
    ro = ui.safe(data.roster, rid, what="load the shift plan")
    if ro:
        dept = ro.dept_of
        flagged = {}
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
                    "Department": theme.dept_label(d),
                    "People": heads.get(d, 0),
                    "Workload": ratio,
                    "Shifts filled": c.get("coverage"),
                    "Shifts short of people": c.get("understaffed_shifts"),
                    "Check in this week": flagged.get(d, 0),
                }
            )
        df = pd.DataFrame(rows)

        def color_ratio(v):
            b = theme.BAND[theme.load_tone(v)]
            return f"background-color:{b['bg']};color:{b['fg']};font-weight:600"

        df["Shifts filled"] = df["Shifts filled"].map(lambda v: f"{v:.0%}" if v is not None else "—")
        df["Workload"] = df["Workload"].map(lambda v: f"{v:.2f}" if v is not None else "—")
        ui.table(df, ["Department", "People", "Shifts short of people", "Check in this week"], key="ov_dept")
        st.caption("Workload = hours needed ÷ hours planned. Above 1.10 means too few people.")

ui.footer()
