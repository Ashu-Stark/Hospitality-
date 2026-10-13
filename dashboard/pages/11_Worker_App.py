import streamlit as st

from lib import data, platform, tenancy, theme, ui, worker_ui

ui.setup("pages/11_Worker_App.py", "Worker preview")
SECONDS = int(tenancy.active_settings().get("offer_seconds", 30))
ro, working, bands, day, shift = data.ops_inputs(st.session_state.get("ops_day"), st.session_state.get("ops_shift_val"))

left, right = st.columns([1, 1.25])
with right:
    ui.html(
        theme.section(
            "What the worker sees",
            "Worker app (manager preview)",
            "Employees sign in to their own app. Here a manager can act as any on-shift worker to demo the flow; "
            "every action is recorded in the audit log as 'acting as'.",
        )
    )
    try:
        jobs = platform.jobs()
    except platform.PlatformError:
        jobs = []
    pending = {j["offer_to"] for j in jobs if j["status"] == "offered"}
    mine = {j["assigned_to"] for j in jobs if j["status"] in ("accepted", "in_progress")}
    opts = sorted(working, key=lambda e: (e not in pending, e not in mine, e))
    if not opts:
        ui.empty("Nobody is on shift. Pick a day/shift on the Dispatch page or generate a roster.")
        ui.footer()
        st.stop()
    me = st.selectbox(
        "Act as worker",
        opts,
        format_func=lambda e: (
            f"{ui.short_name(e)} · {theme.dept_label(working[e])}" + (" · ping" if e in pending else "") + (" · job" if e in mine else "")
        ),
        key="worker_me",
    )
    allow_upload = st.toggle(
        "Allow photo upload (demo only)",
        value=False,
        help="Production uses the live camera only, so gallery photos cannot be reused. Turn on only when a laptop has no camera.",
    )
    ui.html(
        theme.banner(
            "Photos are stamped with <b>server time</b>, the job and the worker, and hashed (SHA-256) on arrival. "
            "This proves when the server received the photo; it cannot stop someone photographing a screen.",
            "gray",
            "shield",
        )
    )
    worker_ui.completed(me)

with left:
    worker_ui.phone(me, working.get(me), shift, SECONDS, allow_upload)

ui.footer()
