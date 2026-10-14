from datetime import datetime

import streamlit as st

from lib import api_client as api
from lib import models, theme, timefmt, ui
from lib.api_client import ApiError

ui.setup("pages/7_Tasks.py", "Tasks")
ui.page_head("Tasks", "Follow-up tasks for your team: what is late, what is open, what is done.")
board_slot = st.container()  # the answer (tiles + task cards) goes first; the practice clock sits in Details underneath

# ------------------------------------------------------------------ demo clock (demo-only control, under Details)
with ui.details("Details: practice clock and auto-update"):
    clock_raw = ui.safe(api.get_clock, what="read the practice clock")
    clock = models.parse_clock(clock_raw) if clock_raw else None
    a, b, c = st.columns([1.1, 2.9, 1.1])
    with a:
        ui.html(
            f'<div style="display:flex;gap:8px;align-items:center"><span class="ss-tag" style="background:#fff6df;border-color:#f2cd6f;'
            f'color:#7a5000">Practice clock</span></div><div style="font-size:1.5rem;font-weight:600;letter-spacing:-.03em;margin-top:6px">'
            f"{clock.virtual_now.strftime('%a %d %b, %H:%M') if clock and clock.virtual_now else '—'}</div>"
            f'<div style="color:#6b6a65;font-size:.8rem">speed ×{clock.multiplier:g}</div>'
            if clock
            else ""
        )
    with b:
        speeds = {"Real time": 1.0, "1 min = 1 h": 60.0, "1 s = 1 h": 3600.0, "1 s = 1 day": 86400.0}
        cur = next((k for k, v in speeds.items() if clock and abs(v - clock.multiplier) < 1e-6), None)
        pick = st.segmented_control("Fast-forward the clock", list(speeds), default=cur, key="speed_pick")
        if pick and clock and speeds[pick] != clock.multiplier:
            if ui.safe(api.set_clock, speeds[pick], what="change the clock speed"):
                st.toast(f"Clock speed set to ×{speeds[pick]:g}", icon=":material/fast_forward:")
                st.rerun()
    with c:
        auto = st.toggle(
            "Update every 5 seconds", value=False, help="Shows new reminders and tasks passed to the supervisor as they happen."
        )
        st.button("Refresh now", icon=":material/refresh:")

overrides: dict = st.session_state.setdefault("task_status_override", {})


def act(task_id, to: str) -> None:
    """Optimistic update: show the new status at once, roll back if the API call fails."""
    prev = overrides.get(task_id)
    overrides[task_id] = to
    try:
        (api.ack_task if to == "acked" else api.done_task)(task_id)
        st.session_state["task_msg"] = f"Task #{task_id} marked {'seen' if to == 'acked' else to}"
    except ApiError as e:
        if prev is None:
            overrides.pop(task_id, None)
        else:
            overrides[task_id] = prev
        st.session_state["task_error"] = f"Task #{task_id}: {e.message} (not changed)"


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

    if not tasks:
        ui.empty("No tasks yet. Make the support plan, add one from a person's page, or use a voice note.")
        return

    def urgency(t: models.Task) -> tuple[str, str]:
        if t.status == "done":
            return "", ""
        f = t.deadline_fraction(now)
        if t.deadline and now > t.deadline:
            return "overdue", theme.band_chip("high", "late")
        if f is not None and f >= 0.9:
            return "near90", theme.band_chip("watch", f"{f:.0%} of time used")
        if f is not None and f >= 0.5:
            return "near50", theme.band_chip("watch", f"{f:.0%} of time used")
        return "", ""

    n_over = sum(1 for t in tasks if urgency(t)[0] == "overdue")
    n_open = sum(t.status == "open" for t in tasks)
    ui.verdict(
        n_over,
        ok_text="No task is late." + (f" {n_open} not seen yet." if n_open else ""),
        bad_text=f"{n_over} task{'s are' if n_over != 1 else ' is'} late. Start with the red ones.",
    )
    ui.big_numbers(
        [
            ("Late", n_over, "Past the time, not done", "bad" if n_over else "ok"),
            ("Not seen yet", n_open, "Nobody has opened it", "warn" if n_open else "ok"),
            ("Being done", sum(t.status == "acked" for t in tasks), "Someone is on it", "info"),
            ("Done", sum(t.status == "done" for t in tasks), "Finished", "ok"),
        ]
    )
    f1, f2, _f3 = st.columns([1.5, 1.5, 2])
    with f1:
        who = st.multiselect("Who does it", sorted({t.assignee for t in tasks}), placeholder="Everyone")
    with f2:
        emp = st.multiselect(
            "About which person", sorted({t.employee_id for t in tasks if t.employee_id}), format_func=ui.short_name, placeholder="Any"
        )
    show_keys = False
    tasks = [t for t in tasks if (not who or t.assignee in who) and (not emp or t.employee_id in emp)]
    if not tasks:
        ui.empty("No tasks match these filters.")
        return
    cols = st.columns(3)
    for col, (status, title) in zip(cols, (("open", "Not seen yet"), ("acked", "Being done"), ("done", "Done"))):
        with col:
            group = sorted((t for t in tasks if t.status == status), key=lambda t: t.deadline or datetime.max)
            ui.html(
                f'<div style="font-weight:600;font-size:1.05rem;margin:4px 4px 8px">{title} <span class="ss-tag">{len(group)}</span></div>'
            )
            for t in group:
                cls, chip = urgency(t)
                rem = [e for e in t.events if "remind" in str(e.get("kind", "")).lower()]
                esc_tag = theme.band_chip("high", "passed to the supervisor") if t.escalated else ""
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
                        st.button("Seen", key=f"ack_{t.id}", on_click=act, args=(t.id, "acked"), width="stretch")
                with b2:
                    if t.status != "done":
                        st.button("Done", key=f"done_{t.id}", on_click=act, args=(t.id, "done"), type="primary", width="stretch")
                if t.events:
                    with st.expander(f"History ({len(t.events)})"):
                        for e in t.events:
                            st.caption(f"{timefmt.stamp(e.get('at'))} · {e.get('kind')}: {e.get('message')}")


with board_slot:
    board()
ui.footer()
