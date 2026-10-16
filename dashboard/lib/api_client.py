"""The only module that talks to the backend. Pages never import requests.

Every public function serves the mock fixtures when settings.use_mocks is true,
otherwise calls API_BASE_URL. Any failure raises ApiError with a plain-language
message; pages show it with ui.safe_call (banner, never a stack trace).
"""

from __future__ import annotations

import os
from typing import Any

import requests

from . import mock_backend as mock
from . import wake
from .config import Settings, current_settings

_session = requests.Session()

OPS_KEY_ENV = "HOI_OPS_API_KEY"  # shared secret of the ops / ML API (backend/auth.py); never printed or logged
OPS_KEY_HEADER = "X-HOI-Key"
KNOWN_OPS_URLS = ("https://hoi-ops.onrender.com",)  # the deployed ops API (also OPS_API_URL in platform_api/seed.py)


def _origin(url: str) -> str:
    from urllib.parse import urlsplit

    p = urlsplit(url.strip().lower())
    return f"{p.scheme}://{p.netloc}"


def _auth_headers(base: str) -> dict[str, str]:
    """X-HOI-Key, only for our own ops API: the env API_BASE_URL, the known deployment or a local server. A workspace can
    point "Server address" anywhere, and the shared secret must never be sent to a server we do not run."""
    key = os.getenv(OPS_KEY_ENV, "").strip()
    if not key:
        return {}
    trusted = {_origin(u) for u in (*KNOWN_OPS_URLS, os.getenv("API_BASE_URL", ""), os.getenv("OPS_API_URL", "")) if u.strip()}
    return {OPS_KEY_HEADER: key} if _origin(base) in trusted or wake.is_local(base) else {}


class ApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None, detail: Any = None, endpoint: str = ""):
        super().__init__(message)
        self.message, self.status, self.detail, self.endpoint = message, status, detail, endpoint


def _detail_text(detail: Any) -> str:
    if isinstance(detail, list):  # FastAPI validation errors
        parts = []
        for e in detail:
            if isinstance(e, dict):
                loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("body", "query"))
                parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
        return "; ".join(parts) or str(detail)
    return str(detail) if detail is not None else ""


def _friendly(status: int, detail: Any, endpoint: str, base: str) -> str:
    d = _detail_text(detail)
    if status == 404:
        return f"Not found. {d}".strip()
    if status == 422:
        return f"Some of the input is not right: {d}"
    if status == 501:
        return d or "This is not available right now."
    if status == 503:
        return f"The server could not do this right now: {d}" if d else "The server is busy. Try again in a minute."
    if status == 401:
        return "The data server refused the request: this portal's access key (HOI_OPS_API_KEY) is missing or wrong."
    if status == 403:
        return "This was blocked. Check the text for unusual characters."
    if status >= 500:
        return f"Something went wrong on the server. Try again. {d}".strip()
    return f"Something went wrong (code {status}). {d}".strip()


def _http(
    method: str,
    path: str,
    s: Settings,
    *,
    params: dict | None = None,
    json: Any = None,
    timeout: float | None = None,
    data: dict | None = None,
    files: dict | None = None,
) -> Any:
    url = s.api_base_url + path
    try:
        r = wake.request(  # one retry with a longer timeout while a sleeping (Render free tier) server wakes up
            method,
            url,
            s.api_base_url,
            session=_session,
            params=params,
            json=json,
            data=data,
            files=files,
            headers=_auth_headers(s.api_base_url),
            timeout=timeout or s.timeout_s,
        )
    except requests.exceptions.ConnectionError as e:
        raise ApiError(
            "The server is not answering. Try again in a minute, or press Refresh.",
            endpoint=path,
            detail=str(e),
        ) from None
    except requests.exceptions.Timeout:
        raise ApiError(
            "The server took too long. It may be waking up (this can take about a minute). Wait a minute, then press Refresh.",
            endpoint=path,
        ) from None
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:300] if "<html" not in r.text[:200].lower() else None
        raise ApiError(_friendly(r.status_code, detail, path, s.api_base_url), status=r.status_code, detail=detail, endpoint=path)
    try:
        return r.json()
    except ValueError:
        raise ApiError(f"{path} returned a non-JSON response.", status=r.status_code, endpoint=path) from None


def _mock(fn, *args, endpoint: str = "") -> Any:
    try:
        return fn(*args)
    except mock.MockError as e:
        raise ApiError(_friendly(e.status, e.detail, endpoint, "mock"), status=e.status, detail=e.detail, endpoint=endpoint) from None


def _s(settings: Settings | None) -> Settings:
    return settings or current_settings()


# ------------------------------------------------------------------ endpoints
def health(settings: Settings | None = None) -> dict:
    s = _s(settings)
    return _mock(mock.load, "health.json", endpoint="/health") if s.use_mocks else _http("GET", "/health", s)


def get_alerts(inventory: list[dict] | None = None, settings: Settings | None = None) -> dict:
    """Hotel alerts (plain sentences, severity, reason, one action). With inventory rows the stock-out rule runs too."""
    s = _s(settings)
    if s.use_mocks:
        return _mock(mock.alerts, {"inventory": inventory}, endpoint="/alerts")
    if inventory is not None:
        return _http("POST", "/alerts", s, json={"inventory": inventory})
    return _http("GET", "/alerts", s)


def get_forecast(date_from: str, date_to: str, as_of: str | None = None, settings: Settings | None = None) -> dict:
    s = _s(settings)
    params = {"from": date_from, "to": date_to, **({"as_of": as_of} if as_of else {})}
    return _mock(mock.forecast, params, endpoint="/forecast") if s.use_mocks else _http("GET", "/forecast", s, params=params)


def score_attrition(
    week_start: str | None = None,
    employee_ids: list[str] | None = None,
    settings: Settings | None = None,
    live_signals: dict | None = None,
) -> list[dict]:
    """live_signals: the platform's weekly staff facts (GET /people/signals); people without them use the demo data."""
    s = _s(settings)
    body = {k: v for k, v in {"week_start": week_start, "employee_ids": employee_ids, "live_signals": live_signals}.items() if v}
    return _mock(mock.score, body, endpoint="/attrition/score") if s.use_mocks else _http("POST", "/attrition/score", s, json=body)


def rescore_attrition(
    employee_id: str,
    feature_overrides: dict | None = None,
    protected_weekends_off: int | None = None,
    week_start: str | None = None,
    settings: Settings | None = None,
) -> dict:
    s = _s(settings)
    body: dict[str, Any] = {"employee_id": employee_id}
    if feature_overrides:
        body["feature_overrides"] = feature_overrides
    if protected_weekends_off:
        body["protected_weekends_off"] = int(protected_weekends_off)
    if week_start:
        body["week_start"] = week_start
    return _mock(mock.rescore, body, endpoint="/attrition/rescore") if s.use_mocks else _http("POST", "/attrition/rescore", s, json=body)


def generate_roster(
    week_start: str | None = None,
    protected_ids: list[str] | None = None,
    use_cache: bool = True,
    deterministic: bool = True,
    simulate_infeasible: bool = False,
    settings: Settings | None = None,
) -> dict:
    s = _s(settings)
    body: dict[str, Any] = {"protected_ids": protected_ids or [], "use_cache": use_cache, "deterministic": deterministic}
    if week_start:
        body["week_start"] = week_start
    if s.use_mocks:
        return _mock(mock.generate_roster, {**body, "_simulate_infeasible": simulate_infeasible}, endpoint="/roster/generate")
    return _http("POST", "/roster/generate", s, json=body, timeout=s.roster_timeout_s)


def get_roster(roster_id: int | str, settings: Settings | None = None) -> dict:
    s = _s(settings)
    return _mock(mock.get_roster, roster_id, endpoint=f"/roster/{roster_id}") if s.use_mocks else _http("GET", f"/roster/{roster_id}", s)


def create_task(
    idempotency_key: str,
    title: str,
    assignee: str,
    *,
    supervisor: str | None = None,
    description: str = "",
    employee_id: str | None = None,
    due_in_minutes: int | None = None,
    settings: Settings | None = None,
) -> dict:
    s = _s(settings)
    body = {
        k: v
        for k, v in {
            "idempotency_key": idempotency_key,
            "title": title,
            "assignee": assignee,
            "supervisor": supervisor,
            "description": description,
            "employee_id": employee_id,
            "due_in_minutes": due_in_minutes,
        }.items()
        if v not in (None, "")
    }
    return _mock(mock.create_task, body, endpoint="/tasks") if s.use_mocks else _http("POST", "/tasks", s, json=body)


def list_tasks(status: str | None = None, employee_id: str | None = None, settings: Settings | None = None) -> list[dict]:
    s = _s(settings)
    params = {k: v for k, v in {"status": status, "employee_id": employee_id}.items() if v}
    return _mock(mock.list_tasks, status, employee_id, endpoint="/tasks") if s.use_mocks else _http("GET", "/tasks", s, params=params)


def ack_task(task_id: int | str, settings: Settings | None = None) -> dict:
    s = _s(settings)
    return _mock(mock.ack_task, task_id, endpoint=f"/tasks/{task_id}/ack") if s.use_mocks else _http("POST", f"/tasks/{task_id}/ack", s)


def done_task(task_id: int | str, settings: Settings | None = None) -> dict:
    s = _s(settings)
    return _mock(mock.done_task, task_id, endpoint=f"/tasks/{task_id}/done") if s.use_mocks else _http("POST", f"/tasks/{task_id}/done", s)


def run_loop(settings: Settings | None = None) -> dict:
    s = _s(settings)
    return (
        _mock(mock.run_loop, endpoint="/loop/run") if s.use_mocks else _http("POST", "/loop/run", s, timeout=max(90.0, s.roster_timeout_s))
    )


def list_interventions(
    status: str = "all", employee_id: str | None = None, week_start: str | None = None, settings: Settings | None = None
) -> list[dict]:
    """GET /interventions: stored closed-loop interventions with their linked task status (open/acked/done/overdue)."""
    s = _s(settings)
    params = {k: v for k, v in {"status": status, "employee_id": employee_id, "week_start": week_start}.items() if v}
    return _mock(mock.interventions, params, endpoint="/interventions") if s.use_mocks else _http("GET", "/interventions", s, params=params)


def metrics_overview(replacement_cost_inr: float | None = None, settings: Settings | None = None) -> dict:
    s = _s(settings)
    params = {"replacement_cost_inr": replacement_cost_inr} if replacement_cost_inr else {}
    return _mock(mock.metrics, params, endpoint="/metrics/overview") if s.use_mocks else _http("GET", "/metrics/overview", s, params=params)


def demo_reset(settings: Settings | None = None) -> dict:
    s = _s(settings)
    return _mock(mock.reset, endpoint="/demo/reset") if s.use_mocks else _http("POST", "/demo/reset", s, timeout=60)


def get_clock(settings: Settings | None = None) -> dict:
    s = _s(settings)
    return _mock(mock.get_clock, endpoint="/demo/clock") if s.use_mocks else _http("GET", "/demo/clock", s)


def set_clock(multiplier: float, settings: Settings | None = None) -> dict:
    s = _s(settings)
    body = {"multiplier": float(multiplier)}
    return _mock(mock.set_clock, body, endpoint="/demo/clock") if s.use_mocks else _http("POST", "/demo/clock", s, json=body)


def voice_ingest(file: str, create_task: bool = False, settings: Settings | None = None) -> dict:
    s = _s(settings)
    body = {"file": file, "create_task": create_task}
    return (
        _mock(mock.voice_ingest, body, endpoint="/voice/ingest")
        if s.use_mocks
        else _http("POST", "/voice/ingest", s, json=body, timeout=60)
    )


# ------------------------------------------------------------------ hotel onboarding by voice (backend/onboarding)
def onboarding_start(
    language: str = "en", hotel_type: str | None = None, hotel_name: str | None = None, settings: Settings | None = None
) -> dict:
    s = _s(settings)
    body = {k: v for k, v in {"language": language, "hotel_type": hotel_type, "hotel_name": hotel_name}.items() if v}
    return (
        _mock(mock.onboarding_start, body, endpoint="/onboarding/start")
        if s.use_mocks
        else _http("POST", "/onboarding/start", s, json=body)
    )


def onboarding_answer(
    session_id: str,
    text: str | None = None,
    audio: tuple[str, bytes, str] | None = None,
    consent: bool = False,
    settings: Settings | None = None,
) -> dict:
    """Typed text (JSON) or an audio recording (multipart: file name, bytes, content type)."""
    s = _s(settings)
    if s.use_mocks:
        body = {"session_id": session_id, "text": text, "consent": consent}
        return _mock(mock.onboarding_answer, body, audio, endpoint="/onboarding/answer")
    if audio is not None:
        form = {"session_id": session_id, "consent": "true" if consent else "false"}
        return _http("POST", "/onboarding/answer", s, data=form, files={"file": audio}, timeout=90)
    return _http("POST", "/onboarding/answer", s, json={"session_id": session_id, "text": text, "consent": consent}, timeout=60)


def onboarding_edit(session_id: str, field: str, value: Any, settings: Settings | None = None) -> dict:
    s = _s(settings)
    body = {"session_id": session_id, "field": field, "value": value}
    return (
        _mock(mock.onboarding_edit, body, endpoint="/onboarding/field")
        if s.use_mocks
        else _http("PATCH", "/onboarding/field", s, json=body)
    )


def onboarding_summary(session_id: str, settings: Settings | None = None) -> dict:
    s = _s(settings)
    if s.use_mocks:
        return _mock(mock.onboarding_summary, session_id, endpoint="/onboarding/summary")
    return _http("GET", "/onboarding/summary", s, params={"session": session_id})


def onboarding_confirm(session_id: str, acknowledged_legal_fields: list[str], settings: Settings | None = None) -> dict:
    s = _s(settings)
    body = {"session": session_id, "acknowledged_legal_fields": list(acknowledged_legal_fields)}
    return (
        _mock(mock.onboarding_confirm, body, endpoint="/onboarding/confirm")
        if s.use_mocks
        else _http("POST", "/onboarding/confirm", s, json=body)
    )


def onboarding_demo_transcript(settings: Settings | None = None) -> dict:
    s = _s(settings)
    path = "/onboarding/demo-transcript"
    return _mock(mock.onboarding_demo_transcript, endpoint=path) if s.use_mocks else _http("GET", path, s)


def property_settings(property_id: str, settings: Settings | None = None) -> dict:
    s = _s(settings)
    path = f"/properties/{property_id}/settings"
    return _mock(mock.onboarding_property_settings, property_id, endpoint=path) if s.use_mocks else _http("GET", path, s)


# ------------------------------------------------------------------ mock-only data + raw explorer
def heroes() -> dict:
    """12-week hero trajectories. No API endpoint serves this; it always comes from the mock file."""
    return _mock(mock.load, "heroes.json", endpoint="heroes.json")


def raw_request(method: str, path: str, body: Any = None, settings: Settings | None = None) -> Any:
    """Admin debugging: call any endpoint and return the raw JSON."""
    s = _s(settings)
    path = "/" + path.lstrip("/")
    route, _, query = path.partition("?")
    params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
    if not s.use_mocks:
        return _http(method.upper(), route, s, params=params or None, json=body if method.upper() != "GET" else None, timeout=60)
    m, parts = method.upper(), route.strip("/").split("/")
    table = {
        ("GET", "health"): lambda: mock.load("health.json"),
        ("GET", "forecast"): lambda: mock.forecast(params),
        ("POST", "attrition/score"): lambda: mock.score(body or {}),
        ("POST", "attrition/rescore"): lambda: mock.rescore(body or {}),
        ("POST", "roster/generate"): lambda: mock.generate_roster(body or {}),
        ("GET", "tasks"): lambda: mock.list_tasks(params.get("status"), params.get("employee_id")),
        ("POST", "tasks"): lambda: mock.create_task(body or {}),
        ("GET", "demo/clock"): mock.get_clock,
        ("POST", "demo/clock"): lambda: mock.set_clock(body or {}),
        ("POST", "demo/reset"): mock.reset,
        ("POST", "loop/run"): mock.run_loop,
        ("GET", "interventions"): lambda: mock.interventions(params),
        ("GET", "metrics/overview"): lambda: mock.metrics(params),
        ("POST", "voice/ingest"): lambda: mock.voice_ingest(body or {}),
    }
    key = "/".join(parts)
    if (m, key) in table:
        return _mock(table[(m, key)], endpoint=route)
    if m == "GET" and len(parts) == 2 and parts[0] == "roster":
        return _mock(mock.get_roster, parts[1], endpoint=route)
    if m == "POST" and len(parts) == 3 and parts[0] == "tasks" and parts[2] in ("ack", "done"):
        return _mock(mock.ack_task if parts[2] == "ack" else mock.done_task, parts[1], endpoint=route)
    raise ApiError(f"No mock for {m} {route}.", status=404, endpoint=route)
