"""Sign-in screen, per portal. Rendered by login.py and by any page opened while signed out.

super-admin portal: platform sign-in only (+ "Platform admin" demo button); hotel accounts are pointed to the hotel portal
hotel portal:       sign in, join with an invite code, one-click demo accounts for the hotel roles
"""

import streamlit as st

from . import auth, config, portal, theme
from . import platform as _pf

BASE_CSS = """<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display:none; }
.st-key-login_card { background:#fff; border-radius:28px; padding:28px 28px 18px !important; }
.ss-demo-card { background:#fff; border-radius:20px; padding:16px; min-height:118px; }
.ss-demo-card b { font-size:1rem; letter-spacing:-.02em; }
.ss-demo-card div { color:#6b6a65; font-size:.8rem; margin-top:4px; }
</style>"""


def render() -> None:
    st.markdown(theme.CSS, unsafe_allow_html=True)
    st.markdown(BASE_CSS + portal.css(), unsafe_allow_html=True)
    if config.is_super():
        _render_super()
    else:
        _render_hotel()


# Everyday words for the demo-account cards (the API's descriptions use internal page names); unknown accounts keep theirs.
DEMO_TEXT = {
    "platform": "Add and manage hotels",
    "demo.owner": "Sees everything for the hotel",
    "demo.hr": "Check-ins and people, no shifts or stock",
    "demo.housekeeping": "Shift plan, jobs and stock requests",
    "demo.frontoffice": "Guest requests, late check-outs, jobs",
    "demo.store": "Stock only",
    "demo.homestay": "The simple app for a 6-room homestay",
    "DN03": "A simple task list",
}


def _demo_card(d: dict, primary: bool) -> None:
    desc = DEMO_TEXT.get(d["username"]) or str(d["description"]).replace("Employee app:", "Staff app:")
    st.markdown(
        f'<div class="ss-demo-card ss-anim"><b>{theme.esc(d["label"])}</b><div>{theme.esc(desc)}</div></div>',
        unsafe_allow_html=True,
    )
    if st.button("Enter", key=f"demo_{d['username']}", width="stretch", type="primary" if primary else "secondary"):
        _demo(d["username"])


def _demo(username: str) -> None:
    err = auth.demo_login(username)
    if err:
        st.error(err)
    else:
        st.rerun()


def _signin_form(label: str = "Username or employee ID") -> None:
    with st.form("signin"):
        user = st.text_input(label)
        pw = st.text_input("Password / PIN", type="password")
        ok = st.form_submit_button("Sign in", type="primary", width="stretch")
    if ok:
        err = auth.login(user, pw)
        if not err:
            st.rerun()
        st.error(err)


# ------------------------------------------------------------------ super-admin portal
def _render_super() -> None:
    st.markdown(
        f'<div class="ss-topbar ss-super">{portal.brand_html({})}'
        '<div class="ss-util"><span>Hotels</span><span>Insights</span><span>Activity log</span></div></div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.25, 1], gap="large")
    with left:
        st.markdown(
            theme.hero(
                "HOI team console",
                "For the HOI team only. Add hotels, choose what each hotel can use, see how hotels use HOI, and check the "
                "activity log. Everything you do here is logged.",
                eyebrow="HOI team",
                variant="dark",
                pills=["Hotels", "Plans", "Insights", "Activity log"],
            ),
            unsafe_allow_html=True,
        )
    with right:
        with st.container(key="login_card"):
            st.markdown(
                '<div style="font-size:1.6rem;font-weight:600;letter-spacing:-.03em">HOI team sign-in</div>'
                '<div style="color:#6b6a65;margin-bottom:8px">For HOI team accounts only</div>',
                unsafe_allow_html=True,
            )
            _signin_form("Username")
    st.markdown(
        theme.banner(
            "<b>Work at a hotel?</b> Owners, managers and staff sign in here instead: " + portal.link(config.hotel_portal_url()),
            "blue",
            "user",
        ),
        unsafe_allow_html=True,
    )
    demos = [d for d in auth.demo_accounts() if d["username"] == "platform"]
    if demos:
        st.markdown(theme.section("Try it without an account", "Demo", "One click. Practice data."), unsafe_allow_html=True)
        c, _ = st.columns([1, 3])
        with c:
            _demo_card({**demos[0], "label": "HOI team"}, True)


# ------------------------------------------------------------------ hotel admin portal
def _render_hotel() -> None:
    st.markdown(
        f'<div class="ss-topbar">{portal.brand_html({})}'
        '<div class="ss-util"><span>Shift plan</span><span>Jobs</span><span>Stock</span><span>Your team</span></div></div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.25, 1], gap="large")
    with left:
        st.markdown(
            theme.hero(
                "Run a calmer hotel.<br>Keep your best people.",
                "Plan shifts for how busy you will be. Send jobs to staff phones and get photo proof. Know when stock runs low. "
                "See early who may need a friendly chat.",
                eyebrow="For hotel owners and managers",
                pills=["Shift plan", "Jobs", "Stock", "How full we'll be", "Check-ins"],
            ),
            unsafe_allow_html=True,
        )
    with right:
        with st.container(key="login_card"):
            st.markdown(
                '<div style="font-size:1.6rem;font-weight:600;letter-spacing:-.03em">Welcome back</div>'
                '<div style="color:#6b6a65;margin-bottom:8px">Sign in to your hotel</div>',
                unsafe_allow_html=True,
            )
            t_in, t_join = st.tabs(["Sign in", "Join with invite code"])
            with t_in:
                _signin_form()
            with t_join:
                with st.form("join"):
                    code = st.text_input("Invite code", placeholder="From your hotel admin")
                    emp = st.text_input("Employee ID (employees only)", placeholder="HS05")
                    new_user = st.text_input("Choose a username")
                    new_pw = st.text_input("Choose a password / PIN (6+ characters)", type="password")
                    go = st.form_submit_button("Create account", type="primary", width="stretch")
                if go:
                    err = auth.register(code, new_user, new_pw, emp or None)
                    if not err:
                        st.rerun()
                    st.error(err)

    st.markdown(
        theme.banner(
            f"<b>Hotel staff?</b> Use the staff app on your phone: <b>{theme.esc(_pf.public_url())}/worker/</b> "
            "(your shifts, new jobs, photos, supplies). Add it to your home screen.",
            "blue",
            "user",
        ),
        unsafe_allow_html=True,
    )
    all_demos = auth.demo_accounts()
    demos = [d for d in all_demos if d["username"] != "platform"]
    if demos:
        st.markdown(
            theme.section(
                "Try it without an account",
                "Demo",
                "One click. Each role sees only its own pages. Practice data.",
            ),
            unsafe_allow_html=True,
        )
        per_row = 5
        for i in range(0, len(demos), per_row):
            for col, d in zip(st.columns(per_row), demos[i : i + per_row]):
                with col:
                    _demo_card(d, d["username"] == "demo.owner")
    if any(d["username"] == "platform" for d in all_demos):
        a, b = st.columns([3, 1], vertical_alignment="center")
        a.markdown(
            f'<div style="color:#6b6a65;font-size:.85rem">HOI team: your console is at {portal.link(config.super_portal_url())}. '
            "You can also open one hotel from here (it is logged).</div>",
            unsafe_allow_html=True,
        )
        if b.button("HOI team: choose a hotel", key="demo_platform", type="tertiary", icon=":material/shield:"):
            _demo("platform")
