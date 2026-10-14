"""Client for the HOI platform API (platform_api/hoi_platform): tenants, accounts, dispatch, photos, inventory, audit.

PLATFORM_API_URL decides where it lives:
  embedded (default) – the same FastAPI app runs in-process (no separate server; real routing, validation and auth)
  https://...        – a deployed platform API

Every call goes over the API with the signed-in user's bearer token; the frontend never touches the database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from . import wake

BACKEND_DIR = Path(__file__).resolve().parents[2] / "platform_api"
SLOW_S = 120.0  # calls that wait on the tourism portal (a free host that cold-starts; the API retries once): see portal_client


class PlatformError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message, self.status = message, status


def mode() -> str:
    return os.getenv("PLATFORM_API_URL", "embedded").strip() or "embedded"


@st.cache_resource(show_spinner=False)
def _embedded_client():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from fastapi.testclient import TestClient

    from hoi_platform.main import create_app

    return TestClient(create_app())


def _token() -> str | None:
    return st.session_state.get("auth_token")


def _send(method: str, path: str, headers: dict, timeout: float | None = None, **kw) -> Any:
    try:
        if mode() == "embedded":
            return _embedded_client().request(method, path, headers=headers, **kw)
        if timeout:
            kw["timeout"] = timeout
        base = mode().rstrip("/")
        return wake.request(method, base + path, base, headers=headers, **kw)  # one retry while a sleeping server wakes up
    except requests.exceptions.RequestException:
        raise PlatformError("The server is not answering. It may be waking up: try again in a minute.") from None


def try_refresh() -> bool:
    """Use the stored refresh token to get a new access token (rotating the refresh token). Platform admins get their
    hotel-scoped token re-issued for the hotel they had open."""
    rt = st.session_state.get("refresh_token")
    if not rt:
        return False
    r = _send("POST", "/auth/refresh", {}, json={"refresh_token": rt})
    if r.status_code != 200:
        for k in ("refresh_token", "auth_token", "platform_token", "user"):
            st.session_state.pop(k, None)
        return False
    j = r.json()
    st.session_state["refresh_token"] = j["refresh_token"]
    st.session_state["user"] = j["user"]
    st.session_state["_rt_dirty"] = True  # tells the browser-cookie writer to store the rotated token
    if j["user"]["role"] == "platform_admin":
        st.session_state["platform_token"] = j["token"]
        st.session_state["auth_token"] = j["token"]  # console token; a hotel is re-opened only if one was open
        tid = st.session_state.get("imp_tid")  # set only in the hotel portal, after the admin chose a hotel
        if tid:
            imp = _send("POST", f"/auth/impersonate/{tid}", {"Authorization": f"Bearer {j['token']}"})
            if imp.status_code == 200:
                st.session_state["auth_token"] = imp.json()["token"]
                st.session_state["tenant"] = imp.json()["tenant"]
            else:
                st.session_state.pop("imp_tid", None)
                st.session_state["tenant"] = None
    else:
        st.session_state["auth_token"] = j["token"]
        st.session_state["tenant"] = j.get("tenant") or st.session_state.get("tenant")
    return True


def call(
    method: str,
    path: str,
    *,
    json: Any = None,
    params: dict | None = None,
    files: dict | None = None,
    data: dict | None = None,
    token: str | None = None,
    raw: bool = False,
    auth: bool = True,
    timeout: float | None = None,
    _retry: bool = True,
) -> Any:
    tok = token or (_token() if auth else None)
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    r = _send(method, path, headers, timeout, json=json, params=params, files=files, data=data)
    if r.status_code == 401 and auth and _retry and try_refresh():  # access token expired: refresh once and retry
        fresh = st.session_state.get("platform_token") if token and token == st.session_state.get("platform_token") else None
        return call(
            method, path, json=json, params=params, files=files, data=data, token=fresh, raw=raw, auth=auth, timeout=timeout, _retry=False
        )
    if r.status_code == 401 and auth:
        st.session_state.pop("auth_token", None)
        st.session_state.pop("user", None)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:200]
        if isinstance(detail, list):  # pydantic validation errors
            detail = "; ".join(f"{'.'.join(str(x) for x in e.get('loc', [])[1:])}: {e.get('msg')}" for e in detail)
        raise PlatformError(str(detail or f"HTTP {r.status_code}"), r.status_code)
    if r.status_code == 204:
        return None
    return r.content if raw else r.json()


def logout_token(refresh_token: str) -> None:
    try:
        call("POST", "/auth/logout", json={"refresh_token": refresh_token}, auth=False)
    except PlatformError:
        pass


def _pid() -> str | None:
    """The property this session looks at (lib.tenancy.current_property); None = the API's default (first property)."""
    from . import tenancy  # local import: tenancy imports this module

    return tenancy.property_id()


def _pid_params() -> dict:
    pid = _pid()
    return {"property_id": pid} if pid else {}


def rooms() -> dict:
    return call("GET", "/rooms", params=_pid_params())


def room_action(rid: str, action: str, body: dict | None = None) -> dict:
    return call("POST", f"/rooms/{rid}/{action}", json=body or {})


def room_qr(rid: str) -> bytes:
    return call("GET", f"/rooms/{rid}/qr.svg", raw=True)


def publish_roster(week_start: str | None, assignments: list[dict]) -> dict:
    return call("PUT", "/dispatch/roster", json={"week_start": week_start, "assignments": assignments})


@st.cache_data(ttl=3600, show_spinner=False)
def asset_data_uri(path: str) -> str | None:
    """A small static asset served by the platform API (e.g. a hotel logo at /shared/brand/...) as a data: URI, fetched
    server-side so it works in embedded mode too (no browser-reachable API needed). None if unavailable."""
    import base64

    if not path.startswith("/") or ".." in path:
        return None
    try:
        r = _send("GET", path, {})
    except PlatformError:
        return None
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
    if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) > 300_000:
        return None
    return f"data:{ctype};base64," + base64.b64encode(r.content).decode()


def public_url() -> str:
    """Where browsers reach the platform API (worker portal, guest QR pages). Needs the API running as a service."""
    return os.getenv("PLATFORM_PUBLIC_URL", "http://localhost:8100").rstrip("/")


# ------------------------------------------------------------------ auth
def login(username: str, password: str) -> dict:
    return call("POST", "/auth/login", json={"username": username, "password": password}, auth=False)


def register(code: str, username: str, password: str, employee_id: str | None) -> dict:
    return call(
        "POST", "/auth/register", json={"code": code, "username": username, "password": password, "employee_id": employee_id}, auth=False
    )


def demo_accounts() -> list[dict]:
    return call("GET", "/auth/demo-accounts", auth=False)


def demo_login(username: str) -> dict:
    return call("POST", f"/auth/demo/{username}", auth=False)


def me() -> dict:
    return call("GET", "/auth/me")


def set_prefs(prefs: dict) -> dict:
    return call("PATCH", "/auth/me/prefs", json={"prefs": prefs})


def impersonate(tid: str, platform_token: str) -> dict:
    return call("POST", f"/auth/impersonate/{tid}", token=platform_token)


# ------------------------------------------------------------------ platform console (uses the unscoped platform token)
def _pt() -> str | None:
    return st.session_state.get("platform_token")


def tenants() -> list[dict]:
    return call("GET", "/platform/tenants", token=_pt())


def create_tenant(**body) -> dict:
    return call("POST", "/platform/tenants", json=body, token=_pt())


def update_tenant(tid: str, **fields) -> dict:
    return call("PATCH", f"/platform/tenants/{tid}", json=fields, token=_pt())


def delete_tenant(tid: str) -> None:
    call("DELETE", f"/platform/tenants/{tid}", token=_pt())


def platform_invite(tid: str, role: str = "owner") -> dict:
    return call("POST", f"/platform/tenants/{tid}/invites", json={"role": role}, token=_pt())


def platform_audit(tenant_id: str | None = None, limit: int = 500) -> list[dict]:
    return call("GET", "/platform/audit", params={k: v for k, v in {"tenant_id": tenant_id, "limit": limit}.items() if v}, token=_pt())


# ------------------------------------------------------------------ workspace
def workspace() -> dict:
    return call("GET", "/workspace")


def update_workspace(**fields) -> dict:
    return call("PATCH", "/workspace", json=fields)


def properties() -> list[dict]:
    return call("GET", "/workspace/properties")


def add_property(name: str, region: str, rooms: int, floors: int) -> dict:
    return call("POST", "/workspace/properties", json={"name": name, "region": region, "rooms": rooms, "floors": floors})


def staff() -> list[dict]:
    return call("GET", "/workspace/staff")


def import_staff(rows: list[dict]) -> dict:
    return call("POST", "/workspace/staff/import", json={"rows": rows})


def users() -> list[dict]:
    return call("GET", "/workspace/users")


def set_user_active(uid: str, active: bool) -> dict:
    return call("PATCH", f"/workspace/users/{uid}", json={"active": active})


def invites() -> list[dict]:
    return call("GET", "/workspace/invites")


def create_invite(role: str) -> dict:
    return call("POST", "/workspace/invites", json={"role": role})


# ------------------------------------------------------------------ dispatch
def set_context(day: str | None, shift: str | None, working: dict, bands: dict, floors: int = 4) -> dict:
    """Manual override of who is on shift (practice clock / demos); it ends with the current shift."""
    return call("PUT", "/dispatch/context", json={"day": day, "shift": shift, "working": working, "bands": bands, "floors": floors})


def publish_bands(bands: dict, floors: int = 4) -> dict:
    """Chance-of-leaving bands and floor count only; who is on shift keeps following the live roster."""
    return call("PUT", "/dispatch/context", json={"override": False, "bands": bands, "floors": floors})


def clear_context_override() -> dict:
    return call("DELETE", "/dispatch/context/override")


def get_context() -> dict:
    return call("GET", "/dispatch/context")


def create_job(title: str, department: str | None, room: str | None, urgency: str, source: str) -> dict:
    body = {"title": title, "department": department, "room": room, "urgency": urgency, "source": source, **_pid_params()}
    return call("POST", "/dispatch/jobs", json=body)


def jobs(status: str | None = None, worker: str | None = None) -> list[dict]:
    return call("GET", "/dispatch/jobs", params={k: v for k, v in {"status": status, "worker": worker}.items() if v})


def job_action(jid: str, action: str, employee_id: str | None = None) -> dict:
    return call("POST", f"/dispatch/jobs/{jid}/{action}", json={"employee_id": employee_id})


def retry(jid: str) -> dict:
    return call("POST", f"/dispatch/jobs/{jid}/retry")


def link_task(jid: str, task_id: str) -> dict:
    return call("POST", f"/dispatch/jobs/{jid}/link-task", json={"task_id": str(task_id)})


def upload_photo(jid: str, kind: str, data: bytes, employee_id: str | None) -> dict:
    form = {"kind": kind, **({"employee_id": employee_id} if employee_id else {})}
    return call("POST", f"/dispatch/jobs/{jid}/photos", data=form, files={"file": ("photo.jpg", data, "image/jpeg")})


def job_photos(jid: str) -> dict:
    return call("GET", f"/dispatch/jobs/{jid}/photos")


def photo_bytes(pid: str) -> bytes:
    return call("GET", f"/dispatch/photos/{pid}", raw=True)


def performance(days: int = 14) -> dict:
    """Per-worker performance score vs each person's own previous period (owner / hr / dept_head; coaching aid)."""
    return call("GET", "/dispatch/performance", params={"days": int(days)})


def worklog(day: str | None = None, employee_id: str | None = None, department: str | None = None) -> dict:
    """One day's jobs with wait / work minutes and photo ids, plus a per-person summary (owner / hr / dept_head; a
    department head gets their own department only)."""
    params = {k: v for k, v in {"date": day, "employee_id": employee_id, "department": department}.items() if v}
    return call("GET", "/dispatch/worklog", params=params)


def reset_dispatch() -> None:
    call("POST", "/dispatch/reset")


# ------------------------------------------------------------------ inventory
def inv(method: str, path: str, **kw) -> Any:
    return call(method, f"/inventory{path}", **kw)


# ------------------------------------------------------------------ hospitality suite (docs/HOSPITALITY_SUITE.md sections 1, 4, 5)
def feature_missing(e: PlatformError) -> bool:
    """True when the platform API has no such route yet (FastAPI's bare 404), as opposed to a 404 for missing data."""
    return e.status == 404 and e.message in ("Not Found", "HTTP 404")


def platform_insights(days: int = 30) -> dict:
    return call("GET", "/platform/insights", params={"days": int(days)}, token=_pt())


def hotel_profile() -> dict:
    return call("GET", "/hotel/profile", params=_pid_params())


def save_hotel_profile(profile: dict) -> dict:
    return call("PUT", "/hotel/profile", json=profile, params=_pid_params())


# ------------------------------------------------------------------ property settings, recognition, staffing requests
def update_property(pid: str, **fields) -> dict:
    """Owner: mode (hotel|homestay), incentive_monthly_budget_cap, recognition_leaderboard_opt_in, recognition, portal_api_key."""
    return call("PATCH", f"/workspace/properties/{pid}", json=fields)


def recognition_summary(month: str | None = None) -> dict:
    return call("GET", "/recognition/summary", params={**_pid_params(), **({"month": month} if month else {})})


def staffing_requests() -> list[dict]:
    return call("GET", "/staffing/requests", params=_pid_params())


def create_staffing_request(**body) -> dict:
    return call("POST", "/staffing/requests", json={**_pid_params(), **body}, timeout=SLOW_S)


def resend_staffing_request(rid: str) -> dict:
    return call("POST", f"/staffing/requests/{rid}/send", timeout=SLOW_S)


def guest_summary() -> dict:
    return call("GET", "/guest-services/summary")


def late_checkouts() -> Any:
    return call("GET", "/guest-services/late-checkouts")


def decide_late_checkout(lid: str, approve: bool, note: str = "") -> dict:
    return call("POST", f"/guest-services/late-checkouts/{lid}/decide", json={"approve": bool(approve), "note": note})


def guest_feedback(days: int = 30) -> Any:
    return call("GET", "/guest-services/feedback", params={"days": int(days)})


def guest_checkouts(day: str | None = None) -> Any:
    return call("GET", "/guest-services/checkouts", params={"date": day} if day else None)


# ------------------------------------------------------------------ photo proof: which job kinds need a before / after photo
def photo_proof_settings() -> dict:
    """{"kinds": [{kind, label, before, after}], "defaults": [...]} (owner edits; others read)."""
    return call("GET", "/hotel/settings/photo-proof")  # per hotel (tenant), not per property


def save_photo_proof_settings(kinds: list[dict]) -> dict:
    return call("PUT", "/hotel/settings/photo-proof", json={"kinds": kinds})
