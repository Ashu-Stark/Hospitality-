"""Resolve a page file to its registered st.Page object (robust for deep-linked sessions), and link or switch to it
without ever crashing the page.

Streamlit can, in rare timing cases (e.g. the first run right after signing in on a deep link such as /Staff), see a
page registry that does not contain the page a link points to and raise StreamlitPageNotFoundError. link() and go()
then rerun once (the next run registers every page again) and, if that is not enough, fall back to a plain link."""

import html
import time

import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

_RECOVER_KEY = "_nav_recover_at"


def page(file: str):
    return st.session_state.get("_page_by_file", {}).get(file, file)


def url_of(file: str) -> str:
    """The URL path app.py gives a page ("" for the default page)."""
    if file == st.session_state.get("_default_page"):
        return ""
    return file.split("/")[-1].split("_", 1)[-1].removesuffix(".py")


def _recover() -> None:
    """Rerun once to get a fresh page registry; at most once every 10 s so a real problem cannot loop."""
    if time.time() - st.session_state.get(_RECOVER_KEY, 0.0) > 10:
        st.session_state[_RECOVER_KEY] = time.time()
        st.rerun()


def link(file: str, label: str, icon: str | None = None, where=None) -> None:
    """st.page_link that never breaks the page."""
    where = where or st
    try:
        where.page_link(page(file), label=label, icon=icon)
    except StreamlitPageNotFoundError:
        _recover()
        where.markdown(
            f'<a class="ss-navlink" href="./{html.escape(url_of(file))}" target="_self">{html.escape(label)}</a>',
            unsafe_allow_html=True,
        )


def go(file: str) -> None:
    """st.switch_page that never breaks the page."""
    try:
        st.switch_page(page(file))
    except StreamlitPageNotFoundError:
        _recover()
        st.stop()
