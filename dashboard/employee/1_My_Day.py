import streamlit as st

from lib import employee_ctx, models, nav, platform, theme, ui
from lib.api_client import ApiError, list_tasks

ui.setup("employee/1_My_Day.py", "My day", employee=True)
ctx = employee_ctx.context()
employee_ctx.header(ctx, "My day")
t = ctx["today"]
if t:
    ui.html(
        f'<div class="ss-hero blue" style="padding:26px 24px"><div class="eyebrow">Today · {employee_ctx.day_label(t["date"])}</div>'
        f'<h1 style="font-size:2.2rem">{t["shift"].capitalize()} shift</h1><p>{t["hours"]} hours · {theme.esc(theme.dept_label(ctx["dept"]))}</p></div>'
    )
else:
    ui.html(
        '<div class="ss-hero dark" style="padding:26px 24px"><div class="eyebrow">Today</div><h1 style="font-size:2.2rem">Day off</h1>'
        "<p>No shift on the roster today. Rest well.</p></div>"
    )

ui.html(theme.section("This week", "My shifts"))
shifts = {a["date"]: a for a in ctx["my_shifts"]}
days = ctx["roster"].dates if ctx["roster"] else []
if days:
    ui.html(
        '<div class="ss-days">'
        + "".join(
            f'<div class="ss-day {"on" if d == ctx["day"] else ""}"><div class="n">{employee_ctx.day_label(d).split()[1]}</div>'
            f'<div class="d">{employee_ctx.day_label(d).split()[0]}</div><div class="d" style="font-weight:600">'
            f"{shifts[d]['shift'][:3] if d in shifts else 'off'}</div></div>"
            for d in days
        )
        + "</div>"
    )
    weekend_off = all(d not in shifts for d in days[5:7])
    st.caption(f"{len(shifts)} shifts · {sum(a['hours'] for a in shifts.values())} h this week" + (" · weekend off" if weekend_off else ""))
else:
    ui.empty("No roster published yet.")

try:
    jobs_open = platform.jobs("offered,accepted,in_progress")
    my_reqs = platform.inv("GET", "/requests", params={"status": "pending,partial"})
except platform.PlatformError:
    jobs_open, my_reqs = [], []
try:
    my_tasks = [x for x in models.parse_tasks(list_tasks()) if x.assignee == ctx["me"] and x.status != "done"]
except ApiError:
    my_tasks = []
ui.html(
    theme.tiles(
        [
            theme.tile("Jobs", str(len(jobs_open)), "pinged or in progress", "flag"),
            theme.tile("Supply requests", str(len(my_reqs)), "waiting for the store", "check"),
            theme.tile("My tasks", str(len(my_tasks)), "open", "clock"),
        ]
    )
)
c1, c2 = st.columns(2)
c1.page_link(nav.page("employee/2_Jobs.py"), label="Open jobs", icon=":material/bolt:")
c2.page_link(nav.page("employee/3_Supplies.py"), label="Request supplies", icon=":material/inventory_2:")
ui.footer()
