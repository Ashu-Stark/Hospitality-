import time

import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import data, models, nav, theme, ui
from lib.models import PLAIN_REASON

ui.setup("pages/6_Closed_Loop.py", "Support plan")
ui.page_head("Support plan", "One click: find who needs a chat, make the follow-up tasks, give them weekends off, then check again.")

c1, c2 = st.columns([1, 3])
with c1:
    run = st.button("Make the support plan", type="primary", icon=":material/play_arrow:", width="stretch")
with c2:
    st.caption("Takes about 30 seconds. Running it again does not make the same tasks twice.")

# Task status -> pill tone (theme.BAND palette): done green, acked amber, overdue red, open grey.
STATUS_TONE = {"done": ("low", "Done"), "acked": ("watch", "Seen"), "overdue": ("high", "Late"), "open": ("unknown", "Open")}


def reason(k: str | None) -> str:
    return PLAIN_REASON.get(str(k or "")) or models.pretty(k or "")


def interventions_section() -> None:
    """Stored interventions (GET /interventions); open vs completed comes from each linked task."""
    ui.html(theme.section("Next steps", "Follow-through", "Every suggested next step and whether its task is done."))
    pick = st.radio("Show", ["All", "Open", "Done"], horizontal=True, key="iv_status", label_visibility="collapsed")
    rows = ui.safe(api.list_interventions, pick.lower(), what="load the next steps")
    if rows is None:
        return
    if not rows:
        ui.empty("No next steps yet. Press Make the support plan." if pick == "All" else f"No {pick.lower()} next steps.")
        return
    cell = "padding:6px 10px;border-bottom:1px solid #ecebe8;text-align:left;vertical-align:top"
    head = "".join(
        f'<th style="{cell};font-size:.75rem;color:#6b6a65">{h}</th>' for h in ("Person", "Why", "Next step", "Who", "By", "Status")
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td style="{cell}">{v}</td>'
            for v in (
                theme.esc(ui.short_name(r.get("employee_id"))),
                theme.esc(reason(r.get("driver"))),
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
    st.caption(f"{len(rows)} shown: {n_done} done, {n_over} late. Mark them seen or done on the Tasks page.")


animate = False
if run:
    with st.spinner("Working: finding people, making tasks, making two shift plans, checking again…"):
        raw = ui.safe(api.run_loop, what="make the support plan")
    if raw:
        st.session_state["loop_raw"] = raw
        st.session_state["last_roster_id"] = raw.get("protected_roster_id")
        data.clear()
        animate = True

raw = st.session_state.get("loop_raw")
if not raw:
    ui.empty("Press Make the support plan to start. Results appear step by step.")
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
            "Who needs a chat this week",
            f"{len(L.flagged)} permanent staff to check in with, week of {L.week_start}. "
            "Seasonal staff are handled by contract-renewal tasks instead.",
        )
    )
    cards = []
    for e in L.flagged:
        p = people.get(e)
        top = reason(p.top_drivers[0]) if p and p.top_drivers else "—"
        cards.append(
            theme.status_card(
                f"place {p.baseline.rank}" if p else "",
                f"chance {p.original_risk:.0%}" if p else "",
                ui.short_name(e),
                top,
                p.original_band if p else "high",
            )
        )
    ui.html(f'<div class="ss-statusrow" style="margin-top:12px">{"".join(cards)}</div>')
pause()

# ------------------------------------------------------------------ step 2
with st.container(key="card_s2"):
    ui.html(theme.step_header(2, "Make next-step tasks", f"{len(L.interventions)} tasks: up to 2 suggested next steps for each person."))
    if L.interventions:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Task": f"#{i.get('task_id')}",
                        "Person": ui.short_name(i.get("employee_id")),
                        "Why": reason(i.get("driver")),
                        "Next step": i.get("action"),
                        "Who": i.get("owner"),
                        "By": i.get("due_date"),
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
            "Change the shift plan",
            f"Plan #{L.baseline_roster_id} before vs plan #{L.protected_roster_id} with a weekend off for these people.",
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
            + cmp("Shifts short of people", "understaffed_shifts", "{:,.0f}")
            + cmp("Hours short", "understaffed_hours", "{:,.0f} h")
            + cmp("Shifts filled", "coverage", "{:.1%}", good_neg=False)
            + "</div>"
        )
pause()

# ------------------------------------------------------------------ step 4
with st.container(key="card_s4"):
    ui.html(theme.step_header(4, "Check again", "For each person: the chance of leaving with each shift plan."))
    rows = []
    for p in L.people:
        rows.append(
            {
                "Employee": ui.short_name(p.employee_id),
                "Chance (before)": p.baseline.risk,
                "Chance (weekends off)": p.protected.risk,
                "Change": p.risk_change,
                "Group": f"{theme.BAND[p.baseline.band]['label']} → {theme.BAND[p.protected.band]['label']}",
                "Place": f"{p.baseline.rank} → {p.protected.rank}",
                "Overtime hours": f"{p.baseline.overtime_hours:g} → {p.protected.overtime_hours:g}",
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
            df.style.map(color_delta, subset=["Change"]).format(
                {
                    "Chance (before)": "{:.1%}",
                    "Chance (weekends off)": "{:.1%}",
                    "Change": lambda v: f"{'↓' if v < 0 else '↑' if v > 0 else ''} {v * 100:+.1f} points",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    for p in L.people:
        if p.is_demo_hero:
            ui.html(
                f'<div style="margin:6px 0">{theme.icon("user", 16)} <b>{theme.esc(ui.short_name(p.employee_id))}</b>: chance '
                f"{p.baseline.risk:.1%} → {p.protected.risk:.1%} {theme.delta_chip(p.risk_change * 100, '{:.1f} points')}, overtime "
                f"{p.baseline.overtime_hours:g} h → {p.protected.overtime_hours:g} h, weekend off "
                f"{'yes' if p.protected.full_weekend_off else 'no'}.</div>"
            )
    biggest = max((abs(p.risk_change) for p in L.people), default=0)
    worse = [p for p in L.people if p.risk_change > 0]
    ui.html(
        theme.banner(
            f"<b>Honest read:</b> the biggest change is {biggest * 100:.1f} points. One weekend off does not undo weeks of "
            "overtime. It takes several weeks of weekends off to see a real change."
            + (f" {len(worse)} person(s) went slightly <i>up</i> with the new plan." if worse else ""),
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
            theme.tile("Cost change", ui.inr(tp.get("total_cost_inr", 0) - tb.get("total_cost_inr", 0)), "new plan − old plan", "rupee"),
            theme.tile(
                "Shifts filled change",
                f"{(tp.get('coverage', 0) - tb.get('coverage', 0)) * 100:+.1f} points",
                "new plan − old plan",
                "check",
            ),
            theme.tile("Overtime change", f"{tp.get('overtime_hours', 0) - tb.get('overtime_hours', 0):+,.0f} h", "whole team", "clock"),
            theme.tile("People who moved to a calmer group", f"{improved} of {len(L.people)}", "out of the people checked", "trend"),
        ]
    )
)
c1, c2 = st.columns(2)
with c1:
    st.page_link(nav.page("pages/5_Roster.py"), label="Compare the two shift plans", icon=":material/calendar_month:")
with c2:
    st.page_link(nav.page("pages/7_Tasks.py"), label="See the next-step tasks", icon=":material/task_alt:")

interventions_section()

ui.footer()
