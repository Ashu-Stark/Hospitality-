from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import charts, data, theme, ui
from lib.config import current_settings

ui.setup("pages/1_Overview.py", "Overview")
ui.html(
    theme.hero(
        "This week at the hotel",
        "Operations cost, coverage and who may need support, from one source of truth.",
        eyebrow="Overview",
        variant="blue",
    )
)

# ------------------------------------------------------------------ metric cards
c_rc, _ = st.columns([1, 3])
with c_rc:
    rc = st.number_input(
        "Replacement cost per leaver (₹, assumption)",
        min_value=0,
        step=5000,
        value=int(st.session_state.get("replacement_cost", current_settings().replacement_cost_inr)),
        help="ROI = flagged staff still employed × this assumed replacement cost. Edit it to see the effect.",
    )
    st.session_state["replacement_cost"] = rc

m = ui.safe(data.metrics, float(rc), what="load overview metrics")
if m:
    ot = f"{m.overtime_hours:,.0f} h"
    on_time = ui.pct(m.tasks_on_time_rate) if m.tasks_on_time_rate is not None else "—"
    ui.html(
        theme.tiles(
            [
                theme.tile("Overtime this roster", ot, f"{ui.inr(m.overtime_cost_inr)} overtime cost", "clock"),
                theme.tile("Understaffed shifts", f"{m.understaffed_shifts}", f"roster total {ui.inr(m.total_roster_cost_inr)}", "alert"),
                theme.tile(
                    "Task on-time rate",
                    on_time,
                    f"{m.tasks_total} tasks" + ("" if m.tasks_on_time_rate is not None else " · none completed yet"),
                    "check",
                ),
                theme.tile("Flagged for review", f"{m.flagged_count}", f"{m.flagged_still_employed} still employed", "flag"),
                theme.tile(
                    "Value at stake (ROI)",
                    ui.inr(m.roi_inr),
                    f"{m.flagged_still_employed} × {ui.inr(m.replacement_cost_inr)}",
                    "rupee",
                    assumption=f"replacement cost = {ui.inr(m.replacement_cost_inr)}",
                ),
            ]
        )
    )
    if m.roi_note:
        st.caption(m.roi_note)
    if m.roster_id is None:
        ui.html(
            theme.banner(
                "No roster has been solved yet, so overtime and staffing metrics are empty. Run the "
                "<b>Closed loop</b> page or generate one on the <b>Roster</b> page.",
                "amber",
                "info",
            )
        )

# ------------------------------------------------------------------ forecast + attention
week = data.demo_week() or ui.ensure_demo_week()
scores = ui.safe(data.scores, ui.week(), what="load risk scores") or []
left, right = st.columns([1.6, 1])

with left:
    ui.html(theme.section("Occupancy, next 7 days", "Forecast"))
    if week:
        d0 = date.fromisoformat(week)
        fc = ui.safe(data.forecast, d0.isoformat(), (d0 + timedelta(days=6)).isoformat(), what="load the occupancy forecast")
        if fc and fc.days:
            busiest = max(fc.days, key=lambda d: d.mean)
            ui.html(theme.day_strip([{"date": d.date, "alert": d.high_demand_alert} for d in fc.days], selected=busiest.date))
            st.plotly_chart(charts.forecast_band(fc, 290), width="stretch", config={"displayModeBar": False})
            alerts = [d for d in fc.days if d.high_demand_alert or d.low_demand_alert]
            busiest_day = date.fromisoformat(busiest.date).strftime("%A %d %b")
            ui.html(
                theme.banner(
                    f"Busiest day: <b>{busiest_day}</b> at ~{busiest.mean:.0%} expected occupancy "
                    f"(band {busiest.low:.0%}–{busiest.high:.0%}). "
                    + (f"{len(alerts)} demand alert(s) this week." if alerts else "No high/low demand alerts this week.")
                    + f" <span style='color:#6b6a65'>Interval: {theme.esc(fc.band)}; it covered only ~68% of days in "
                    "backtests, so read it as a guide.</span>",
                    "blue",
                    "trend",
                )
            )
        elif fc:
            ui.empty("The forecast returned no days for this week.")
    else:
        ui.empty("Demo week unknown: the score table could not be loaded.")

with right:
    ui.html(theme.section("Needs attention today", "Top 5 across the hotel", "Flagged for review, not predictions of leaving."))
    order = {"high": 0, "watch": 1, "low": 2, "unknown": 3}
    top = sorted(scores, key=lambda s: (order[s.band], s.rank or 999, -s.risk))[:5]
    if not top:
        ui.empty("No scores available.")
    for s in top:
        with st.container(key=f"att_{s.employee_id}"):
            a, b = st.columns([3.2, 1])
            with a:
                td = s.top_driver
                ui.html(
                    f'<div class="ss-person"><div class="ss-avatar {"hero" if s.is_demo_hero else ""}">{theme.esc(ui.initials(s.employee_id))}</div>'
                    f'<div><div style="font-weight:600">{theme.esc(ui.display_name(s.employee_id))}</div>'
                    f'<div style="margin-top:3px;display:flex;gap:6px;flex-wrap:wrap">{theme.band_chip(s.band)}{theme.basis_tag(s.band_basis)}'
                    f'<span class="ss-tag">rank {s.rank}/{s.group_size}</span></div>'
                    f'<div style="color:#6b6a65;font-size:.78rem;margin-top:4px">{theme.esc(td.title if td else "no active driver")}</div></div></div>'
                )
            with b:
                if st.button("Open", key=f"open_{s.employee_id}", icon=":material/arrow_forward:"):
                    ui.go_to_employee(s.employee_id)
    ui.html("<style>[class*='st-key-att_']{background:#fff;border-radius:18px;padding:12px 14px;margin-bottom:8px}</style>")

# ------------------------------------------------------------------ department table
ui.html(
    theme.section(
        "Departments",
        "Load & flags",
        "Load ratio = required ÷ scheduled hours in the current roster. Red > 1.10 (short), amber 0.95–1.10, green < 0.95.",
    )
)
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

        st.dataframe(
            df.style.map(color_ratio, subset=["Load ratio"]).format({"Load ratio": "{:.2f}", "Coverage": "{:.0%}"}),
            hide_index=True,
            width="stretch",
        )
        st.caption(f"Roster #{ro.id} · {ro.method} · status {ro.status} · week {ro.week_start}")

ui.footer()
