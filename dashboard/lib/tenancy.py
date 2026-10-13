"""The signed-in user's hotel group (tenant), fetched from the platform API and cached in the session.
Switching tenant re-points the ML API client (each tenant has its own data source) and clears caches."""

from __future__ import annotations

import streamlit as st

from . import platform
from .config import env_settings

DEMO_ID = "org_demo"
PLANS = {
    "starter": {"label": "Starter", "properties": 1, "staff": 80, "modules": ["Forecast & roster", "Dispatch + photo proof", "Inventory"]},
    "growth": {
        "label": "Growth",
        "properties": 5,
        "staff": 400,
        "modules": ["Everything in Starter", "Retention, what-if, closed loop", "Voice to task"],
    },
    "chain": {
        "label": "Chain",
        "properties": None,
        "staff": None,
        "modules": ["Everything in Growth", "Unlimited properties", "Own backend URL"],
    },
}
SIGNED_OUT = {
    "id": None,
    "name": "Hospitality Operations Intelligence",
    "brand_color": "#f07a2c",
    "plan": "growth",
    "settings": {},
    "modules": [],
    "use_mocks": True,
    "api_base_url": None,
    "is_demo": False,
    "onboarded": True,
    "onboarding_step": 0,
    "status": "active",
    "properties": [],
}


def active() -> dict:
    return st.session_state.get("tenant") or SIGNED_OUT


def refresh() -> dict:
    try:
        st.session_state["tenant"] = platform.workspace()
    except platform.PlatformError:
        pass
    return active()


def bootstrap() -> dict:
    """Called by every page: make sure the ML API client points at this tenant's data source."""
    t = active()
    if t.get("id") and "properties" not in t:
        t = refresh()
    _apply(t)
    return t


def _apply(t: dict) -> None:
    st.session_state["settings_override"] = {
        "use_mocks": bool(t.get("use_mocks", True)),
        "api_base_url": (t.get("api_base_url") or env_settings().api_base_url).rstrip("/"),
    }


def on_tenant_change() -> None:
    for k in (
        "demo_week",
        "week_start",
        "roster_raw",
        "loop_raw",
        "last_roster_id",
        "created_tasks",
        "task_status_override",
        "voice_res",
        "voice_task",
        "whatif_history",
        "selected_employee",
        "ctx_sig",
    ):
        st.session_state.pop(k, None)
    st.cache_data.clear()
    refresh()
    _apply(active())


def settings_of(t: dict) -> dict:
    return t.get("settings") or {}


def active_settings() -> dict:
    return settings_of(active())


def rooms() -> int:
    props = active().get("properties") or []
    return int(props[0]["rooms"]) if props else 45


def floors() -> int:
    props = active().get("properties") or []
    return int(props[0].get("floors") or 4) if props else 4
