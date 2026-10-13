"""Recognition: positive-only points that turn the month's thank-you budget into a fair reward estimate (People section).

Points are never used for discipline; workers see only their own points plus team totals. Per-person rows are for the
people who pay the rewards (owner, HR, department heads) and are listed by id, not ranked, unless the owner opts in.
"""

import pandas as pd
import streamlit as st

from lib import auth, platform, theme, ui

ui.setup("pages/18_Recognition.py", "Thank-you points")
ui.page_head("Thank-you points", "Thank-you points for good work this month, and what each person may get from your budget.")
ui.html(
    theme.banner(
        "<b>Points only go up.</b> They are never used to punish or cut pay. Each person sees only their own points in the staff app.",
        "blue",
        "shield",
    )
)
r = ui.api(platform.recognition_summary, what="load recognition points", feature="recognition points")
if not isinstance(r, dict):
    ui.footer()
    st.stop()

team = r["team"]
ui.big_numbers(
    [
        ("Points this month", team["total_points"], f"Earned by {team['people_with_points']} of {team['members']} people", "info"),
        (
            "Monthly budget",
            ui.inr(r["budget_inr"]) if r["budget_set"] else "Not set",
            "Set it in Settings" if not r["budget_set"] else "The most you will pay out",
            "ok" if r["budget_set"] else "warn",
        ),
        ("Estimated rewards", ui.inr(r["allocated_inr"]), f"{ui.inr(r['unallocated_inr'])} stays with you", "ok"),
        ("Qualify for a reward", team["eligible"], f"Finished at least {r['config']['min_jobs']} jobs", "info"),
    ]
)

rows = r["workers"]
if rows:
    df = pd.DataFrame(
        [
            {
                "Role": ui.avatar_uri(w["department"]),
                "Employee": ui.short_name(w["employee_id"]),
                "Points": w["points"],
                "Estimated reward ₹": w["estimated_reward_inr"],
                "Jobs done": w["jobs_done"],
                "Department": theme.dept_label(w["department"]),
                "Qualifies": "yes" if w["eligible"] else f"needs {r['config']['min_jobs']} jobs",
                "Reached the limit": "yes" if w["capped"] else "",
                "Share of budget": f"{w['share']:.0%}",
                "Points before the limit": w["raw_points"],
            }
            for w in rows
        ]
    )
    zero = int((df["Points"] == 0).sum())
    df = df[df["Points"] > 0] if zero < len(df) else df
    ui.takeaway(
        ("People with points, listed by ID (not ranked)." if not r.get("leaderboard") else "Your team board is switched on (Settings).")
        + (f" {zero} people have no points yet." if zero and zero < len(rows) else "")
    )
    ui.table(
        df,
        ["Role", "Employee", "Points", "Estimated reward ₹"],
        key="rec_tbl",
        column_config={"Role": st.column_config.ImageColumn("Role", width="small")},
    )
else:
    ui.empty("No staff counted for this property yet.")

with st.expander("How points are earned, and the fair-play rules"):
    w = r["config"]["weights"]
    ui.html(
        '<div class="ss-kv">'
        + "".join(
            f"<div><div class='k'>{theme.esc(label)}</div><div class='v'>+{w[k]}</div></div>"
            for k, label in (
                ("on_time_job", "Job finished on time"),
                ("after_photo", "After photo added"),
                ("inspection_pass", "Room passed the check first time"),
                ("guest_feedback_good", "Guest gave 4-5 stars after the request"),
            )
        )
        + "</div>"
    )
    st.markdown(
        f"- No negative points: nothing ever subtracts.\n"
        f"- At most **{r['config']['max_points_per_worker']} points** per person per month, so nobody is pushed to overwork.\n"
        f"- A reward share needs at least **{r['config']['min_jobs']} finished jobs** in the month.\n"
        f"- One person gets at most **{r['config']['max_share']:.0%}** of the budget; the rest stays with you.\n"
        "- These numbers are a starting point. The owner can change them."
    )
    st.caption("Rewards are an estimate until the owner confirms them at month end.")
if auth.role() in ("owner", "platform_admin"):
    st.caption("Change the budget, the rules or the team board in Settings.")
ui.footer()
