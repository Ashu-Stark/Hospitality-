"""Client for the Uttarakhand tourism portal (portal/): forwards a hotel's staffing request to the portal's staffing partners,
and asks how many job seekers fit a skill (retention check, read-only).

    POST {PORTAL_API_URL}/api/v1/ingest/staffing-request      header X-API-Key: <the property's portal business API key>
    GET  {PORTAL_API_URL}/api/v1/ingest/candidate-matches?skill=&limit=   same header; count + anonymised previews

PORTAL_API_URL defaults to https://hoi-portal.vercel.app. The key is a secret: it is read from the property's settings at call
time, sent only in the header, and never logged, stored in errors or returned. Tests replace `send` with a fake (no network).

Body (no personal data: department / skill, dates and a head count only):
    {"external_id", "department", "skill", "date_from", "date_to", "openings", "note"}
"""

from __future__ import annotations

import logging
import os

import httpx

DEFAULT_PORTAL_URL = "https://hoi-portal.vercel.app"
PATH = "/api/v1/ingest/staffing-request"
MATCHES_PATH = "/api/v1/ingest/candidate-matches"
TIMEOUT_S = 10.0
log = logging.getLogger("hoi.portal_client")


class PortalError(Exception):
    """Sending failed. `message` is safe to store and show (never contains the key)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message, self.status = message, status


def base_url() -> str:
    return (os.getenv("PORTAL_API_URL") or DEFAULT_PORTAL_URL).strip().rstrip("/")


HINTS = {
    401: "the portal API key was not accepted",
    403: "the portal API key was not accepted",
    404: "the portal does not offer this yet",
    422: "the portal rejected the request format",
}


def _call(method: str, path: str, api_key: str, *, json: dict | None = None, params: dict | None = None) -> dict:
    """One request to the portal. Returns its JSON object. Raises PortalError (never with the key in it)."""
    try:
        r = httpx.request(method, base_url() + path, json=json, params=params, headers={"X-API-Key": api_key}, timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        log.warning("portal %s %s failed: %s", method, path, type(e).__name__)
        raise PortalError(f"The tourism portal could not be reached ({type(e).__name__}).") from None
    if r.status_code >= 400:
        log.warning("portal %s %s rejected: HTTP %s", method, path, r.status_code)
        raise PortalError(f"The tourism portal answered HTTP {r.status_code}: {HINTS.get(r.status_code, 'try again later')}.", r.status_code)
    try:
        out = r.json()
    except ValueError:
        out = {}
    return out if isinstance(out, dict) else {}


def send(payload: dict, api_key: str) -> dict:
    """POST the staffing request to the portal. Returns the portal's JSON (e.g. its job_id). Raises PortalError on any failure."""
    return _call("POST", PATH, api_key, json=payload)


def candidate_matches(skill: str, api_key: str, limit: int = 5) -> dict:
    """GET how many public job seekers fit `skill` in the hotel's own district (+ up to `limit` anonymised previews)."""
    return _call("GET", MATCHES_PATH, api_key, params={"skill": skill, "limit": limit})


def job_url(job_id: str) -> str:
    return f"{base_url()}/#/jobs/{job_id}"


def page_url(path: str) -> str:
    """A portal page from a hash path the portal returned (e.g. '#/business/hiring/candidates/C-1')."""
    return f"{base_url()}/{path.lstrip('/')}"
