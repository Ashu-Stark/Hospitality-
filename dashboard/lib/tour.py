"""Guided product tour for first-time users. Runs on the demo workspace and walks the 3-minute story
page by page. State lives in st.session_state['tour_step']; completion is remembered per install."""

from __future__ import annotations

import streamlit as st

from . import nav, platform, theme

STEPS = [
    (
        "pages/1_Overview.py",
        "Start with the week",
        "Cost, coverage and who may need support, from one source of truth. The orange tag on ROI marks an assumption you can edit.",
    ),
    (
        "pages/2_Risk_List.py",
        "Who to check in with",
        "Bands rank people within this week. Permanent staff are ranked by the model; seasonal staff by "
        "contract date (see the basis tag). Click any row for the reasons.",
    ),
    (
        "pages/3_Employee_Detail.py",
        "Meet Sunita",
        "Rising overtime and no weekend off. Each driver is explained in plain language and is "
        "labelled with how strongly the data supports it. Create a task straight from the playbook.",
    ),
    (
        "pages/4_What_If_Simulator.py",
        "Try a fix first",
        "Give her 2 protected weekends and re-score. It is a simulation, not a promise, and the effect is shown as-is, even when small.",
    ),
    (
        "pages/5_Roster.py",
        "Fair roster in seconds",
        "The solver respects leave, rest and skills, and reports exactly why a week cannot be "
        "staffed instead of publishing a roster that breaks a rule.",
    ),
    (
        "pages/6_Closed_Loop.py",
        "Close the loop",
        "Press Run full loop: score, create interventions, re-solve with protected weekends, re-score. This is the core idea.",
    ),
    (
        "pages/10_Dispatch.py",
        "Live dispatch",
        "Press Simulate incoming request. The best on-shift worker is pinged; if they do not accept "
        "in time, the next one is. Open 'Why this worker?' for the score.",
    ),
    (
        "pages/11_Worker_App.py",
        "The worker's side",
        "Accept the ping, take a before photo, do the job, take an after photo. Both are stamped with server time and hashed.",
    ),
    ("pages/12_Setup.py", "Make it yours", "Create your own workspace: properties, staff by ID only, your backend, team invites."),
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
