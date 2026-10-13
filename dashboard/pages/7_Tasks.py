from datetime import datetime

import streamlit as st

from lib import api_client as api
from lib import models, theme, ui
from lib.api_client import ApiError

ui.setup("pages/7_Tasks.py", "Tasks")
ui.page_head("Tasks", "Follow-up tasks and how close each one is to its deadline.")

# ------------------------------------------------------------------ demo clock (demo-only control)
with st.container(key="card_clock"):
    clock_raw = ui.safe(api.get_clock, what="read the demo clock")
    clock = models.parse_clock(clock_raw) if clock_raw else None
    a, b, c = st.columns([1.1, 2.9, 1.1])
    with a:
        ui.html(
            f'<div style="display:flex;gap:8px;align-items:center"><span class="ss-tag" style="background:#fff6df;border-color:#f2cd6f;'
            f'color:#7a5000">DEMO-ONLY CONTROL</span></div><div style="font-size:1.5rem;font-weight:600;letter-spacing:-.03em;margin-top:6px">'
            f"{clock.virtual_now.strftime('%a %d %b, %H:%M') if clock and clock.virtual_now else '—'}</div>"
            f'<div style="color:#6b6a65;font-size:.8rem">virtual time · speed ×{clock.multiplier:g}</div>'
            if clock
            else ""
        )
    with b:
        speeds = {"Real time": 1.0, "1 min = 1 h": 60.0, "1 s = 1 h": 3600.0, "1 s = 1 day": 86400.0}
        cur = next((k for k, v in speeds.items() if clock and abs(v - clock.multiplier) < 1e-6), None)
        pick = st.segmented_control("Fast-forward the clock", list(speeds), default=cur, key="speed_pick")
        if pick and clock and speeds[pick] != clock.multiplier:
            if ui.safe(api.set_clock, speeds[pick], what="change the demo clock speed"):
                st.toast(f"Clock speed set to ×{speeds[pick]:g}", icon=":material/fast_forward:")
                st.rerun()
    with c:
        auto = st.toggle(
            "Live refresh (5 s)", value=False, help="Re-reads the board every 5 seconds so reminders and escalations appear live."
        )
        st.button("Refresh now", icon=":material/refresh:")

overrides: dict = st.session_state.setdefault("task_status_override", {})


def act(task_id, to: str) -> None:
    """Optimistic update: show the new status at once, roll back if the API call fails."""
    prev = overrides.get(task_id)
    overrides[task_id] = to
    try:
        (api.ack_task if to == "acked" else api.done_task)(task_id)
        st.session_state["task_msg"] = f"Task #{task_id} marked {to}"
    except ApiError as e:
        if prev is None:
            overrides.pop(task_id, None)
        else:
            overrides[task_id] = prev
        st.session_state["task_error"] = f"Task #{task_id}: {e.message} (change rolled back)"


@st.fragment(run_every=5 if auto else None)
def board() -> None:
    raw = ui.safe(api.list_tasks, what="load tasks")
    if raw is None:
        return
    tasks = models.parse_tasks(raw)
    for t in tasks:  # server truth wins once it has caught up
        if overrides.get(t.id) == t.status:
            overrides.pop(t.id, None)
        elif t.id in overrides:
            t.status = overrides[t.id]
    if msg := st.session_state.pop("task_msg", None):
        st.toast(msg, icon=":material/check:")
    if err := st.session_state.pop("task_error", None):
        ui.html(theme.banner(theme.esc(err), "red", "alert"))
    try:
        c = models.parse_clock(api.get_clock())
    except ApiError:
        c = None
    now = c.virtual_now if c and c.virtual_now else datetime.utcnow()

    f1, f2, f3 = st.columns([1.5, 1.5, 2])
    with f1:
        who = st.multiselect("Assignee", sorted({t.assignee for t in tasks}), placeholder="Everyone")
    with f2:
        emp = st.multiselect(
            "Linked employee", sorted({t.employee_id for t in tasks if t.employee_id}), format_func=ui.short_name, placeholder="Any"
        )
    with f3:
        show_keys = st.toggle("Show idempotency keys (debug)", value=False)
    tasks = [t for t in tasks if (not who or t.assignee in who) and (not emp or t.employee_id in emp)]
    if not tasks:
        ui.empty("No tasks yet. Run the closed loop, create one from an employee page, or ingest a voice note.")
        return

    def urgency(t: models.Task) -> tuple[str, str]:
        if t.status == "done":
            return "", ""
        f = t.deadline_fraction(now)
        if t.deadline and now > t.deadline:
            return "overdue", theme.band_chip("high", "overdue")
        if f is not None and f >= 0.9:
            return "near90", theme.band_chip("watch", f"{f:.0%} of time used")
        if f is not None and f >= 0.5:
            return "near50", theme.band_chip("watch", f"{f:.0%} of time used")
        return "", ""

    n_over = sum(1 for t in tasks if urgency(t)[0] == "overdue")
    ui.html(
        theme.tiles(
            [
                theme.tile("Open", str(sum(t.status == "open" for t in tasks)), "awaiting acknowledgement", "flag"),
                theme.tile("Acknowledged", str(sum(t.status == "acked" for t in tasks)), "in progress", "clock"),
                theme.tile("Done", str(sum(t.status == "done" for t in tasks)), "completed", "check"),
                theme.tile("Overdue", str(n_over), "past deadline, not done", "alert"),
            ]
        )
    )
    ui.html('<div style="height:12px"></div>')
    cols = st.columns(3)
    for col, (status, title) in zip(cols, (("open", "Open"), ("acked", "Acknowledged"), ("done", "Done"))):
        with col:
            group = sorted((t for t in tasks if t.status == status), key=lambda t: t.deadline or datetime.max)
            ui.html(
                f'<div style="font-weight:600;font-size:1.05rem;margin:4px 4px 8px">{title} <span class="ss-tag">{len(group)}</span></div>'
            )
            for t in group:
                cls, chip = urgency(t)
                rem = [e for e in t.events if "remind" in str(e.get("kind", "")).lower()]
                esc_tag = theme.band_chip("high", "escalated") if t.escalated else ""
                ui.html(
                    f'<div class="ss-task {cls}"><div class="t">{theme.esc(t.title)}</div>'
                    f'<div class="m">#{t.id} · {theme.esc(t.assignee)}'
                    + (f" · {theme.esc(ui.short_name(t.employee_id))}" if t.employee_id else "")
                    + f'</div><div class="m">due {t.deadline.strftime("%d %b %H:%M") if t.deadline else "—"}'
                    + (f" · {len(rem)} reminder(s)" if rem else "")
                    + f"</div>"
                    f'<div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">{chip}{esc_tag}</div>'
                    + (f'<div class="key">{theme.esc(t.idempotency_key)}</div>' if show_keys else "")
                    + "</div>"
                )
                b1, b2 = st.columns(2)
                with b1:
                    if t.status == "open":
                        st.button("Ack", key=f"ack_{t.id}", on_click=act, args=(t.id, "acked"), width="stretch")
                with b2:
                    if t.status != "done":
                        st.button("Done", key=f"done_{t.id}", on_click=act, args=(t.id, "done"), type="primary", width="stretch")
                if t.events:
                    with st.expander(f"History ({len(t.events)})"):
                        for e in t.events:
                            st.caption(f"{str(e.get('at', ''))[:16].replace('T', ' ')} · {e.get('kind')}: {e.get('message')}")


board()
ui.footer()
