import time

import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import data, models, nav, theme, ui

ui.setup("pages/6_Closed_Loop.py", "Closed loop")
ui.html(
    theme.hero(
        "Score. Fix. Re-roster.<br>Measure.",
        "One run: flag high-risk permanent staff, create the matched intervention tasks, re-solve the roster with "
        "protected weekends, then re-score everyone flagged under both rosters.",
        eyebrow="Closed-loop demo",
        pills=["1 Score", "2 Interventions", "3 Adjust roster", "4 Re-score"],
    )
)

c1, c2 = st.columns([1, 3])
with c1:
    run = st.button("Run full loop", type="primary", icon=":material/play_arrow:", width="stretch")
with c2:
    st.caption(
        "Deterministic for the demo week (cached rosters), so the same numbers come back on every run. Tasks use "
        "idempotency keys, so re-running never duplicates them. The live run takes ~30 s."
    )

# Task status -> pill tone (theme.BAND palette): done green, acked amber, overdue red, open grey.
STATUS_TONE = {"done": ("low", "Done"), "acked": ("watch", "Acknowledged"), "overdue": ("high", "Overdue"), "open": ("unknown", "Open")}


def interventions_section() -> None:
    """Stored interventions (GET /interventions); open vs completed comes from each linked task."""
    ui.html(theme.section("Interventions", "Follow-through", "Every stored intervention with the status of its linked task."))
    pick = st.radio("Show", ["All", "Open", "Done"], horizontal=True, key="iv_status", label_visibility="collapsed")
    rows = ui.safe(api.list_interventions, pick.lower(), what="load the interventions")
    if rows is None:
        return
    if not rows:
        ui.empty("No interventions yet. Run the loop to create them." if pick == "All" else f"No {pick.lower()} interventions.")
        return
    cell = "padding:6px 10px;border-bottom:1px solid #ecebe8;text-align:left;vertical-align:top"
    head = "".join(
        f'<th style="{cell};font-size:.75rem;color:#6b6a65">{h}</th>' for h in ("Employee", "Driver", "Action", "Owner", "Due", "Status")
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td style="{cell}">{v}</td>'
            for v in (
                theme.esc(ui.short_name(r.get("employee_id"))),
                theme.esc(models.pretty(r.get("driver", ""))),
                theme.esc(r.get("action")),
                theme.esc(r.get("owner")),
                theme.esc(r.get("due_date")),
                theme.band_chip(*STATUS_TONE.get(r.get("task_status"), ("unknown", str(r.get("task_status"))))),
            )
        )
        + "</tr>"
        for r in rows
    )
    ui.html(
        f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:.85rem"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    )
    n_done = sum(r.get("task_status") == "done" for r in rows)
    n_over = sum(r.get("task_status") == "overdue" for r in rows)
    st.caption(
        f"{len(rows)} shown: {n_done} done, {n_over} overdue. Status comes from the linked task (ack or close it on the Tasks page). "
        "Interventions are support actions for flagged staff; a flag is a model estimate on SYNTHETIC data, not a prediction about any person."
    )


animate = False
if run:
    with st.spinner("Running the loop: scoring, creating tasks, solving two rosters, re-scoring…"):
        raw = ui.safe(api.run_loop, what="run the closed loop")
    if raw:
        st.session_state["loop_raw"] = raw
        st.session_state["last_roster_id"] = raw.get("protected_roster_id")
        data.clear()
        animate = True

raw = st.session_state.get("loop_raw")
if not raw:
    ui.empty("Press Run full loop to start. Results appear step by step.")
    interventions_section()
    ui.footer()
    st.stop()

L = models.parse_loop(raw)
people = {p.employee_id: p for p in L.people}
tb, tp = L.totals.get("baseline", {}), L.totals.get("protected", {})
BAND_RANK = {"low": 0, "watch": 1, "high": 2, "unknown": 1}


def pause():
    if animate:
        time.sleep(0.6)


# ------------------------------------------------------------------ step 1
with st.container(key="card_s1"):
    ui.html(
        theme.step_header(
            1,
            "Score this week",
            f"{len(L.flagged)} permanent staff flagged for review in the week of {L.week_start}. "
            "Seasonal staff follow the contract-date rule and are handled by renewal tasks instead.",
        )
    )
    cards = []
    for e in L.flagged:
        p = people.get(e)
        top = models.pretty(p.top_drivers[0]) if p and p.top_drivers else "—"
        cards.append(
            theme.status_card(
                f"rank {p.baseline.rank}" if p else "",
                f"risk {p.original_risk:.3f}" if p else "",
                ui.short_name(e),
                top,
                p.original_band if p else "high",
            )
        )
    ui.html(f'<div class="ss-statusrow" style="margin-top:12px">{"".join(cards)}</div>')
pause()

# ------------------------------------------------------------------ step 2
with st.container(key="card_s2"):
    ui.html(
        theme.step_header(
            2, "Generate interventions", f"{len(L.interventions)} tasks from the driver playbook: top 2 actions per flagged person."
        )
    )
    if L.interventions:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Task": f"#{i.get('task_id')}",
                        "Employee": ui.short_name(i.get("employee_id")),
                        "Driver": models.pretty(i.get("driver", "")),
                        "Action": i.get("action"),
                        "Owner": i.get("owner"),
                        "Due": i.get("due_date"),
                    }
                    for i in L.interventions
                ]
            ),
            hide_index=True,
            width="stretch",
        )
pause()

# ------------------------------------------------------------------ step 3
with st.container(key="card_s3"):
    ui.html(
        theme.step_header(
            3,
            "Adjust the roster",
            f"Baseline roster #{L.baseline_roster_id} vs protected roster #{L.protected_roster_id} (flagged staff get a weekend off).",
        )
    )
    if tb and tp:

        def cmp(label, key, fmt, good_neg=True, money=False):
            b, p = tb.get(key, 0), tp.get(key, 0)
            show = (lambda v: ui.inr(v)) if money else (lambda v: fmt.format(v))
            return (
                f'<div class="ss-tile"><div class="top">{theme.esc(label)}</div><div class="val" style="font-size:1.35rem">'
                f"{show(b)} → {show(p)}</div>{theme.delta_chip(p - b, '{:,.1f}' if not money else '₹{:,.0f}', good_neg)}</div>"
            )

        ui.html(
            '<div class="ss-tiles" style="margin-top:12px">'
            + cmp("Total cost", "total_cost_inr", "", True, True)
            + cmp("Overtime hours", "overtime_hours", "{:,.0f} h")
            + cmp("Understaffed shifts", "understaffed_shifts", "{:,.0f}")
            + cmp("Understaffed hours", "understaffed_hours", "{:,.0f} h")
            + cmp("Coverage", "coverage", "{:.1%}", good_neg=False)
            + "</div>"
        )
pause()

# ------------------------------------------------------------------ step 4
with st.container(key="card_s4"):
    ui.html(theme.step_header(4, "Re-score", "Each flagged person re-scored with the features each roster implies."))
    rows = []
    for p in L.people:
        rows.append(
            {
                "Employee": ui.short_name(p.employee_id),
                "Risk (baseline roster)": p.baseline.risk,
                "Risk (protected roster)": p.protected.risk,
                "Δ risk": p.risk_change,
                "Band": f"{p.baseline.band} → {p.protected.band}",
                "Rank": f"{p.baseline.rank} → {p.protected.rank}",
                "Overtime h": f"{p.baseline.overtime_hours:g} → {p.protected.overtime_hours:g}",
                "Weekend off": f"{'yes' if p.baseline.full_weekend_off else 'no'} → {'yes' if p.protected.full_weekend_off else 'no'}",
                "Days worked": f"{p.baseline.days_worked} → {p.protected.days_worked}",
            }
        )
    df = pd.DataFrame(rows)

    def color_delta(v):
        if abs(v) < 1e-4:
            return "color:#52514e"
        return f"color:{'#0a6b12' if v < 0 else '#a32020'};font-weight:600"

    if not df.empty:
        st.dataframe(
            df.style.map(color_delta, subset=["Δ risk"]).format(
                {
                    "Risk (baseline roster)": "{:.4f}",
                    "Risk (protected roster)": "{:.4f}",
                    "Δ risk": lambda v: f"{'↓' if v < 0 else '↑' if v > 0 else ''} {v:+.4f}",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    for p in L.people:
        if p.is_demo_hero:
            ui.html(
                f'<div style="margin:6px 0">{theme.icon("user", 16)} <b>{theme.esc(ui.short_name(p.employee_id))}</b>: risk '
                f"{p.baseline.risk:.4f} → {p.protected.risk:.4f} {theme.delta_chip(p.risk_change, '{:.4f}')}, overtime "
                f"{p.baseline.overtime_hours:g} h → {p.protected.overtime_hours:g} h, weekend off "
                f"{'yes' if p.protected.full_weekend_off else 'no'}.</div>"
            )
    biggest = max((abs(p.risk_change) for p in L.people), default=0)
    worse = [p for p in L.people if p.risk_change > 0]
    ui.html(
        theme.banner(
            f"<b>Honest read:</b> the largest risk change is {biggest:.4f}. One protected week barely moves a score driven by "
            "weeks of sustained overtime; a lasting effect needs several protected cycles."
            + (f" {len(worse)} person(s) score slightly <i>higher</i> under the protected roster." if worse else "")
            + f" <span style='color:#6b6a65'>{theme.esc(L.note)}</span>",
            "amber",
            "info",
        )
    )
ui.html("<style>[class*='st-key-card_s']{margin-bottom:12px}</style>")

# ------------------------------------------------------------------ totals footer
improved = sum(1 for p in L.people if BAND_RANK[p.protected.band] < BAND_RANK[p.baseline.band])
ui.html(theme.section("Totals", "Outcome"))
ui.html(
    theme.tiles(
        [
            theme.tile("Cost delta", ui.inr(tp.get("total_cost_inr", 0) - tb.get("total_cost_inr", 0)), "protected − baseline", "rupee"),
            theme.tile(
                "Coverage delta", f"{(tp.get('coverage', 0) - tb.get('coverage', 0)) * 100:+.1f} pts", "protected − baseline", "check"
            ),
            theme.tile("Overtime delta", f"{tp.get('overtime_hours', 0) - tb.get('overtime_hours', 0):+,.0f} h", "whole roster", "clock"),
            theme.tile("Bands improved", f"{improved} of {len(L.people)}", "flagged people whose band dropped", "trend"),
        ]
    )
)
c1, c2 = st.columns(2)
with c1:
    st.page_link(nav.page("pages/5_Roster.py"), label="Compare the two rosters shift by shift", icon=":material/calendar_month:")
with c2:
    st.page_link(nav.page("pages/7_Tasks.py"), label="See the intervention tasks", icon=":material/task_alt:")

interventions_section()

ui.footer()
