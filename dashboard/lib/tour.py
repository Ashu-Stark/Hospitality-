"""Guided product tour for first-time users. Runs on the demo workspace and walks the 3-minute story
page by page. State lives in st.session_state['tour_step']; completion is remembered per install."""

from __future__ import annotations

import streamlit as st

from . import nav, platform, theme

STEPS = [
    (
        "pages/1_Overview.py",
        "Start with the week",
        "Money, shifts and who may need a chat, all in one place. Numbers we guessed show their reason when you hover.",
    ),
    (
        "pages/2_Risk_List.py",
        "Who to check in with",
        "People are sorted into: check in this week, keep an eye on, doing fine. Click a row to see why.",
    ),
    (
        "pages/3_Employee_Detail.py",
        "Meet Sunita",
        "More overtime and no weekend off. Each reason is in plain words. Make a task from the suggested next step.",
    ),
    (
        "pages/4_What_If_Simulator.py",
        "Try a change first",
        "Give her 2 weekends off and see what changes. It is a guess, not a promise.",
    ),
    (
        "pages/5_Roster.py",
        "Fair shift plan in seconds",
        "The plan follows the rules (rest, leave, weekly off) and tells you clearly when there are not enough people.",
    ),
    (
        "pages/6_Closed_Loop.py",
        "Support plan",
        "Press 'Make the support plan': find who needs a chat, make tasks, plan weekends off, then check again.",
    ),
    (
        "pages/10_Dispatch.py",
        "Jobs",
        "Press 'Try a guest request'. The best free person gets it on their phone. If they don't take it in time, the next person does.",
    ),
    (
        "pages/11_Worker_App.py",
        "The staff side",
        "Take the job, take a photo before, do the job, take a photo after. The time on the photo comes from the server.",
    ),
    ("pages/12_Setup.py", "Make it yours", "Add your hotel, staff (by ID only) and invite your team."),
]


def start() -> None:
    st.session_state["tour_step"] = 0
    st.switch_page(nav.page(STEPS[0][0]))


def end() -> None:
    st.session_state.pop("tour_step", None)
    try:
        platform.set_prefs({"tour_done": True})
    except platform.PlatformError:
        pass


def render(page_file: str) -> None:
    i = st.session_state.get("tour_step")
    if i is None:
        return
    page, title, body = STEPS[i]
    if page != page_file:
        with st.container(key="tour_resume"):
            a, b = st.columns([5, 1])
            a.markdown(f"**Guided tour paused** · step {i + 1} of {len(STEPS)}: {title}")
            if b.button("Resume", key="tour_resume_btn", width="stretch"):
                st.switch_page(nav.page(page))
        return
    with st.container(key="tour_card"):
        st.markdown(
            f'<div class="ss-tour-head"><span class="ss-tag">Guided tour · {i + 1} / {len(STEPS)}</span>'
            f'<div class="ss-tour-dots">{"".join(f"<i class={chr(39)}on{chr(39)}></i>" if k <= i else "<i></i>" for k in range(len(STEPS)))}</div></div>'
            f'<div class="ss-tour-title">{theme.esc(title)}</div><div class="ss-tour-body">{theme.esc(body)}</div>',
            unsafe_allow_html=True,
        )
        a, b, c = st.columns([1, 1, 4])
        if i > 0 and a.button("Back", key="tour_back", width="stretch"):
            st.session_state["tour_step"] = i - 1
            st.switch_page(nav.page(STEPS[i - 1][0]))
        last = i == len(STEPS) - 1
        if b.button("Finish" if last else "Next", key="tour_next", type="primary", width="stretch"):
            if last:
                end()
                st.rerun()
            st.session_state["tour_step"] = i + 1
            st.switch_page(nav.page(STEPS[i + 1][0]))
        if c.button("End tour", key="tour_end", type="tertiary"):
            end()
            st.rerun()
