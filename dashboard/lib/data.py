"""Cached read-only accessors (TTL 30s). Mutations go straight through api_client.

Each cached function takes the (base_url, use_mocks) pair so MOCK and LIVE never share cache entries.
The Refresh button in the sidebar calls clear().
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import streamlit as st

from . import api_client as api
from . import models as m
from .config import HERO_NAME_FILES, PLAYBOOK_FILES, Settings, current_settings

TTL = 30


def _settings(base: str, mocks: bool) -> Settings:
    s = current_settings()
    return Settings(**{**s.__dict__, "api_base_url": base, "use_mocks": mocks})


def _k() -> tuple[str, bool]:
    s = current_settings()
    return s.api_base_url, s.use_mocks


@st.cache_data(ttl=TTL, show_spinner=False)
def _health(base, mocks):
    return api.health(_settings(base, mocks))


@st.cache_data(ttl=TTL, show_spinner=False)
def _scores(base, mocks, week):
    return api.score_attrition(week_start=week, settings=_settings(base, mocks))


@st.cache_data(ttl=TTL, show_spinner=False)
def _forecast(base, mocks, f, t):
    return api.get_forecast(f, t, settings=_settings(base, mocks))


@st.cache_data(ttl=TTL, show_spinner=False)
def _metrics(base, mocks, rc):
    return api.metrics_overview(rc, settings=_settings(base, mocks))


@st.cache_data(ttl=TTL, show_spinner=False)
def _roster(base, mocks, rid):
    return api.get_roster(rid, settings=_settings(base, mocks))


@st.cache_data(ttl=300, show_spinner=False)
def _heroes():
    return api.heroes()


def health() -> dict:
    return _health(*_k())


def scores(week: str | None = None) -> list[m.AttritionScore]:
    return m.parse_scores(_scores(*_k(), week))


def forecast(date_from: str, date_to: str) -> m.Forecast:
    return m.parse_forecast(_forecast(*_k(), date_from, date_to))


def metrics(replacement_cost: float | None = None) -> m.Metrics:
    return m.parse_metrics(_metrics(*_k(), replacement_cost))


def roster(roster_id) -> m.Roster:
    return m.parse_roster(_roster(*_k(), roster_id))


def heroes() -> list[m.Hero]:
    return m.parse_heroes(_heroes())


def clear() -> None:
    st.cache_data.clear()


# ------------------------------------------------------------------ static lookups
def _first_json(paths) -> dict:
    for p in paths:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
    return {}


@st.cache_data(show_spinner=False)
def hero_names() -> dict[str, str]:
    """Display names exist ONLY for the 5 scripted demo heroes. Everyone else is an ID."""
    return {str(k): str(v) for k, v in _first_json(HERO_NAME_FILES).items()}


@st.cache_data(show_spinner=False)
def playbook() -> dict:
    d = _first_json(PLAYBOOK_FILES)
    return d.get("drivers", d)


def demo_week() -> str | None:
    """The backend's scoring week (latest week in the synthetic data)."""
    return st.session_state.get("demo_week")


def week_options(anchor: str, n: int = 8) -> list[str]:
    a = date.fromisoformat(anchor)
    return [(a - timedelta(weeks=i)).isoformat() for i in range(n)]


def current_roster_id():
    """Most relevant roster: the one this session generated, else the one the metrics endpoint reports."""
    rid = st.session_state.get("last_roster_id")
    if rid is not None:
        return rid
    try:
        return metrics().roster_id
    except api.ApiError:
        return None


def dept_map() -> dict[str, str]:
    """employee_id -> department. The score endpoint has no department, so it is joined from roster.people."""
    rid = current_roster_id()
    if rid is None:
        return {}
    try:
        return roster(rid).dept_of
    except api.ApiError:
        return {}


def ops_inputs(day: str | None = None, shift: str | None = None):
    """(roster, working{emp: dept}, bands{emp: band}, day, shift) for the dispatch engine.
    Falls back to imported tenant staff when no roster exists. Never raises."""
    from . import auth, dispatch, platform, tenancy

    rid = current_roster_id()
    ro = None
    if rid is not None:
        try:
            ro = roster(rid)
        except api.ApiError:
            ro = None
    d0, s0 = dispatch.ops_context(ro)
    day, shift = day or d0, shift or s0
    try:
        staff_rows = platform.staff() if auth.role() != "worker" else []
    except platform.PlatformError:
        staff_rows = []
    working = dispatch.on_shift(ro, staff_rows, day, shift)
    try:
        bands = {s.employee_id: s.band for s in scores(None)} if auth.role() != "worker" else {}
    except api.ApiError:
        bands = {}
    if auth.role() in ("owner", "dept_head", "platform_admin"):  # managers publish the roster snapshot the engine ranks from
        sig = hash((day, shift, tuple(sorted(working.items())), tuple(sorted(bands.items()))))
        if st.session_state.get("ctx_sig") != sig:
            try:
                platform.set_context(day, shift, working, bands, tenancy.floors())
                st.session_state["ctx_sig"] = sig
            except platform.PlatformError:
                pass
        if ro is not None and st.session_state.get("roster_pub") != ro.id:  # employees read their own shifts from this
            try:
                platform.publish_roster(ro.week_start, ro.assignments)
                st.session_state["roster_pub"] = ro.id
            except platform.PlatformError:
                pass
    elif auth.role() == "worker":
        try:
            working = platform.get_context().get("working", {})
        except platform.PlatformError:
            working = {}
    return ro, working, bands, day, shift
