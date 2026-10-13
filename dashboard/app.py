"""Hospitality Operations Intelligence (HOI) app entrypoint. One codebase, two admin portals (ADMIN_PORTAL):

    ADMIN_PORTAL=hotel streamlit run app.py --server.port 8501   # hotel admin portal (default)
    ADMIN_PORTAL=super streamlit run app.py --server.port 8502   # HOI platform admin portal

Router only. What a visitor sees depends on the portal and on who is signed in:
  signed out      -> login.py (sign in; hotel portal also: join with invite code, one-click demo accounts)
  super portal    -> console/ (home summary, hotels, insights, audit); platform admins only
  hotel portal    -> pages/ filtered by role and by the modules in the hotel's plan;
                     platform admins first choose a hotel (pick_hotel.py, audited impersonation)
  employee        -> employee/ (hotel portal; mobile-first app: my day, jobs, supplies, my tasks)
"""

import streamlit as st

from lib import access, auth, config, portal, tenancy

auth.restore()  # "stay signed in": refresh-token cookie -> new session after a browser refresh
if config.is_super():
    title = "HOI Platform Admin"
else:
    t = tenancy.active()
    title = f"{t['name']} · Hotel admin" if t.get("id") else "HOI Hotel Admin"
    if hotel := st.query_params.get("hotel"):  # "Open in hotel portal" link from the platform console
        st.session_state["want_hotel"] = str(hotel)[:64]
st.set_page_config(page_title=title, page_icon=portal.page_icon(), layout="wide", initial_sidebar_state="collapsed")
st.logo(str(portal.BRAND_DIR / "hoi-icon-192.png"), size="large")  # HOI platform mark (sidebar / collapsed header)

if auth.current() and not config.is_super():
    tenancy.bootstrap()  # loads the properties, so the navigation follows the property's mode (homestay / hotel)
nav = access.visible_pages()
st.session_state["_nav"] = nav
routable = nav if auth.current() else nav + access.portal_pages()
if auth.needs_hotel():  # registered (not shown) so "Open this hotel" can switch_page to Home; ui.setup denies it until then
    routable = nav + access.HOTEL_PAGES[:1]
elif auth.impersonating():  # likewise for "Exit" back to the hotel picker
    routable = nav + [access.PICK_PAGE]
start = st.session_state.get("_smoke_page")  # set only by tests/smoke.py
files = [f for f, _, _ in nav]
default = start if start in files else files[0]
by_file: dict[str, st.Page] = {}
for f, label, ic in routable:
    if f not in by_file:
        url = None if f == default else f.split("/")[-1].split("_", 1)[-1].removesuffix(".py")
        by_file[f] = st.Page(f, title=label, icon=ic, url_path=url, default=f == default)
st.session_state["_page_by_file"] = by_file  # nav links use Page objects, never path strings
auth.sync_cookie()
st.navigation(list(by_file.values()), position="hidden").run()
