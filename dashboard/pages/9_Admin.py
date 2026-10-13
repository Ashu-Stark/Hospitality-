import json

import streamlit as st

from lib import api_client as api
from lib import data, models, platform, tenancy, theme, ui
from lib.config import current_settings, env_settings
from lib.mock_backend import source_of

ui.setup("pages/9_Admin.py", "Admin")
ui.page_head("System", "Choose practice data or your own, check the server, start the practice again.")

s = current_settings()
env = env_settings()

# ------------------------------------------------------------------ mode toggle
with st.container(key="card_mode"):
    a, b = st.columns([1.3, 2])
    with a:
        st.markdown("**Which data?**")
        mode = st.segmented_control(
            "Data", ["Practice data", "Live data"], default="Practice data" if s.use_mocks else "Live data", label_visibility="collapsed"
        )
        url = st.text_input("Server address", value=s.api_base_url)
        if st.button("Save for this hotel", type="primary", icon=":material/check:"):
            if ui.safe(
                platform.update_workspace, use_mocks=mode == "Practice data", api_base_url=url.rstrip("/"), what="save the data choice"
            ):
                tenancy.on_tenant_change()
            st.rerun()
    with b:
        ui.html(
            theme.kv(
                [
                    ("Now using", theme.esc(s.mode_label)),
                    ("New hotels start with", "Practice data" if env.use_mocks else "Live data"),
                    ("Wait time", f"{s.timeout_s:.0f} s (shift plan {s.roster_timeout_s:.0f} s)"),
                ]
            )
        )
        st.caption(f"Saved for this hotel only ({tenancy.active()['name']}).")
ui.html("<style>[class*='st-key-card_']{background:#fff;border-radius:22px;padding:18px 20px;margin-bottom:12px}</style>")

# ------------------------------------------------------------------ health
with st.container(key="card_health"):
    st.markdown("**Is the server working?**")
    h = ui.safe(api.health, what="reach the server")
    if h:
        ok = h.get("status") == "ok"
        ui.html(theme.band_chip("low" if ok else "high", "Working" if ok else "Not working"))
        with st.expander("For technical support"):
            st.dataframe(
                [{"Part": m.get("name"), "Version": m.get("version"), "Data check": m.get("dataset_sha256")} for m in h.get("models", [])],
                hide_index=True,
                width="stretch",
            )

# ------------------------------------------------------------------ reset
with st.container(key="card_reset"):
    st.markdown("**Start the practice again**")
    st.caption(
        "Clears tasks, shift plans and the practice clock" + ("." if s.use_mocks else ". This changes it for everyone on this server.")
    )

    @st.dialog("Start again?")
    def confirm_reset():
        st.write("This clears all tasks, shift plans and clock changes" + ("." if s.use_mocks else " for everyone on this server."))
        c1, c2 = st.columns(2)
        if c1.button("Yes, start again", type="primary", width="stretch"):
            r = ui.safe(api.demo_reset, what="start again")
            if r is not None:
                for k in ("roster_raw", "loop_raw", "last_roster_id", "created_tasks", "task_status_override", "voice_res", "voice_task"):
                    st.session_state.pop(k, None)
                data.clear()
                st.session_state["reset_result"] = r
                st.rerun()
        if c2.button("Cancel", width="stretch"):
            st.rerun()

    if st.button("Start again…", icon=":material/restart_alt:"):
        confirm_reset()
    if st.session_state.get("reset_result") is not None:
        st.success("Done. Everything is back to the start.")
        st.session_state.pop("reset_result")

# ------------------------------------------------------------------ raw explorer (technical support only)
with st.expander("For technical support"):
    st.markdown("**Ask the server directly**")
    c1, c2 = st.columns([1, 4])
    with c1:
        method = st.selectbox("Method", ["GET", "POST"])
    with c2:
        path = st.text_input("Path", value="/metrics/overview", help="e.g. /forecast?from=2029-12-24&to=2029-12-30, /roster/3, /tasks")
    body_txt = st.text_area("JSON body (POST)", value="{}", height=90, disabled=method == "GET")
    if st.button("Send", icon=":material/send:"):
        try:
            body = json.loads(body_txt or "{}") if method == "POST" else None
        except ValueError as e:
            body = None
            st.error(f"Body is not valid JSON: {e}")
        else:
            res = ui.safe(api.raw_request, method, path, body, what=f"call {method} {path}")
            if res is not None:
                st.json(res, expanded=2)

    st.markdown("**Missing fields check**")
    if models.SCHEMA_WARNINGS:
        for w in models.SCHEMA_WARNINGS.values():
            ui.html(theme.banner(theme.esc(w), "amber", "alert"))
    else:
        st.caption("Nothing missing so far.")
    st.markdown("**Where the practice files come from**")
    for f in [
        "health.json",
        "forecast_week.json",
        "attrition_scores.json",
        "rescore_sunita.json",
        "loop_run.json",
        "roster_baseline.json",
        "roster_protected.json",
        "tasks.json",
        "metrics_overview.json",
        "demo_clock.json",
        "voice_ingest.json",
        "heroes.json",
        "playbook.json",
        "hero_display_names.json",
        "roster_infeasible.json",
    ]:
        st.caption(f"{f} ← {source_of(f)}")
    st.caption("Re-capture from the live API: `python mocks/_fixtures.py --refresh`")

ui.footer()
