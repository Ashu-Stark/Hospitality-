"""The signed-in user's hotel group (tenant), fetched from the platform API and cached in the session.
Switching tenant re-points the ML API client (each tenant has its own data source) and clears caches."""

from __future__ import annotations

import streamlit as st

from . import platform
from .config import env_settings

DEMO_ID = "org_demo"
PLANS = {
    "starter": {"label": "Starter", "properties": 1, "staff": 80, "modules": ["Shift plan", "Jobs + photo proof", "Stock"]},
    "growth": {
        "label": "Growth",
        "properties": 5,
        "staff": 400,
        "modules": ["Everything in Starter", "May leave soon? check-ins", "Voice notes into tasks"],
    },
    "chain": {
        "label": "Chain",
        "properties": None,
        "staff": None,
        "modules": ["Everything in Growth", "Any number of hotels", "Own server"],
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
        "property_id",
    ):
        st.session_state.pop(k, None)
    st.cache_data.clear()
    if active().get("id"):  # a platform admin's console token has no workspace to refresh
        refresh()
    _apply(active())


def settings_of(t: dict) -> dict:
    return t.get("settings") or {}


def active_settings() -> dict:
    return settings_of(active())


# ------------------------------------------------------------------ current property (a hotel group can have several)
def properties() -> list[dict]:
    return active().get("properties") or []


def current_property() -> dict | None:
    """The property this browser session looks at: the session choice, else the user's saved preference, else the first."""
    props = properties()
    if not props:
        return None
    want = st.session_state.get("property_id") or ((st.session_state.get("user") or {}).get("prefs") or {}).get("property_id")
    return next((p for p in props if p["id"] == want), props[0])


def property_id() -> str | None:
    p = current_property()
    return p["id"] if p else None


def mode() -> str:
    """'homestay' (simple app, plain words) or 'hotel' (everything) for the current property."""
    p = current_property()
    if not p:
        return "hotel"
    m = p.get("mode")
    return m if m in ("hotel", "homestay") else ("homestay" if int(p.get("rooms") or 0) <= 10 else "hotel")


def is_homestay() -> bool:
    return mode() == "homestay"


def set_property(pid: str) -> None:
    st.session_state["property_id"] = pid
    try:
        platform.set_prefs({"property_id": pid})
        u = st.session_state.get("user")
        if u is not None:
            u["prefs"] = {**(u.get("prefs") or {}), "property_id": pid}
    except platform.PlatformError:
        pass


def rooms() -> int:
    p = current_property()
    return int(p["rooms"]) if p else 45


def floors() -> int:
    p = current_property()
    return int(p.get("floors") or 4) if p else 4
