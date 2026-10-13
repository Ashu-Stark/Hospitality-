"""Live weather from Open-Meteo (no key), cached per destination in `weather_cache` for 30 minutes.

On any failure the result is `{"available": false, "reason": ...}` (a failure is cached for FAIL_TTL so a
down upstream is not hammered). Tests replace the fetcher with `set_fetcher()` and never call the network.

Plain-language warnings use ASSUMED thresholds (not official warning criteria):
    heavy rain: a day with precipitation_sum >= HEAVY_RAIN_MM, or probability >= 80 % with >= RAIN_LIKELY_MM
    snow:       a day with snowfall_sum >= SNOW_CM
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

import httpx

from .. import config, mongo
from ..errors import NotFound
from ..seed.destinations import BY_ID_DEST

log = logging.getLogger("hoi.portal.weather")
URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 6.0
FAIL_TTL_MINUTES = 3
HEAVY_RAIN_MM = 50.0  # ASSUMED
RAIN_LIKELY_MM = 20.0  # ASSUMED
SNOW_CM = 5.0  # ASSUMED
SOURCE = "Open-Meteo (open-meteo.com), forecast model data"

# WMO weather interpretation codes (as documented by Open-Meteo).
WMO = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def http_fetch(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,snowfall_sum,weather_code",
        "hourly": "precipitation,snowfall",  # used by the traffic prediction (rain / snow slow-down)
        "timezone": "Asia/Kolkata",
        "forecast_days": 7,
    }
    r = httpx.get(URL, params=params, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()


_FETCHER: Callable[[float, float], dict] = http_fetch


def set_fetcher(fn: Callable[[float, float], dict] | None) -> None:
    """Inject a fetcher (tests). None restores the real HTTP fetcher."""
    global _FETCHER
    _FETCHER = fn or http_fetch


def _num(v):
    return None if v is None else round(float(v), 1)


def parse(raw: dict) -> dict:
    cur = raw.get("current") or {}
    daily = raw.get("daily") or {}
    days = []
    for i, d in enumerate(daily.get("time", [])):

        def col(name, i=i):
            vals = daily.get(name) or []
            return vals[i] if i < len(vals) else None

        code = col("weather_code")
        days.append(
            {
                "date": d,
                "max_c": _num(col("temperature_2m_max")),
                "min_c": _num(col("temperature_2m_min")),
                "precip_probability": col("precipitation_probability_max"),
                "precip_mm": _num(col("precipitation_sum")),
                "snow_cm": _num(col("snowfall_sum")),
                "weather_code": code,
                "summary": WMO.get(code, "Unknown") if code is not None else None,
            }
        )
    code = cur.get("weather_code")
    if cur.get("temperature_2m") is None and not days:
        raise ValueError("empty forecast")
    hourly = raw.get("hourly") or {}
    return {
        "hourly": {
            "time": list(hourly.get("time") or []),
            "precip_mm": [_num(v) for v in hourly.get("precipitation") or []],
            "snow_cm": [_num(v) for v in hourly.get("snowfall") or []],
        },
        "current": {
            "temperature_c": _num(cur.get("temperature_2m")),
            "weather_code": code,
            "summary": WMO.get(code, "Unknown") if code is not None else None,
            "wind_kmh": _num(cur.get("wind_speed_10m")),
            "time": cur.get("time"),
        },
        "daily": days,
    }


def warnings(days: list[dict]) -> list[dict]:
    out = []
    for d in days:
        mm, prob, snow = d.get("precip_mm") or 0, d.get("precip_probability") or 0, d.get("snow_cm") or 0
        if mm >= HEAVY_RAIN_MM or (prob >= 80 and mm >= RAIN_LIKELY_MM):
            out.append(
                {
                    "date": d["date"],
                    "kind": "heavy_rain",
                    "message": f"Heavy rain is forecast on {d['date']} ({mm:g} mm). Hill roads can be blocked by landslides; check road advisories before setting out.",
                }
            )
        if snow >= SNOW_CM:
            out.append(
                {
                    "date": d["date"],
                    "kind": "snow",
                    "message": f"Snowfall is forecast on {d['date']} ({snow:g} cm). Roads to higher places may close; carry warm layers and check advisories.",
                }
            )
    return out


def for_destination(dest_id: str) -> dict:
    dest = BY_ID_DEST.get(dest_id)
    if not dest:
        raise NotFound("Destination not found.")
    s = config.settings
    if not s.weather_enabled:
        return {"available": False, "reason": "Live weather is switched off on this server."}
    col = mongo.db().weather_cache
    cached = col.find_one({"destination_id": dest_id})
    now = mongo.now()
    if cached and mongo.aware(cached["expires_at"]) > now:
        return _shape(cached, cached_hit=True)
    try:
        data = parse(_FETCHER(dest["lat"], dest["lon"]))
        doc = {"ok": True, "stale": False, "data": data, "fetched_at": now, "expires_at": now + timedelta(minutes=s.weather_ttl_minutes)}
    except Exception as e:  # noqa: BLE001 - network, HTTP, JSON or shape errors all mean "unavailable"
        log.warning("weather unavailable for %s: %s", dest_id, type(e).__name__)
        if cached and cached.get("ok"):  # serve the last good forecast, marked stale, and back off before retrying
            col.update_one({"destination_id": dest_id}, {"$set": {"stale": True, "expires_at": now + timedelta(minutes=FAIL_TTL_MINUTES)}})
            return _shape({**cached, "stale": True}, cached_hit=True)
        doc = {
            "ok": False,
            "reason": "Live weather is unavailable right now. Try again later.",
            "fetched_at": now,
            "expires_at": now + timedelta(minutes=FAIL_TTL_MINUTES),
        }
    col.update_one({"destination_id": dest_id}, {"$set": doc}, upsert=True)
    return _shape(doc, cached_hit=False)


def _shape(doc: dict, cached_hit: bool) -> dict:
    if not doc.get("ok"):
        return {"available": False, "reason": doc.get("reason", "Live weather is unavailable right now.")}
    data = doc["data"]
    return {
        "available": True,
        "current": data["current"],
        "daily": data["daily"],
        "warnings": warnings(data["daily"]),
        "thresholds": {
            "heavy_rain_mm": HEAVY_RAIN_MM,
            "rain_likely_mm": RAIN_LIKELY_MM,
            "snow_cm": SNOW_CM,
            "note": "ASSUMED thresholds, not official warning criteria.",
        },
        "fetched_at": mongo.iso(doc["fetched_at"]),
        "cached": cached_hit,
        "stale": bool(doc.get("stale")),
        "source": SOURCE,
        "timezone": "Asia/Kolkata",
    }


def cached_summary(dest_id: str) -> dict | None:
    """Compact current weather from the cache only (never calls Open-Meteo). None when nothing is cached."""
    doc = mongo.db().weather_cache.find_one({"destination_id": dest_id})
    if not doc:
        return None
    if not doc.get("ok"):
        return {"available": False}
    cur = doc["data"]["current"]
    warn = warnings(doc["data"]["daily"])
    return {
        "available": True,
        "temperature_c": cur.get("temperature_c"),
        "summary": cur.get("summary"),
        "warning": warn[0] if warn else None,
        "fetched_at": mongo.iso(doc["fetched_at"]),
        "stale": bool(doc.get("stale")) or mongo.aware(doc["expires_at"]) <= mongo.now(),
    }
