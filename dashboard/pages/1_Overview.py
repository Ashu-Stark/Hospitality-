from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import charts, data, theme, ui
from lib.config import current_settings

ui.setup("pages/1_Overview.py", "Overview")
ui.page_head("Week numbers", "Cost, coverage and demand for this week, in plain numbers.")
rc = int(st.session_state.get("replacement_cost", current_settings().replacement_cost_inr))
m = ui.safe(data.metrics, float(rc), what="load overview metrics")
if m:
    on_time = ui.pct(m.tasks_on_time_rate) if m.tasks_on_time_rate is not None else "—"
    ui.big_numbers(
        [
            (
                "Short shifts",
                m.understaffed_shifts,
                f"Roster cost {ui.inr(m.total_roster_cost_inr)}",
                "bad" if m.understaffed_shifts else "ok",
            ),
            ("Overtime", f"{m.overtime_hours:,.0f} h", f"{ui.inr(m.overtime_cost_inr)} extra pay", "warn" if m.overtime_hours else "ok"),
            ("Tasks on time", on_time, f"of {m.tasks_total} tasks", "info"),
            ("Value at stake", ui.inr(m.roi_inr), f"{m.flagged_still_employed} people to support × assumed cost of replacing one", "info"),
        ]
    )
    if m.roster_id is None:
        st.caption("No roster solved yet: make one on the Roster page to fill the staffing numbers.")
with st.expander("Assumptions"):
    rc_new = st.number_input(
        "Cost of replacing one person who leaves (₹, ASSUMED)",
        min_value=0,
        step=5000,
        value=rc,
        help="Value at stake = people flagged for support who are still employed × this assumed replacement cost.",
    )
    if rc_new != rc:
        st.session_state["replacement_cost"] = rc_new
        st.rerun()
    if m and m.roi_note:
        st.caption(m.roi_note)

# ------------------------------------------------------------------ forecast (the one chart)
week = data.demo_week() or ui.ensure_demo_week()
scores = ui.safe(data.scores, ui.week(), what="load risk scores") or []
ui.html('<h3 class="ss-h3">How full will we be?</h3>')
if week:
    d0 = date.fromisoformat(week)
    fc = ui.safe(data.forecast, d0.isoformat(), (d0 + timedelta(days=6)).isoformat(), what="load the occupancy forecast")
    if fc and fc.days:
        busiest = max(fc.days, key=lambda d: d.mean)
        ui.takeaway(f"Busiest day: {date.fromisoformat(busiest.date).strftime('%A %d %b')}, about {busiest.mean:.0%} of rooms full.")
        st.plotly_chart(charts.forecast_band(fc, 280), width="stretch", config={"displayModeBar": False})
        st.caption(f"Shaded band = likely range ({fc.band}). It held on about 68% of past days, so treat it as a guide.")
    elif fc:
        ui.empty("The forecast returned no days for this week.")
else:
    ui.empty("Demo week unknown: the score table could not be loaded.")

# ------------------------------------------------------------------ department table
ui.html('<h3 class="ss-h3">Departments</h3>')
rid = m.roster_id if m else None
rid = rid or st.session_state.get("last_roster_id")
if rid is None:
    ui.empty("Department load needs a solved roster. Generate one below or on the Roster page.")
    if st.button("Generate roster for the demo week", type="primary", icon=":material/calendar_month:"):
        with st.spinner("Solving roster (can take ~10 s)…"):
            r = ui.safe(api.generate_roster, week, what="generate the roster")
        if r:
            st.session_state["last_roster_id"] = r.get("id")
            data.clear()
            st.rerun()
else:
    ro = ui.safe(data.roster, rid, what=f"load roster {rid}")
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
                    "Headcount": heads.get(d, 0),
                    "Load ratio": ratio,
                    "Coverage": c.get("coverage"),
                    "Understaffed shifts": c.get("understaffed_shifts"),
                    "Flagged (high)": flagged.get(d, 0),
                }
            )
        df = pd.DataFrame(rows)

        def color_ratio(v):
            b = theme.BAND[theme.load_tone(v)]
            return f"background-color:{b['bg']};color:{b['fg']};font-weight:600"

        df["Coverage"] = df["Coverage"].map(lambda v: f"{v:.0%}" if v is not None else "—")
        df["Load ratio"] = df["Load ratio"].map(lambda v: f"{v:.2f}" if v is not None else "—")
        ui.table(df, ["Department", "Headcount", "Understaffed shifts", "Flagged (high)"], key="ov_dept")
        st.caption("Details: load ratio = hours needed ÷ hours scheduled (above 1.10 = short).")

ui.footer()
