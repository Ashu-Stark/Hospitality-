import streamlit as st

from lib import api_client as api
from lib import employee_ctx, models, theme, ui

ui.setup("employee/4_My_Tasks.py", "My tasks", employee=True)
ctx = employee_ctx.context()
employee_ctx.header(ctx, "My tasks")
raw = ui.safe(api.list_tasks, what="load your tasks")
tasks = [t for t in models.parse_tasks(raw or []) if t.assignee == ctx["me"]]
if raw is not None and not tasks:
    ui.empty("No tasks assigned to you.")
for t in sorted(tasks, key=lambda t: (t.status == "done", str(t.deadline or t.created_at))):
    tone = {"open": "watch", "acked": "low", "done": "low"}.get(t.status, "unknown")
    ui.html(
        f'<div class="ss-task"><div style="display:flex;justify-content:space-between;gap:8px"><b>{theme.esc(t.title)}</b>'
        f'{theme.band_chip(tone, t.status)}</div><div class="m">due {t.deadline.strftime("%d %b %H:%M") if t.deadline else "—"}</div></div>'
    )
    c1, c2 = st.columns(2)
    if t.status == "open" and c1.button("Acknowledge", key=f"ea_{t.id}", width="stretch"):
        ui.safe(api.ack_task, t.id, what="acknowledge")
        st.rerun()
    if t.status != "done" and c2.button("Done", key=f"ed_{t.id}", type="primary", width="stretch"):
        ui.safe(api.done_task, t.id, what="complete")
        st.rerun()
ui.footer()
