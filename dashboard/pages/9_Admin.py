import json

import streamlit as st

from lib import api_client as api
from lib import data, models, platform, tenancy, theme, ui
from lib.config import current_settings, env_settings
from lib.mock_backend import source_of

ui.setup("pages/9_Admin.py", "Admin")
ui.page_head("Data & system", "Where the numbers come from, model versions and the demo reset. For the demo operator.")

s = current_settings()
env = env_settings()

# ------------------------------------------------------------------ mode toggle
with st.container(key="card_mode"):
    a, b = st.columns([1.3, 2])
    with a:
        st.markdown("**Data source**")
        mode = st.segmented_control("Mode", ["MOCK", "LIVE"], default="MOCK" if s.use_mocks else "LIVE", label_visibility="collapsed")
        url = st.text_input("API base URL", value=s.api_base_url)
        if st.button("Apply to this workspace", type="primary", icon=":material/check:"):
            if ui.safe(platform.update_workspace, use_mocks=mode == "MOCK", api_base_url=url.rstrip("/"), what="save the data source"):
                tenancy.on_tenant_change()
            st.rerun()
    with b:
        ui.html(
            theme.kv(
                [
                    ("Current mode", f'<span class="ss-mode {"mock" if s.use_mocks else "live"}">{s.mode_label}</span>'),
                    (".env default", "MOCK" if env.use_mocks else "LIVE"),
                    ("Base URL", theme.esc(s.api_base_url)),
                    ("Timeouts", f"{s.timeout_s:.0f}s / roster {s.roster_timeout_s:.0f}s"),
                ]
            )
        )
        st.caption(
            f"Saved per workspace (now: {tenancy.active()['name']}). New workspaces start from USE_MOCKS / API_BASE_URL in dashboard/.env."
        )
ui.html("<style>[class*='st-key-card_']{background:#fff;border-radius:22px;padding:18px 20px;margin-bottom:12px}</style>")

# ------------------------------------------------------------------ health
with st.container(key="card_health"):
    st.markdown("**Backend health** · `GET /health`")
    h = ui.safe(api.health, what="reach /health")
    if h:
        ui.html(
            f'<div style="display:flex;gap:8px;margin-bottom:10px">{theme.band_chip("low" if h.get("status") == "ok" else "high", "status: " + str(h.get("status")))}'
            f'<span class="ss-tag">backend mock flag: {h.get("mock")}</span><span class="ss-tag">synthetic: {h.get("synthetic")}</span></div>'
        )
        st.dataframe(
            [
                {"Model": m.get("name"), "Version": m.get("version"), "Dataset SHA-256": m.get("dataset_sha256")}
                for m in h.get("models", [])
            ],
            hide_index=True,
            width="stretch",
        )

# ------------------------------------------------------------------ reset
with st.container(key="card_reset"):
    st.markdown("**Reset demo state** · `POST /demo/reset`")
    st.caption(
        "Clears tasks, rosters and the demo clock on the backend"
        + (" (in MOCK mode: the in-memory mock state)." if s.use_mocks else ". This affects everyone using this backend.")
    )

    @st.dialog("Reset the demo?")
    def confirm_reset():
        st.write(
            "This clears all tasks, rosters and clock changes" + (" in the mock." if s.use_mocks else " on the LIVE backend for everyone.")
        )
        c1, c2 = st.columns(2)
        if c1.button("Yes, reset", type="primary", width="stretch"):
            r = ui.safe(api.demo_reset, what="reset the demo")
            if r is not None:
                for k in ("roster_raw", "loop_raw", "last_roster_id", "created_tasks", "task_status_override", "voice_res", "voice_task"):
                    st.session_state.pop(k, None)
                data.clear()
                st.session_state["reset_result"] = r
                st.rerun()
        if c2.button("Cancel", width="stretch"):
            st.rerun()

    if st.button("Reset demo…", icon=":material/restart_alt:"):
        confirm_reset()
    if st.session_state.get("reset_result") is not None:
        st.success("Demo reset.")
        st.json(st.session_state.pop("reset_result"), expanded=False)

# ------------------------------------------------------------------ raw explorer
with st.container(key="card_raw"):
    st.markdown("**Raw JSON explorer** (debugging)")
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

# ------------------------------------------------------------------ schema + mock provenance
with st.container(key="card_schema"):
    st.markdown("**Schema check**")
    if models.SCHEMA_WARNINGS:
        for w in models.SCHEMA_WARNINGS.values():
            ui.html(theme.banner(theme.esc(w), "amber", "alert"))
    else:
        ui.html(theme.banner("No missing fields seen in responses parsed so far.", "blue", "check"))
    with st.expander("Mock file provenance"):
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
