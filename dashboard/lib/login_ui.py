"""Sign-in screen: sign in, join with an invite code, one-click demo accounts. Rendered by login.py and by any page
opened while signed out."""

import streamlit as st

from . import auth, theme


def render() -> None:
    st.markdown(theme.CSS, unsafe_allow_html=True)
    st.markdown(
        """<style>
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display:none; }
    .st-key-login_card { background:#fff; border-radius:28px; padding:28px 28px 18px !important; }
    .ss-demo-card { background:#fff; border-radius:20px; padding:16px; min-height:118px; }
    .ss-demo-card b { font-size:1rem; letter-spacing:-.02em; }
    .ss-demo-card div { color:#6b6a65; font-size:.8rem; margin-top:4px; }
    </style>""",
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="ss-topbar"><div class="ss-brand"><span class="ss-brand-mark">{theme.icon("bed", 20, "#fff")}</span>'
        f'<span>HOI <span class="ss-brand-long">Hospitality Operations Intelligence</span></span></div>'
        f'<div class="ss-util"><span>Retention</span><span>Roster</span><span>Dispatch</span><span>Inventory</span></div></div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.25, 1], gap="large")
    with left:
        st.markdown(
            theme.hero(
                "Run a calmer hotel.<br>Keep your best people.",
                "Forecast-driven rosters, live job dispatch with photo proof, inventory that follows demand, and early, explainable "
                "signals about who may need support.",
                eyebrow="Hospitality Operations Intelligence",
                pills=["Retention", "Roster", "Dispatch", "Inventory", "Forecast"],
            ),
            unsafe_allow_html=True,
        )
    with right:
        with st.container(key="login_card"):
            st.markdown(
                '<div style="font-size:1.6rem;font-weight:600;letter-spacing:-.03em">Welcome back</div>'
                '<div style="color:#6b6a65;margin-bottom:8px">Sign in to your hotel workspace</div>',
                unsafe_allow_html=True,
            )
            t_in, t_join = st.tabs(["Sign in", "Join with invite code"])
            with t_in:
                with st.form("signin"):
                    user = st.text_input("Username or employee ID")
                    pw = st.text_input("Password / PIN", type="password")
                    ok = st.form_submit_button("Sign in", type="primary", width="stretch")
                if ok:
                    err = auth.login(user, pw)
                    if not err:
                        st.rerun()
                    st.error(err)
            with t_join:
                with st.form("join"):
                    code = st.text_input("Invite code", placeholder="From your hotel admin")
                    emp = st.text_input("Employee ID (employees only)", placeholder="E134")
                    new_user = st.text_input("Choose a username")
                    new_pw = st.text_input("Choose a password / PIN (6+ characters)", type="password")
                    go = st.form_submit_button("Create account", type="primary", width="stretch")
                if go:
                    err = auth.register(code, new_user, new_pw, emp or None)
                    if not err:
                        st.rerun()
                    st.error(err)

    from . import platform as _pf

    st.markdown(
        theme.banner(
            f"<b>Hotel staff?</b> Use the staff app on your phone: <b>{theme.esc(_pf.public_url())}/worker/</b> "
            "(shifts, job pings, photo proof, supplies). Add it to your home screen.",
            "blue",
            "user",
        ),
        unsafe_allow_html=True,
    )
    demos = auth.demo_accounts()
    if demos:
        st.markdown(
            theme.section(
                "Try it without an account",
                "Demo",
                "One click, one role, on the demo hotel with synthetic data. Each role sees only what it is allowed to.",
            ),
            unsafe_allow_html=True,
        )
        cols = st.columns(len(demos))
        for col, d in zip(cols, demos):
            username, label, desc = d["username"], d["label"], d["description"]
            with col:
                st.markdown(
                    f'<div class="ss-demo-card ss-anim"><b>{theme.esc(label)}</b><div>{theme.esc(desc)}</div></div>', unsafe_allow_html=True
                )
                if st.button("Enter", key=f"demo_{username}", width="stretch", type="primary" if username == "demo.owner" else "secondary"):
                    err = auth.demo_login(username)
                    if err:
                        st.error(err)
                    else:
                        st.rerun()

    st.markdown(
        '<div class="ss-footer"><span>Hospitality Operations Intelligence (HOI) · synthetic demo data · no real person appears anywhere</span>'
        "<span>Product site: website/site/index.html (live at /site on the portal domain)</span></div>",
        unsafe_allow_html=True,
    )
