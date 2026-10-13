"""LocationIQ (locationiq.com, OpenStreetMap data): a static map image for the Map view and nearby places per destination.

The key (LOCATIONIQ_API_KEY) stays on the server: the browser only ever sees our own URLs (the CSP allows images from
'self' only). Results are cached in MongoDB for 7 days: `map_tiles` (PNG bytes per filter combination) and
`places_cache` (per destination and category). Failures are cached for FAIL_TTL_MINUTES so a down upstream is not
hammered. Calls are sequential and at least MIN_INTERVAL_S apart (free tier: about 2 requests per second).
Tests replace the HTTP function with `set_http()` and never call the network.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import timedelta

import httpx

from .. import config, mongo
from ..errors import Invalid, NotFound, Unavailable
from ..seed.destinations import BY_ID_DEST, DESTINATIONS
from ..seed.districts import BY_ID as DISTRICTS
from ..seed.experiences import BY_ID_EXP, CIRCUITS

log = logging.getLogger("hoi.portal.locationiq")
NEARBY_URL = "https://us1.locationiq.com/v1/nearby"
STATIC_URL = "https://maps.locationiq.com/v3/staticmap"
ATTRIBUTION = "© LocationIQ · © OpenStreetMap contributors"
TIMEOUT_S = 8.0
MIN_INTERVAL_S = 0.5
FAIL_TTL_MINUTES = 10
MAP_SIZE = "960x720"
MAP_SINGLE_ZOOM = 11  # one marker: LocationIQ would otherwise zoom to street level
MARKER_ICON = "small-red-cutout"
PLACES_PER_CATEGORY = 5
PLACES_BUDGET_S = 6.0  # one request fetches uncached categories for at most this long; the rest come on the next request
DISTANCE_NOTE = "Straight-line distance from the destination's approximate centre, not road distance. Places from OpenStreetMap; verify before relying on them."

# key, label, LocationIQ tag (documented single-word tags or OSM class:type), radius in metres
CATEGORIES: list[tuple[str, str, str, int]] = [
    ("hospital", "Hospitals", "hospital", 25000),
    ("pharmacy", "Pharmacies", "pharmacy", 10000),
    ("atm", "ATMs", "atm", 10000),
    ("fuel", "Fuel", "fuel", 25000),
    ("police", "Police", "amenity:police", 15000),
    ("viewpoint", "Viewpoints", "tourism:viewpoint", 15000),
    ("place_of_worship", "Places of worship", "place_of_worship", 5000),
]
BY_CAT = {c[0]: c for c in CATEGORIES}

_LOCK = threading.Lock()
_LAST = [0.0]
STATS = {"requests": 0}


def _http_get(url: str, params: list | dict) -> httpx.Response:
    return httpx.get(url, params=params, timeout=TIMEOUT_S)


_HTTP: Callable = _http_get


def set_http(fn: Callable | None) -> None:
    """Inject a fake HTTP GET (tests): fn(url, params) -> object with status_code, headers, content, json(). None restores."""
    global _HTTP
    _HTTP = fn or _http_get
    _LAST[0] = 0.0


def _key() -> str:
    s = config.settings
    return s.locationiq_key if s.locationiq_enabled else ""


def available() -> bool:
    return bool(_key())


def _get(url: str, params: list) -> httpx.Response:
    """Sequential, rate-limited GET; the key is added here and never logged."""
    with _LOCK:
        wait = _LAST[0] + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            STATS["requests"] += 1
            return _HTTP(url, [("key", _key()), *params])
        finally:
            _LAST[0] = time.monotonic()


def _ttl(ok: bool):
    now = mongo.now()
    return now, now + (timedelta(days=config.settings.external_cache_days) if ok else timedelta(minutes=FAIL_TTL_MINUTES))


# ------------------------------------------------------------------ static map
def map_info() -> dict:
    return {"available": available(), "attribution": ATTRIBUTION}


def filtered(circuit: str | None, theme: str | None, district: str | None) -> list[dict]:
    if circuit and circuit not in {c["id"] for c in CIRCUITS}:
        raise Invalid("Unknown circuit.")
    if theme and theme not in BY_ID_EXP:
        raise Invalid("Unknown experience.")
    if district and district not in DISTRICTS:
        raise Invalid("Unknown district.")
    in_circuit = next((set(c["destination_ids"]) for c in CIRCUITS if c["id"] == circuit), None)
    return [
        d
        for d in DESTINATIONS
        if (in_circuit is None or d["id"] in in_circuit)
        and (not district or d["district"] == district)
        and (not theme or theme in d.get("themes", []))
    ]


def static_map(circuit: str | None = None, theme: str | None = None, district: str | None = None) -> bytes:
    """PNG bytes for the filtered destinations (markers, automatic zoom). Raises Unavailable when there is no image."""
    pts = filtered(circuit, theme, district)
    if not pts:
        raise NotFound("No destinations match these filters.")
    if not available():
        raise Unavailable("Map image unavailable.")
    key = f"c={circuit or ''}|t={theme or ''}|d={district or ''}|s={MAP_SIZE}"
    col = mongo.db().map_tiles
    cached = col.find_one({"key": key})
    now = mongo.now()
    if cached and mongo.aware(cached["expires_at"]) > now:
        if cached.get("ok"):
            return bytes(cached["png"])
        raise Unavailable("Map image unavailable right now.")
    params = [("size", MAP_SIZE), ("format", "png"), ("markers", f"icon:{MARKER_ICON}|" + "|".join(f"{p['lat']},{p['lon']}" for p in pts))]
    if len(pts) == 1:
        params += [("center", f"{pts[0]['lat']},{pts[0]['lon']}"), ("zoom", str(MAP_SINGLE_ZOOM))]
    png = None
    try:
        r = _get(STATIC_URL, params)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/png") and r.content[:8] == b"\x89PNG\r\n\x1a\n":
            png = bytes(r.content)
        else:
            log.warning("static map failed: HTTP %s", r.status_code)
    except Exception as e:  # noqa: BLE001
        log.warning("static map failed: %s", type(e).__name__)
    if png is None:
        if cached and cached.get("ok"):  # serve the last good image and retry later
            col.update_one({"key": key}, {"$set": {"expires_at": now + timedelta(minutes=FAIL_TTL_MINUTES)}})
            return bytes(cached["png"])
        fetched, exp = _ttl(False)
        col.update_one(
            {"key": key}, {"$set": {"key": key, "ok": False, "fetched_at": fetched, "expires_at": exp}, "$unset": {"png": ""}}, upsert=True
        )
        raise Unavailable("Map image unavailable right now.")
    fetched, exp = _ttl(True)
    col.update_one(
        {"key": key},
        {"$set": {"key": key, "ok": True, "png": png, "points": len(pts), "fetched_at": fetched, "expires_at": exp}},
        upsert=True,
    )
    return png


# ------------------------------------------------------------------ nearby places
def _parse_places(body, dest: dict) -> list[dict]:
    from .plan import haversine_km  # local import: plan imports this module

    items, seen = [], set()
    for x in body if isinstance(body, list) else []:
        name = str(x.get("name") or "").strip()
        try:
            lat, lon = float(x["lat"]), float(x["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        km = haversine_km(dest, {"lat": lat, "lon": lon})
        items.append(
            {
                "name": name[:120],
                "kind": str(x.get("type") or "")[:40],
                "distance_km": round(km, 1),
                "lat": round(lat, 5),
                "lon": round(lon, 5),
            }
        )
    items.sort(key=lambda i: i["distance_km"])
    return items[:PLACES_PER_CATEGORY]


def _fetch_category(dest: dict, cat: tuple) -> dict:
    key, _, tag, radius = cat
    params = [("lat", str(dest["lat"])), ("lon", str(dest["lon"])), ("tag", tag), ("radius", str(radius))]
    params += [("limit", str(PLACES_PER_CATEGORY * 3)), ("dedupe", "1"), ("format", "json")]
    try:
        r = _get(NEARBY_URL, params)
    except Exception as e:  # noqa: BLE001
        log.warning("nearby %s/%s failed: %s", dest["id"], key, type(e).__name__)
        return {"ok": False}
    if r.status_code == 404:  # LocationIQ answers 404 "Unable to geocode" when nothing is within the radius
        return {"ok": True, "items": []}
    if r.status_code != 200:
        log.warning("nearby %s/%s failed: HTTP %s", dest["id"], key, r.status_code)
        return {"ok": False}
    try:
        return {"ok": True, "items": _parse_places(r.json(), dest)}
    except ValueError:
        return {"ok": False}


def places(dest_id: str, category: str | None = None) -> dict:
    dest = BY_ID_DEST.get(dest_id)
    if not dest:
        raise NotFound("Destination not found.")
    if category and category not in BY_CAT:
        raise Invalid("Unknown category. Use one of: " + ", ".join(BY_CAT))
    cats = [BY_CAT[category]] if category else CATEGORIES
    base = {
        "destination_id": dest_id,
        "source": "LocationIQ (OpenStreetMap data)",
        "attribution": ATTRIBUTION,
        "distance_note": DISTANCE_NOTE,
        "categories": [{"key": c[0], "label": c[1], "radius_km": c[3] / 1000} for c in cats],
    }
    if not available():
        return {**base, "available": False, "groups": [], "pending": []}
    col = mongo.db().places_cache
    t0 = time.monotonic()
    groups, pending, fetched_at, fetched = [], [], None, 0
    for cat in cats:
        doc = col.find_one({"destination_id": dest_id, "category": cat[0]})
        now = mongo.now()
        if not (doc and mongo.aware(doc["expires_at"]) > now):
            if fetched and time.monotonic() - t0 > PLACES_BUDGET_S:
                pending.append(cat[0])
                doc = doc if doc and doc.get("ok") else None  # stale but good data is still worth showing
            else:
                res = _fetch_category(dest, cat)
                fetched += 1
                if res["ok"] or not (doc and doc.get("ok")):
                    f, exp = _ttl(res["ok"])
                    new = {
                        "destination_id": dest_id,
                        "category": cat[0],
                        "ok": res["ok"],
                        "items": res.get("items", []),
                        "fetched_at": f,
                        "expires_at": exp,
                    }
                    col.update_one({"destination_id": dest_id, "category": cat[0]}, {"$set": new}, upsert=True)
                    doc = new
                else:  # keep the last good result, retry later
                    col.update_one({"_id": doc["_id"]}, {"$set": {"expires_at": now + timedelta(minutes=FAIL_TTL_MINUTES)}})
        if doc and doc.get("ok") and doc.get("items"):
            groups.append({"category": cat[0], "label": cat[1], "radius_km": cat[3] / 1000, "items": doc["items"]})
            f = mongo.aware(doc["fetched_at"])
            fetched_at = f if fetched_at is None or f < fetched_at else fetched_at
    return {**base, "available": bool(groups), "groups": groups, "pending": pending, "fetched_at": mongo.iso(fetched_at)}
