import streamlit as st

from lib import api_client as api
from lib import data, nav, platform, theme, ui
from lib.api_client import ApiError

ui.setup("pages/8_Voice_Ingest.py", "Voice")
ui.page_head("Voice note", "Turn a spoken note into a task.")

DEMO_CLIP = "clip_01.wav"

with st.container(key="card_voice"):
    a, b, c = st.columns([1.2, 2, 1])
    with a:
        ui.html(
            '<div class="ss-field"><span>' + theme.icon("mic", 22, "#1f6fe5") + '</span><div><div class="lbl">Demo clip</div>'
            f'<div class="v">{DEMO_CLIP}</div></div></div>'
        )
        use_demo = st.button("Use demo clip", type="primary", icon=":material/play_arrow:", width="stretch")
    with b:
        clip = st.text_input(
            "Or a clip name on the server",
            placeholder="clip_01.wav",
            help="The backend reads audio from its clips folder (ml/voice/clips). Browser upload is not wired to the API yet.",
        )
        st.caption("Uploading audio from the browser needs a backend upload endpoint; today the API takes a server-side clip name.")
    with c:
        ui.html('<div style="height:26px"></div>')
        go = st.button("Transcribe", icon=":material/graphic_eq:", width="stretch", disabled=not clip)


def ingest(name: str, create_task: bool) -> dict | None:
    try:
        return api.voice_ingest(name, create_task=create_task)
    except ApiError as e:
        if e.status == 503:
            ui.html(
                theme.banner(
                    f"<b>The clip '{theme.esc(name)}' could not be processed.</b> The server does not have this audio file, "
                    f"or speech-to-text is unavailable right now. Try the demo clip ({DEMO_CLIP}).",
                    "amber",
                    "mic",
                )
            )
        elif e.status in (400, 422, 403):
            ui.html(
                theme.banner(
                    f"<b>That clip name is not valid.</b> Use a plain file name such as <code>{DEMO_CLIP}</code> "
                    "(no folders or special characters).",
                    "amber",
                    "info",
                )
            )
        else:
            ui.html(theme.banner(f"<b>Voice ingest failed.</b> {theme.esc(e.message)}", "red", "alert"))
        return None


if use_demo or go:
    name = DEMO_CLIP if use_demo else clip.strip()
    with st.spinner("Transcribing and extracting…"):
        res = ingest(name, False)
    if res:
        st.session_state["voice_res"] = {"file": name, "res": res}
        st.session_state.pop("voice_task", None)

state = st.session_state.get("voice_res")
if state:
    v = state["res"].get("voice", {})
    ex = v.get("extraction", {}) or {}
    left, right = st.columns(2)
    with left:
        ui.html(
            f'<div class="ss-card" style="min-height:230px"><div style="color:#6b6a65;font-size:.82rem">Transcript · {theme.esc(v.get("audio_file"))}</div>'
            f'<div style="font-size:1.35rem;letter-spacing:-.02em;margin:10px 0 14px;line-height:1.35">“{theme.esc(v.get("transcript"))}”</div>'
            f'<div style="display:flex;gap:6px;flex-wrap:wrap"><span class="ss-tag">provider: {theme.esc(v.get("provider"))}</span>'
            + (
                '<span class="ss-tag" style="background:#fff6df;border-color:#f2cd6f;color:#7a5000">fallback used</span>'
                if v.get("fallback_used")
                else ""
            )
            + "</div></div>"
        )
    with right:
        urg = str(ex.get("urgency") or "unknown")
        tone = {"high": "high", "medium": "watch", "low": "low"}.get(urg, "unknown")
        ui.html(
            '<div class="ss-card" style="min-height:230px"><div style="color:#6b6a65;font-size:.82rem;margin-bottom:10px">Structured extraction</div>'
            + theme.kv(
                [
                    ("Room", theme.esc(ex.get("room") or "—")),
                    ("Issue", theme.esc(str(ex.get("issue") or "—").replace("_", " "))),
                    ("Department", theme.esc(theme.dept_label(ex.get("department")) if ex.get("department") else "—")),
                    ("Urgency", theme.band_chip(tone, urg)),
                ]
            )
            + f'<div style="color:#6b6a65;font-size:.78rem;margin-top:10px">Matched glossary terms: {theme.esc(", ".join(ex.get("matched_terms") or []) or "—")}</div></div>'
        )
    task = st.session_state.get("voice_task")
    if task:
        ui.html(
            theme.banner(
                f"<b>Task #{task.get('id')} created:</b> {theme.esc(task.get('title'))} · assigned to {theme.esc(task.get('assignee'))} · "
                f"due {theme.esc(str(task.get('deadline', ''))[:16].replace('T', ' '))}",
                "blue",
                "check",
            )
        )
    else:
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Confirm & create task", type="primary", icon=":material/add_task:", width="stretch"):
                with st.spinner("Creating task…"):
                    res = ingest(state["file"], True)
                if res and res.get("task"):
                    st.session_state["voice_task"] = res["task"]
                    st.rerun()
                elif res:
                    ui.html(theme.banner("The backend did not create a task for this clip (no task returned).", "amber", "info"))
        with c2:
            if st.button("Confirm & auto-dispatch to an on-shift worker", icon=":material/bolt:"):
                data.ops_inputs(st.session_state.get("ops_day"), st.session_state.get("ops_shift_val"))  # publish who is on shift
                ui.safe(
                    platform.create_job,
                    str(ex.get("issue") or "Voice request").replace("_", " ").capitalize(),
                    ex.get("department"),
                    ex.get("room"),
                    {"high": "high", "low": "low"}.get(urg, "medium"),
                    "voice",
                    what="dispatch the voice request",
                )
                st.session_state["voice_task"] = {
                    "id": "dispatch",
                    "title": "Sent to Live dispatch",
                    "assignee": "best on-shift worker",
                    "deadline": "",
                }
                st.switch_page(nav.page("pages/10_Dispatch.py"))
            st.caption("Nothing is created until you confirm. Check the room and issue first: speech-to-text can mishear.")
else:
    ui.empty("Press Use demo clip to try the flow.")

ui.footer()
