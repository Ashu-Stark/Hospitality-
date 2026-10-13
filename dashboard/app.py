"""Hospitality Operations Intelligence (HOI) app entrypoint.

    streamlit run app.py

Router only. What a visitor sees depends on who is signed in:
  signed out      -> login.py (sign in, join with invite code, one-click demo accounts)
  platform admin  -> console/ (onboard and manage hotels) + every hotel page
  hotel staff     -> pages/ filtered by role and by the modules in the hotel's plan
  employee        -> employee/ (mobile-first app: my day, jobs, supplies, my tasks)
"""

import streamlit as st

from lib import access, auth

st.set_page_config(
    page_title="HOI · Hospitality Operations Intelligence", page_icon=":material/hotel:", layout="wide", initial_sidebar_state="auto"
)

auth.restore()  # "stay signed in": refresh-token cookie -> new session after a browser refresh
nav = access.visible_pages()
st.session_state["_nav"] = nav
routable = nav if auth.current() else nav + access.CONSOLE_PAGES + access.HOTEL_PAGES + access.EMPLOYEE_PAGES
start = st.session_state.get("_smoke_page")  # set only by tests/smoke.py
files = [f for f, _, _ in nav]
default = start if start in files else files[0]
by_file: dict[str, st.Page] = {}
for f, label, icon in routable:
    if f not in by_file:
        url = None if f == default else f.split("/")[-1].split("_", 1)[-1].removesuffix(".py")
        by_file[f] = st.Page(f, title=label, icon=icon, url_path=url, default=f == default)
st.session_state["_page_by_file"] = by_file  # nav links use Page objects, never path strings
auth.sync_cookie()
st.navigation(list(by_file.values()), position="hidden").run()
