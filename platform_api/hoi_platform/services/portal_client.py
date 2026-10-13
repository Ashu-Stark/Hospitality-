"""Client for the Uttarakhand tourism portal (portal/): forwards a hotel's staffing request to the portal's staffing partners.

    POST {PORTAL_API_URL}/api/v1/ingest/staffing-request      header X-API-Key: <the property's portal business API key>

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
TIMEOUT_S = 10.0
log = logging.getLogger("hoi.portal_client")


class PortalError(Exception):
    """Sending failed. `message` is safe to store and show (never contains the key)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message, self.status = message, status


def base_url() -> str:
    return (os.getenv("PORTAL_API_URL") or DEFAULT_PORTAL_URL).strip().rstrip("/")


def send(payload: dict, api_key: str) -> dict:
    """POST the request to the portal. Returns the portal's JSON (e.g. its id). Raises PortalError on any failure."""
    url = base_url() + PATH
    try:
        r = httpx.post(url, json=payload, headers={"X-API-Key": api_key}, timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        log.warning("portal staffing request failed: %s", type(e).__name__)
        raise PortalError(f"The tourism portal could not be reached ({type(e).__name__}).") from None
    if r.status_code >= 400:
        log.warning("portal staffing request rejected: HTTP %s", r.status_code)
        hint = {
            401: "the portal API key was not accepted",
            403: "the portal API key was not accepted",
            404: "the portal does not offer staffing requests yet",
            422: "the portal rejected the request format",
        }
        raise PortalError(f"The tourism portal answered HTTP {r.status_code}: {hint.get(r.status_code, 'try again later')}.", r.status_code)
    try:
        out = r.json()
    except ValueError:
        out = {}
    return out if isinstance(out, dict) else {}
