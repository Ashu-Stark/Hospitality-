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
            '<div class="ss-field"><span>' + theme.icon("mic", 22, "#1f6fe5") + '</span><div><div class="lbl">Example voice note</div>'
            f'<div class="v">{DEMO_CLIP}</div></div></div>'
        )
        use_demo = st.button("Use the example", type="primary", icon=":material/play_arrow:", width="stretch")
    with b:
        clip = st.text_input("Or the name of a saved voice note", placeholder="clip_01.wav")
    with c:
        ui.html('<div style="height:26px"></div>')
        go = st.button("Turn into text", icon=":material/graphic_eq:", width="stretch", disabled=not clip)


def ingest(name: str, create_task: bool) -> dict | None:
    try:
        return api.voice_ingest(name, create_task=create_task)
    except ApiError as e:
        if e.status == 503:
            ui.html(
                theme.banner(
                    f"<b>We could not read '{theme.esc(name)}'.</b> The file is missing, or voice-to-text is not working right now. "
                    f"Try the example ({DEMO_CLIP}).",
                    "amber",
                    "mic",
                )
            )
        elif e.status in (400, 422, 403):
            ui.html(
                theme.banner(
                    f"<b>That name does not work.</b> Use a plain file name such as <code>{DEMO_CLIP}</code> "
                    "(no folders or special characters).",
                    "amber",
                    "info",
                )
            )
        else:
            ui.html(theme.banner(f"<b>The voice note did not work.</b> {theme.esc(e.message)}", "red", "alert"))
        return None


if use_demo or go:
    name = DEMO_CLIP if use_demo else clip.strip()
    with st.spinner("Listening and writing it down…"):
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
            f'<div class="ss-card" style="min-height:230px"><div style="color:#6b6a65;font-size:.82rem">What we heard · {theme.esc(v.get("audio_file"))}</div>'
            f'<div style="font-size:1.35rem;letter-spacing:-.02em;margin:10px 0 14px;line-height:1.35">“{theme.esc(v.get("transcript"))}”</div></div>'
        )
    with right:
        urg = str(ex.get("urgency") or "unknown")
        tone = {"high": "high", "medium": "watch", "low": "low"}.get(urg, "unknown")
        ui.html(
            '<div class="ss-card" style="min-height:230px"><div style="color:#6b6a65;font-size:.82rem;margin-bottom:10px">What we understood</div>'
            + theme.kv(
                [
                    ("Room", theme.esc(ex.get("room") or "—")),
                    ("Issue", theme.esc(str(ex.get("issue") or "—").replace("_", " "))),
                    ("Department", theme.esc(theme.dept_label(ex.get("department")) if ex.get("department") else "—")),
                    ("Urgency", theme.band_chip(tone, urg)),
                ]
            )
            + f'<div style="color:#6b6a65;font-size:.78rem;margin-top:10px">Key words heard: {theme.esc(", ".join(ex.get("matched_terms") or []) or "—")}</div></div>'
        )
    task = st.session_state.get("voice_task")
    if task:
        ui.html(
            theme.banner(
                f"<b>Task #{task.get('id')} made:</b> {theme.esc(task.get('title'))} · for {theme.esc(task.get('assignee'))} · "
                f"due {theme.esc(str(task.get('deadline', ''))[:16].replace('T', ' '))}",
                "blue",
                "check",
            )
        )
    else:
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Looks right: make a task", type="primary", icon=":material/add_task:", width="stretch"):
                with st.spinner("Making the task…"):
                    res = ingest(state["file"], True)
                if res and res.get("task"):
                    st.session_state["voice_task"] = res["task"]
                    st.rerun()
                elif res:
                    ui.html(theme.banner("No task was made for this voice note.", "amber", "info"))
        with c2:
            if st.button("Looks right: send as a job to a free person on shift", icon=":material/bolt:"):
                data.ops_inputs(st.session_state.get("ops_day"), st.session_state.get("ops_shift_val"))  # publish who is on shift
                ui.safe(
                    platform.create_job,
                    str(ex.get("issue") or "Voice request").replace("_", " ").capitalize(),
                    ex.get("department"),
                    ex.get("room"),
                    {"high": "high", "low": "low"}.get(urg, "medium"),
                    "voice",
                    what="send the job",
                )
                st.session_state["voice_task"] = {
                    "id": "job",
                    "title": "Sent as a job",
                    "assignee": "the best free person on shift",
                    "deadline": "",
                }
                st.switch_page(nav.page("pages/10_Dispatch.py"))
            st.caption("Nothing is made until you press a button. Check the room and problem first: voice-to-text can mishear.")
else:
    ui.empty("Press Use the example to try it.")

ui.footer()
