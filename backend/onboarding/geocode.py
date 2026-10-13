"""Geocode the owner's location answer with LocationIQ Search (forward geocoding), stdlib only.

GET {url}?key=...&q=<location>&format=json&countrycodes=in&limit=1 -> a JSON array whose first
item has lat, lon (strings), display_name and importance (0-1, reported as the confidence).
The key comes ONLY from the environment (geocoding.api_key_env). No key, the flag off, no match
(HTTP 404 "Unable to geocode") or any failure -> None, silently: geocoding is a hint for the
owner and never blocks Confirm. Results are cached in-process for cache_days (same text, same
answer) and calls are at least min_interval_seconds apart. Tests inject a fake Geocoder.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from backend.onboarding.config import GeocodingConfig, OnboardingConfig
from backend.onboarding.schema import Geo

log = logging.getLogger("backend.onboarding.geocode")
SECONDS_PER_DAY = 86400
MAX_QUERY = 200


class Geocoder(Protocol):
    def geocode(self, query: str) -> Geo | None: ...


def _clean(query: str) -> str:
    return " ".join((query or "").split())[:MAX_QUERY]


@dataclass
class LocationIQGeocoder:
    settings: GeocodingConfig
    _cache: dict[str, tuple[float, Geo | None]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last: float = 0.0

    def available(self) -> bool:
        return self.settings.enabled and bool(os.environ.get(self.settings.api_key_env))

    def _fetch(self, q: str) -> list:
        key = os.environ.get(self.settings.api_key_env, "")
        params = {"key": key, "q": q, "format": "json", "countrycodes": self.settings.countrycodes,
                  "limit": 1}
        url = self.settings.url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with self._lock:
            wait = self._last + self.settings.min_interval_seconds - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(req, timeout=self.settings.timeout_seconds) as r:
                    return json.loads(r.read().decode("utf-8"))
            finally:
                self._last = time.monotonic()

    def geocode(self, query: str) -> Geo | None:
        q = _clean(query)
        if not q or not self.available():
            return None
        hit = self._cache.get(q.lower())
        if hit and hit[0] > time.time():
            return hit[1]
        geo = None
        try:
            rows = self._fetch(q)
            if isinstance(rows, list) and rows:
                top = rows[0]
                imp = float(top.get("importance") or 0.0)
                geo = Geo(lat=float(top["lat"]), lon=float(top["lon"]),
                          display_name=str(top.get("display_name") or q)[:300],
                          confidence=round(max(0.0, min(1.0, imp)), 3), query=q)
        except urllib.error.HTTPError as e:
            if e.code != 404:  # 404 = no match: cache "not found" like a result
                log.info("geocoding skipped: HTTP %s", e.code)
                return None
        except Exception as e:  # noqa: BLE001 - network / TLS / JSON: skip silently
            log.info("geocoding skipped: %s", type(e).__name__)
            return None
        self._cache[q.lower()] = (time.time() + self.settings.cache_days * SECONDS_PER_DAY, geo)
        return geo


class NoGeocoder:
    """Geocoding switched off (no geocoding section in the config)."""

    def geocode(self, query: str) -> Geo | None:
        return None


def default_geocoder(cfg: OnboardingConfig) -> Geocoder:
    return LocationIQGeocoder(cfg.geocoding) if cfg.geocoding else NoGeocoder()


def attach(draft, geocoder: Geocoder | None):  # noqa: ANN001, ANN201
    """The draft with location.geo set from the current location text (or cleared when nothing
    is found). Never raises: geocoding must never block an answer, an edit or Confirm."""
    loc = draft.location
    if geocoder is None or not loc.value:
        return draft
    if loc.geo is not None and loc.geo.query == _clean(loc.value):
        return draft
    try:
        geo = geocoder.geocode(loc.value)
    except Exception as e:  # noqa: BLE001
        log.info("geocoding skipped: %s", type(e).__name__)
        geo = None
    data = loc.model_dump()
    data["geo"] = geo.model_dump() if geo else None
    return draft.with_field("location", data)
