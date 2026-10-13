"""Hotel setup (voice): an owner sets up one hotel by answering a few guided questions by voice or text.

Not the same as the Setup page (pages/12_Setup.py), which creates the platform workspace (organisation,
staff import, team invites). This page builds one hotel's operating profile through the ML / ops API
(/onboarding/*): rooms, departments, shifts, rules. Draft only until Confirm.
"""

import pandas as pd
import streamlit as st

from lib import api_client as api
from lib import onboarding_view as ov
from lib import theme, ui
from lib.api_client import ApiError

PAGE = "pages/15_Hotel_Setup.py"
ui.setup(PAGE, "Hotel setup (voice)")
ui.html(
    theme.section(
        "Set up a hotel by voice",
        "Hotel setup (voice)",
        "Answer a few questions in Hindi, English or Hinglish, by voice or by typing. Hospitality Operations Intelligence "
        "fills the rest from a size-based template and shows a draft. This is separate from Setup, which creates your workspace.",
    )
)

LANGS = {"English": "en", "हिन्दी (Hindi)": "hi"}
TYPES = {"Decide from the number of rooms": None, "Homestay": "homestay", "Small hotel": "small_hotel", "Resort": "resort"}
SS = st.session_state


def call(fn, *args, what: str, **kwargs):  # noqa: ANN001, ANN201
    try:
        return fn(*args, **kwargs)
    except ApiError as e:
        if isinstance(e.detail, dict) and "unacknowledged_legal_fields" in e.detail:
            SS["onb_blocked"] = e.detail
            return None
        ui.html(theme.banner(f"<b>Could not {theme.esc(what)}.</b> {theme.esc(e.message)}", "red", "alert"))
        return None


def remember(out: dict | None) -> None:
    if out:
        SS["onb"] = out
        SS["onb_sid"] = out["session_id"]
        SS.pop("onb_blocked", None)


# ------------------------------------------------------------------ start
with st.container(key="card_onb_start"):
    c1, c2, c3 = st.columns([1.2, 1.6, 1])
    with c1:
        lang_label = st.radio("Language", list(LANGS), horizontal=True, key="onb_lang")
    with c2:
        type_label = st.selectbox("Hotel type", list(TYPES), key="onb_type")
    with c3:
        ui.html('<div style="height:26px"></div>')
        if st.button("Start a new setup", type="primary", icon=":material/play_arrow:", width="stretch"):
            SS.pop("onb_confirmed", None)
            remember(call(api.onboarding_start, LANGS[lang_label], TYPES[type_label], what="start the setup"))

state = SS.get("onb")
if not state:
    ui.empty("Press Start a new setup. Nothing is saved until you press Confirm at the end.")
    ui.footer()
    st.stop()

sid = state["session_id"]
ui.html(theme.banner(f"<b>{theme.esc(state['banner'])}</b> Draft for property id {theme.esc(state['property_id'])}.", "amber", "info"))

# ------------------------------------------------------------------ current question + answer
q = state.get("question")
if state.get("stt_error"):
    ui.html(theme.banner(f"<b>{theme.esc(state['stt_error'])}</b> Type your answer in the box below.", "amber", "mic"))
elif state.get("message"):
    ui.html(theme.banner(theme.esc(state["message"]), "blue", "info"))
if state.get("mismatches"):
    ui.html(
        theme.banner(
            "<b>Please confirm:</b> the AI heard a different number than the number reader for "
            + theme.esc(", ".join(state["mismatches"]))
            + ". Check the draft below.",
            "amber",
            "alert",
        )
    )

if q:
    with st.container(key="card_onb_question"):
        ui.html(
            f'<div class="ss-card"><div style="color:#6b6a65;font-size:.82rem">Question {q["number"]} of at most {q["max_questions"]}'
            f' · wording is a draft for review</div><div style="font-size:1.3rem;margin:8px 0">{theme.esc(q["text"])}</div>'
            f'<div style="color:#6b6a65">Example: {theme.esc(q["example"])}</div></div>'
        )
        tab_text, tab_voice, tab_demo = st.tabs(["Type the answer", "Speak the answer", "Cached Hindi demo"])
        with tab_demo:
            st.caption(
                "Plays one SYNTHETIC Hindi / Hinglish conversation written by us (not recorded speech), answer by answer, "
                "so the voice flow can be shown with no microphone and no API keys."
            )
            if st.button("Use the cached Hindi demo answer", icon=":material/record_voice_over:"):
                fx = call(api.onboarding_demo_transcript, what="load the demo transcript")
                demo_text = (fx or {}).get("answers", {}).get(q["field"])
                if demo_text:
                    remember(call(api.onboarding_answer, sid, text=demo_text, what="send the demo answer"))
                    st.rerun()
        with tab_text:
            with st.form("onb_text", clear_on_submit=True):
                text = st.text_input("Your answer", placeholder=q["example"])
                a, b = st.columns([1, 1])
                send = a.form_submit_button("Send answer", type="primary", icon=":material/send:")
                skip = b.form_submit_button("Skip (keep the suggested value)")
            if send and text.strip():
                remember(call(api.onboarding_answer, sid, text=text.strip(), what="send the answer"))
                st.rerun()
            if skip:
                remember(call(api.onboarding_answer, sid, text="skip", what="skip the question"))
                st.rerun()
        with tab_voice:
            st.caption(f"Streamlit {st.__version__}: record with the microphone or upload a short clip.")
            rec = st.audio_input("Record your answer", key=f"onb_rec_{q['number']}")
            up = st.file_uploader("Or upload audio", type=["wav", "mp3", "m4a", "webm", "ogg"], key=f"onb_up_{q['number']}")
            consent = st.checkbox(
                "This recording is my own voice. It contains no staff names or salaries. "
                "I understand that free AI services give no privacy guarantee.",
                key=f"onb_consent_{q['number']}",
            )
            clip = rec or up
            if st.button("Send recording", disabled=clip is None, icon=":material/graphic_eq:"):
                audio = (getattr(clip, "name", None) or "answer.wav", clip.getvalue(), getattr(clip, "type", None) or "audio/wav")
                remember(call(api.onboarding_answer, sid, audio=audio, consent=consent, what="send the recording"))
                st.rerun()
            st.caption(
                "Voice needs the server to allow cloud speech-to-text for owner audio (off by default) and your consent. "
                "If it is off, you will be asked to type instead. Audio is not stored."
            )
else:
    ui.html(theme.banner("<b>All questions answered.</b> Check the draft, tick the legal checks and press Confirm.", "blue", "check"))

if state.get("transcript"):
    st.caption(
        f"Last answer ({state.get('input')}, extractor: {state.get('extractor') or 'none'}): “{state['transcript']}”"
        + (f" · fallback: {state['fallback_reason']}" if state.get("fallback_reason") else "")
    )

# ------------------------------------------------------------------ draft table
ui.html(theme.section("Draft profile", "Summary", "Every field is editable. Source and confidence show where each value came from."))
fields = state["fields"]
legal = state.get("legal_fields", [])
rows = []
for name, fv in fields.items():
    tone, conf_label = ov.confidence_badge(fv["confidence"]) if fv["value"] is not None else ("unknown", "—")
    rows.append(
        {
            "field": name,
            "Field": ov.LABELS.get(name, name),
            "Value": ov.format_value(name, fv["value"]),
            "Source": ov.SOURCE_LABEL.get(fv["source"], fv["source"]) + (" (edited)" if fv.get("method") == "edit" else ""),
            "Confidence": conf_label,
            "Check": ("verify with a qualified person" if fv["needs_verification"] else "")
            + (f" · {fv['note']}" if fv.get("note") else ""),
        }
    )
df = pd.DataFrame(rows)
edited = st.data_editor(
    df,
    key=f"onb_editor_{sid}_{state.get('answers', 0)}",
    hide_index=True,
    width="stretch",
    disabled=["field", "Field", "Source", "Confidence", "Check"],
    column_config={"field": None, "Value": st.column_config.TextColumn("Value (edit me)")},
)
found = ov.geo_found(fields.get("location"))
if found:  # LocationIQ / OpenStreetMap geocoding of the location answer: a hint only, never blocks Confirm
    st.caption(
        f":material/location_on: {found} · not right? edit the location in the table above. Place search © LocationIQ · © OpenStreetMap contributors"
    )
if st.button("Save my edits", icon=":material/save:"):
    errors, out = [], None
    for (_, old), (_, new) in zip(df.iterrows(), edited.iterrows()):
        if str(old["Value"]) != str(new["Value"]):
            try:
                value = ov.parse_value(old["field"], str(new["Value"]))
            except ValueError as e:
                errors.append(f"{old['Field']}: {e}")
                continue
            out = call(api.onboarding_edit, sid, old["field"], value, what=f"save {old['Field']}") or out
    for e in errors:
        ui.html(theme.banner(theme.esc(e), "red", "alert"))
    if out:
        remember({**state, **out, "transcript": None, "message": None, "stt_error": None, "mismatches": []})
        st.rerun()

for kind, tone in (("errors", "red"), ("warnings", "amber")):
    for f, msgs in (state.get(kind) or {}).items():
        for m in msgs:
            ui.html(theme.banner(f"<b>{theme.esc(ov.LABELS.get(f, f))}:</b> {theme.esc(m)}", tone, "alert" if tone == "red" else "info"))
if state.get("needs_confirmation"):
    ui.html(
        theme.banner(
            "<b>Please confirm these values</b> (low confidence): "
            + theme.esc(", ".join(ov.LABELS.get(f, f) for f in state["needs_confirmation"]))
            + ". Edit them or type the same value again, then Save my edits.",
            "amber",
            "alert",
        )
    )

# ------------------------------------------------------------------ legal checks + confirm
ui.html(
    theme.section("Legal values", "Verify with a qualified person", "These depend on labour rules. They are never confirmed from voice.")
)
acks = []
for f in legal:
    fv = fields[f]
    if st.checkbox(
        f"{ov.LABELS.get(f, f)} = {ov.format_value(f, fv['value']) or 'not set'}: checked with a qualified person",
        key=f"onb_ack_{sid}_{f}",
    ):
        acks.append(f)

blocked = SS.get("onb_blocked")
if blocked:
    parts = [
        f"{label}: {', '.join(ov.LABELS.get(x, x) for x in blocked.get(key) or [])}"
        for key, label in (
            ("missing_required", "missing"),
            ("needs_confirmation", "please confirm"),
            ("unacknowledged_legal_fields", "legal checks not ticked"),
        )
        if blocked.get(key)
    ]
    if blocked.get("errors"):
        parts.append("fix the errors above")
    ui.html(theme.banner("<b>Nothing was saved.</b> " + theme.esc("; ".join(parts)), "red", "shield"))

done = SS.get("onb_confirmed")
if done and done.get("property_id") == state["property_id"]:
    ui.html(
        theme.banner(
            f"<b>Saved as {theme.esc(done['property_id'])}</b>"
            + (" (already saved earlier: nothing duplicated)." if not done["created"] else "."),
            "blue",
            "check",
        )
    )
elif st.button("Confirm and save", type="primary", icon=":material/task_alt:", disabled=state["status"] == "confirmed"):
    res = call(api.onboarding_confirm, sid, acks, what="confirm the setup")
    if res:
        SS["onb_confirmed"] = res
        SS.pop("onb_blocked", None)
        remember(call(api.onboarding_summary, sid, what="reload the summary"))
    st.rerun()

ui.footer()
