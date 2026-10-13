"""Resolve a page file to its registered st.Page object (robust for deep-linked sessions)."""

import streamlit as st


def page(file: str):
    return st.session_state.get("_page_by_file", {}).get(file, file)
