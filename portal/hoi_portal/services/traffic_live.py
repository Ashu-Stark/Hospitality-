"""Live road data from pluggable providers: an OPTIONAL nowcast for the traffic prediction (services/traffic.py).

Providers are tried in order (env TRAFFIC_PROVIDERS, else traffic.yaml live.providers); the first that answers wins.
Results are cached per destination in `traffic_cache` (10 minutes; failures 3 minutes) because free tiers have daily
request limits. A provider that fails is skipped for `breaker_minutes` (circuit breaker). Every failure ends in "no
live data", never in an error: the prediction is always available on its own. Keys stay on the server, never logged.

* TomTom (implemented): Traffic Incidents v5 incidentDetails in a bounding box, plus (optional) Flow Segment Data v4 at
  the destination point. Several keys (TOMTOM_API_KEYS, comma list; TOMTOM_API_KEY is added) fail over ONLY when a key
  is invalid/revoked (401/403), the provider errors (5xx) or the call times out / cannot connect. HTTP 429 never
  rotates keys: moving to another key to get around a provider's per-account rate limit would break its terms. A 429
  opens the breaker for the whole provider instead (same policy as the Groq failover in platform_api ai.py).
* HERE (implemented from the Traffic API v7 OpenAPI reference, untested against the live service: no key yet):
  GET https://data.traffic.hereapi.com/v7/incidents?in=bbox:W,S,E,N&locationReferencing=none&apiKey=...
  Active only when HERE_API_KEY is set.
* Mapbox (documented stub, never active): Mapbox has no REST incidents endpoint; congestion comes from the
  mapbox-traffic-v1 vector tiles or from the Directions API `driving-traffic` profile (duration vs duration_typical
  between two points). Implementing it needs a corridor origin per destination, which we do not curate yet.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import Counter
from collections.abc import Callable
from datetime import timedelta

import httpx

from .. import config, mongo
from ..seed.destinations import BY_ID_DEST

log = logging.getLogger("hoi.portal.traffic_live")

# category key -> (singular, plural, road pill). Closed / lane closed -> closed; everything else -> caution. ASSUMED.
CATEGORY = {
    "road_closure": ("road closure", "road closures", "closed"),
    "lane_closure": ("lane closure", "lane closures", "closed"),
    "accident": ("accident", "accidents", "caution"),
    "jam": ("jam", "jams", "caution"),
    "roadworks": ("roadworks", "roadworks", "caution"),
    "flooding": ("flooding", "flooding", "caution"),
    "broken_down": ("broken-down vehicle", "broken-down vehicles", "caution"),
    "weather": ("weather warning", "weather warnings", "caution"),
    "hazard": ("road hazard", "road hazards", "caution"),
    "other": ("incident", "incidents", "caution"),
}
STATUS_ORDER = {"closed": 0, "caution": 1, "open": 2}
MAX_INCIDENTS = 8


class ProviderError(Exception):
    """This provider gave no usable answer (try the next provider)."""


class RateLimited(ProviderError):
    """HTTP 429: respect the limit (no key rotation); the provider is skipped for a while."""


class KeyFailed(Exception):
    """This key cannot be used now (401/403, 5xx, timeout, connection): try the next key."""


def _http_get(url: str, params: dict, timeout: float) -> httpx.Response:
    return httpx.get(url, params=params, timeout=timeout)


_HTTP: Callable = _http_get
_BREAKER: dict[str, float] = {}  # provider -> monotonic time until which it is skipped
_KEY_BAD: dict[str, float] = {}  # key fingerprint -> monotonic time until which it is skipped


def set_http(fn: Callable | None) -> None:
    """Inject a fake (tests): fn(url, params, timeout) -> object with status_code and json(). Resets breakers."""
    global _HTTP
    _HTTP = fn or _http_get
    reset_breakers()


def reset_breakers() -> None:
    _BREAKER.clear()
    _KEY_BAD.clear()


def _cfg() -> dict:
    from .traffic import CFG  # the model owns the config file

    return CFG["live"]


def _kid(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def bbox(dest: dict) -> tuple[float, float, float, float]:
    d = float(_cfg()["box_deg"])
    return round(dest["lon"] - d, 4), round(dest["lat"] - d, 4), round(dest["lon"] + d, 4), round(dest["lat"] + d, 4)


def incident(category: str, **kw) -> dict:
    sing, _, status = CATEGORY.get(category, CATEGORY["other"])
    return {"category": category, "label": sing, "status": status, **kw}


# ------------------------------------------------------------------ TomTom
TOMTOM_INCIDENTS = "https://api.tomtom.com/traffic/services/5/incidentDetails"
TOMTOM_FLOW = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
TOMTOM_FIELDS = (
    "{incidents{type,properties{id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},"
    "startTime,endTime,from,to,length,delay,roadNumbers,timeValidity,lastReportTime}}}"
)
TOMTOM_ICON = {
    1: "accident",
    2: "weather",
    3: "hazard",
    4: "weather",
    5: "weather",
    6: "jam",
    7: "lane_closure",
    8: "road_closure",
    9: "roadworks",
    10: "weather",
    11: "flooding",
    14: "broken_down",
}
MAGNITUDE = {0: "unknown", 1: "minor", 2: "moderate", 3: "major", 4: "indefinite"}


def _tomtom_incident(raw: dict) -> dict:
    p = (raw or {}).get("properties") or {}
    try:
        icon = int(p.get("iconCategory") or 0)
    except (TypeError, ValueError):
        icon = 0
    cat = TOMTOM_ICON.get(icon, "other")
    events = [str(e.get("description") or "").strip() for e in p.get("events") or [] if isinstance(e, dict)]
    delay, mag = p.get("delay"), p.get("magnitudeOfDelay")
    return incident(
        cat,
        road=", ".join(str(r) for r in (p.get("roadNumbers") or [])[:3]) or None,
        **{"from": str(p["from"])[:80] if p.get("from") else None},
        to=str(p["to"])[:80] if p.get("to") else None,
        description="; ".join(e for e in events if e)[:200] or CATEGORY[cat][0].capitalize(),
        delay_min=round(delay / 60) if isinstance(delay, (int, float)) and delay > 0 else None,
        magnitude=MAGNITUDE.get(mag) if isinstance(mag, int) else None,
        start_time=p.get("startTime"),
        end_time=p.get("endTime"),
        last_update=p.get("lastReportTime") or p.get("startTime"),
    )


class TomTom:
    name, source, credit = "tomtom", "TomTom", "Traffic data © TomTom"
    implemented = True

    def available(self) -> bool:
        return bool(config.settings.tomtom_keys)

    def _call(self, url: str, params: dict) -> dict:
        """One GET with key failover (see the module docstring for the policy)."""
        now = time.monotonic()
        keys = [k for k in config.settings.tomtom_keys if _KEY_BAD.get(_kid(k), 0.0) <= now]
        if not keys:
            raise ProviderError("all TomTom keys failed recently")
        timeout = float(_cfg()["timeout_seconds"])
        last = ""
        for key in keys:
            try:
                r = _HTTP(url, {**params, "key": key}, timeout)
            except Exception as e:  # noqa: BLE001 - timeout, connection, TLS inspection: this key/attempt failed
                last = type(e).__name__
                _KEY_BAD[_kid(key)] = now + 60 * float(_cfg()["breaker_minutes"])
                continue
            if r.status_code == 429:
                raise RateLimited("HTTP 429")  # never rotate keys on a rate limit
            if r.status_code in (401, 403) or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                _KEY_BAD[_kid(key)] = now + 60 * float(_cfg()["breaker_minutes"])
                continue
            if r.status_code != 200:
                raise ProviderError(f"HTTP {r.status_code}")
            try:
                return r.json()
            except ValueError as e:
                raise ProviderError("bad JSON") from e
        raise ProviderError(f"all TomTom keys failed ({last})")

    def fetch(self, dest: dict) -> dict:
        w, s, e, n = bbox(dest)
        body = self._call(
            TOMTOM_INCIDENTS,
            {"bbox": f"{w},{s},{e},{n}", "fields": TOMTOM_FIELDS, "language": "en-GB", "timeValidityFilter": "present"},
        )
        incidents = [_tomtom_incident(i) for i in body.get("incidents") or [] if isinstance(i, dict)]
        flow = None
        if _cfg().get("tomtom_flow"):
            try:
                fj = self._call(TOMTOM_FLOW, {"point": f"{dest['lat']},{dest['lon']}", "unit": "KMPH"}).get("flowSegmentData") or {}
                cur, free = fj.get("currentSpeed"), fj.get("freeFlowSpeed")
                if isinstance(cur, (int, float)) and isinstance(free, (int, float)) and free > 0:
                    flow = {
                        "current_kmh": cur,
                        "free_flow_kmh": free,
                        "ratio": round(cur / free, 3),
                        "road_closed": bool(fj.get("roadClosure")),
                    }
            except RateLimited:
                raise
            except ProviderError as e2:  # flow is a bonus: incidents alone are still a good answer
                log.info("TomTom flow unavailable for %s: %s", dest["id"], e2)
        return {"incidents": incidents, "flow": flow}


# ------------------------------------------------------------------ HERE
HERE_INCIDENTS = "https://data.traffic.hereapi.com/v7/incidents"
HERE_TYPE = {
    "roadClosure": "road_closure",
    "laneRestriction": "lane_closure",
    "accident": "accident",
    "congestion": "jam",
    "construction": "roadworks",
    "disabledVehicle": "broken_down",
    "weather": "weather",
    "roadHazard": "hazard",
}


def _here_incident(item: dict) -> dict:
    d = (item or {}).get("incidentDetails") or {}
    cat = "road_closure" if d.get("roadClosed") else HERE_TYPE.get(str(d.get("type") or ""), "other")
    desc = (d.get("description") or {}).get("value") or (d.get("summary") or {}).get("value") or CATEGORY[cat][0].capitalize()
    return incident(
        cat,
        road=None,
        **{"from": None},
        to=None,
        description=str(desc)[:200],
        delay_min=None,
        magnitude=d.get("criticality"),
        start_time=d.get("startTime"),
        end_time=d.get("endTime"),
        last_update=d.get("startTime"),
    )


class Here:
    name, source, credit = "here", "HERE", "Traffic data © HERE"
    implemented = True

    def available(self) -> bool:
        return bool(config.settings.here_key)

    def fetch(self, dest: dict) -> dict:
        w, s, e, n = bbox(dest)
        params = {"in": f"bbox:{w},{s},{e},{n}", "locationReferencing": "none", "apiKey": config.settings.here_key}
        try:
            r = _HTTP(HERE_INCIDENTS, params, float(_cfg()["timeout_seconds"]))
        except Exception as ex:  # noqa: BLE001
            raise ProviderError(type(ex).__name__) from ex
        if r.status_code == 429:
            raise RateLimited("HTTP 429")
        if r.status_code != 200:
            raise ProviderError(f"HTTP {r.status_code}")
        try:
            body = r.json()
        except ValueError as ex:
            raise ProviderError("bad JSON") from ex
        return {"incidents": [_here_incident(i) for i in body.get("results") or [] if isinstance(i, dict)], "flow": None}


class Mapbox:
    """Documented stub (see the module docstring); never active."""

    name, source, credit = "mapbox", "Mapbox", "Traffic data © Mapbox"
    implemented = False

    def available(self) -> bool:
        return False

    def fetch(self, dest: dict) -> dict:  # pragma: no cover - never called while available() is False
        raise ProviderError("Mapbox adapter is a stub")


PROVIDERS = {p.name: p for p in (TomTom(), Here(), Mapbox())}


def order() -> list[str]:
    names = config.settings.traffic_providers or tuple(_cfg()["providers"])
    return [n for n in names if n in PROVIDERS]


def provider_status() -> list[dict]:
    now = time.monotonic()
    out = []
    for n in order():
        p = PROVIDERS[n]
        state = (
            "stub"
            if not p.implemented
            else "not configured"
            if not p.available()
            else "paused after a failure"
            if _BREAKER.get(n, 0.0) > now
            else "ready"
        )
        out.append({"name": p.source, "state": state})
    return out


# ------------------------------------------------------------------ shaping + cache
def summary_text(items: list[dict]) -> str:
    c = Counter(i["category"] for i in items)
    parts = []
    for cat, n in sorted(c.items(), key=lambda kv: (STATUS_ORDER[CATEGORY[kv[0]][2]], -kv[1])):
        sing, plur, _ = CATEGORY[cat]
        parts.append(f"{n} {sing if n == 1 else plur}")
    return ", ".join(parts)


def shape(dest: dict, doc: dict) -> dict | None:
    """The live block for the UI (None when nothing was reported)."""
    items = sorted(doc.get("incidents") or [], key=lambda i: (STATUS_ORDER[i["status"]], -(i.get("delay_min") or 0)))
    flow = doc.get("flow")
    if not items and not flow:
        return None
    p = PROVIDERS.get(doc.get("provider"), PROVIDERS["tomtom"])
    status = min((i["status"] for i in items), key=lambda s: STATUS_ORDER[s], default="open")
    if flow and flow.get("road_closed"):
        status = "closed"
    return {
        "source": p.source,
        "status": status,
        "summary": summary_text(items) if items else "No incidents reported",
        "total": len(items),
        "incidents": items[:MAX_INCIDENTS],
        "flow": flow,
        "area": f"within about 15 km of {dest['name']}",
        "fetched_at": mongo.iso(doc["fetched_at"]),
        "credit": p.credit,
        "note": "Live incidents reported to the provider; often incomplete on hill roads. Check locally before setting out.",
    }


def get(dest_id: str) -> tuple[dict | None, bool]:
    """(raw live document or None, fresh) where fresh = fetched from a provider in this call (not the cache)."""
    dest = BY_ID_DEST.get(dest_id)
    names = [n for n in order() if PROVIDERS[n].available()]
    if not dest or not names:
        return None, False
    cfg = _cfg()
    try:
        col = mongo.db().traffic_cache
        cached = col.find_one({"destination_id": dest_id})
    except Exception:  # noqa: BLE001
        return None, False
    now = mongo.now()
    if cached and mongo.aware(cached["expires_at"]) > now:
        return (cached if cached.get("ok") else None), False
    mono = time.monotonic()
    for n in names:
        if _BREAKER.get(n, 0.0) > mono:
            continue
        p = PROVIDERS[n]
        try:
            data = p.fetch(dest)
        except Exception as e:  # noqa: BLE001 - RateLimited, ProviderError, anything: skip this provider for a while
            _BREAKER[n] = mono + 60 * float(cfg["breaker_minutes"])
            log.warning("live traffic: %s unavailable for %s (%s)", p.source, dest_id, type(e).__name__ if not str(e) else str(e)[:80])
            continue
        doc = {
            "destination_id": dest_id,
            "ok": True,
            "provider": n,
            "incidents": data["incidents"],
            "flow": data.get("flow"),
            "fetched_at": now,
            "expires_at": now + timedelta(minutes=float(cfg["cache_minutes"])),
        }
        col.update_one({"destination_id": dest_id}, {"$set": doc}, upsert=True)
        return doc, True
    col.update_one(
        {"destination_id": dest_id},
        {
            "$set": {
                "destination_id": dest_id,
                "ok": False,
                "fetched_at": now,
                "expires_at": now + timedelta(minutes=float(cfg["fail_cache_minutes"])),
            }
        },
        upsert=True,
    )
    return None, False
