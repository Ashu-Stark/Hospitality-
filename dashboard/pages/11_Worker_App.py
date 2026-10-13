import streamlit as st

from lib import data, platform, tenancy, theme, ui, worker_ui

ui.setup("pages/11_Worker_App.py", "Worker preview")
SECONDS = int(tenancy.active_settings().get("offer_seconds", 30))
ro, working, bands, day, shift = data.ops_inputs(st.session_state.get("ops_day"), st.session_state.get("ops_shift_val"))

left, right = st.columns([1, 1.25])
with right:
    ui.html(
        theme.section(
            "What a staff member sees",
            "Staff app preview",
            "Pick anyone on shift to try their screen. What you do is logged under your name.",
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
        ui.empty("Nobody is on shift. Pick a day and shift on the Jobs page, or make a shift plan.")
        ui.footer()
        st.stop()
    me = st.selectbox(
        "See the screen of",
        opts,
        format_func=lambda e: (
            f"{ui.short_name(e)} · {theme.dept_label(working[e])}"
            + (" · new job" if e in pending else "")
            + (" · job" if e in mine else "")
        ),
        key="worker_me",
    )
    allow_upload = st.toggle(
        "Allow photo upload (practice only)",
        value=False,
        help="Staff phones use the live camera only, so old photos cannot be reused. Turn on only if this computer has no camera.",
    )
    ui.html(
        theme.banner(
            "Each photo gets the <b>server's time</b>, the job and the person. "
            "It shows when the photo arrived. It cannot stop a photo of a screen.",
            "gray",
            "shield",
        )
    )
    worker_ui.completed(me)

with left:
    worker_ui.phone(me, working.get(me), shift, SECONDS, allow_upload)

ui.footer()
