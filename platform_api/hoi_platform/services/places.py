"""Places to visit for the guest concierge: the hotel's own `nearby` list first, then RETRIEVAL from the tourism portal.

Nothing is trained. When a hotel's hand-typed list is short (fewer than MIN_PLACES), or the guest asks for quiet /
lesser-known spots and the list has too few, places are looked up from the Uttarakhand tourism portal's public API
(portal/, base URL from services/portal_client.py) and matched to the hotel by its town / district (property region,
profile `location`) or its coordinates. So a new hotel in Nainital, or anywhere in Uttarakhand the portal covers, gets
places with no extra setup:

    GET {portal}/api/v1/meta                                          destination names + districts (find the hotel's town)
    GET {portal}/api/v1/destinations?district=...                     curated destinations (lat/lon, crowd estimate)
    GET {portal}/api/v1/destinations/{id}/nearby                      other destinations by straight-line distance
    GET {portal}/api/v1/destinations/{id}/places?category=viewpoint   viewpoints from LocationIQ / OpenStreetMap (the
                                                                      portal holds the LocationIQ key; we never need it)
    GET {portal}/api/v1/local-experiences?district=...                community-hosted local experiences (SAMPLE data)

Answers are cached in MongoDB (`places_cache`): fresh for CACHE_HOURS, failures for FAIL_MINUTES, and the last good
answer is used when the portal is down (offline -> the hotel's own list only). The portal has no "lesser-known" field,
so "quieter" (offbeat) uses these signals, in this order (OFFBEAT_SIGNALS):
  1. the hotel marked the place `offbeat: true` (or its tip says quiet / less crowded),
  2. a community-hosted local experience of a small-group type (village walk, birding, farm day, ...),
  3. a portal destination whose crowd estimate for today is low or moderate AND lower than the hotel's own town, and which
     is not one of the best-known destinations (WELL_KNOWN, ASSUMED) or a plain town / city.
Tests replace the HTTP function with `set_http()` and never call the network. No guest or staff data is ever sent.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

import httpx

from .. import config, mongo
from . import portal_client, tenants

log = logging.getLogger("hoi.platform.places")
API = "/api/v1"
TIMEOUT_S = 5.0
SLOW_TIMEOUT_S = 9.0  # the full destination list (only needed for a hotel known by coordinates alone) takes ~6 s
BUDGET_S = 10.0  # one guest question waits at most this long for the portal; the rest is served from cache next time
FAIL_MINUTES = 10
MIN_PLACES = 4  # fewer hand-typed places than this -> fill from the portal
MIN_OFFBEAT = 2
MAX_CARDS = 6
MAX_KM = 60  # portal destinations farther than this (straight line) are not "nearby"
ANCHOR_KM = 40  # hotel coordinates must be this close to a portal destination to use it as the hotel's town
MAPS = "https://www.google.com/maps/search/?api=1&query="

# Small-group, community-hosted experience types: off the usual tourist trail by nature (signal 2).
OFFBEAT_EXPERIENCES = {"village_walk", "nature_walk", "birding", "farm_stay", "artisan_workshop", "home_meal", "folk_music"}
QUIET_BANDS = ("low", "moderate")
# ASSUMED: the best-known destinations in the portal's list, and plain towns / cities: never offered as "hidden" spots, even
# on a quiet day (a low crowd estimate does not make Mussoorie or Dehradun lesser-known).
WELL_KNOWN = {
    "mussoorie",
    "nainital",
    "rishikesh",
    "haridwar",
    "dehradun",
    "kedarnath",
    "badrinath",
    "gangotri",
    "yamunotri",
    "jim-corbett-ramnagar",
    "auli",
    "valley-of-flowers",
}
NOT_OFFBEAT_TAGS = {"city", "town", "Char Dham"}
QUIET_TIP_WORDS = ("quiet", "less crowded", "fewer people", "offbeat", "hidden", "peaceful", "secluded", "शांत", "कम भीड़")
OFFBEAT_SIGNALS = {
    "hotel": "Marked as a quiet spot by the hotel",
    "experience": "Small group with a local host",
    "crowd": "Fewer visitors expected today (portal estimate)",
}
OFFBEAT_SIGNALS_HI = {
    "hotel": "होटल के अनुसार शांत जगह",
    "experience": "छोटा ग्रुप, स्थानीय मेज़बान",
    "crowd": "आज कम भीड़ का अनुमान",
}

# Picture per kind (same-origin SVGs in static/shared/places; the strict CSP allows images from 'self' only).
IMG = "/shared/places/{}.svg"
DEST_PHOTOS = {"mussoorie": "/shared/photos/mussoorie_sm.jpg", "dhanaulti": "/shared/photos/dhanaulti_sm.jpg"}
NAME_KINDS = [
    ("lake", ("lake", "tal", "taal", "jheel", "झील", "ताल")),
    ("temple", ("temple", "mandir", "devi", "math", "ashram", "gurudwara", "church", "मंदिर", "धाम", "dham")),
    ("forest", ("garden", "park", "forest", "zoo", "sanctuary", "reserve", "eco")),
    ("viewpoint", ("point", "peak", "hill", "top", "tibba", "view", "seat", "end", "ropeway")),
    ("waterfall", ("falls", "fall", "waterfall", "jharna", "झरना")),
    ("town", ("road", "mall", "market", "bazaar", "bazar", "street", "town")),
]
DEST_KINDS = [
    ("lake", "lake"),
    ("pilgrimage", "temple"),
    ("Char Dham", "temple"),
    ("wildlife", "forest"),
    ("national park", "forest"),
    ("snow", "mountain"),
    ("trek", "mountain"),
    ("hill town", "town"),
]
EXP_KINDS = {
    "birding": "forest",
    "nature_walk": "forest",
    "village_walk": "village",
    "farm_stay": "village",
    "home_meal": "food",
    "artisan_workshop": "village",
    "folk_music": "village",
    "heritage_walk": "temple",
}
SAFE_IMG = re.compile(r"^/(?!/)[\w\-./]+\.(svg|png|jpe?g|webp)$", re.I)


# ------------------------------------------------------------------ HTTP + cache
def _http_get(url: str, params: dict, timeout: float = TIMEOUT_S) -> httpx.Response:
    return httpx.get(url, params=params, timeout=timeout)


_HTTP: Callable = _http_get
STATS = {"requests": 0}


def set_http(fn: Callable | None) -> None:
    """Inject a fake HTTP GET (tests): fn(url, params, timeout=...) -> object with status_code and json(). None = real."""
    global _HTTP
    _HTTP = fn or _http_get


def _fetch(path: str, params: dict, shape: Callable[[dict], object], timeout: float) -> object | None:
    """One portal GET, shaped. None on any failure (offline, timeout, HTTP error, bad JSON). Runs in a worker thread."""
    try:
        STATS["requests"] += 1
        r = _HTTP(portal_client.base_url() + API + path, params, timeout=timeout)
        if r.status_code == 200:
            return shape(r.json())
        log.warning("portal places %s failed: HTTP %s", path, r.status_code)
    except Exception as e:  # noqa: BLE001 - the hotel's own list still answers
        log.warning("portal places %s failed: %s", path, type(e).__name__)
    return None


def _get_many(reqs: list[tuple[str, dict, Callable[[dict], object]]], deadline: float, timeout: float = TIMEOUT_S) -> list:
    """Cached GETs of portal paths, the missing ones fetched in parallel. Per request: the shaped answer, the last good
    one when the portal fails (stale), or None. MongoDB is only touched from this (the calling) thread."""
    col = mongo.col("places_cache")
    now = time.time()
    keys = [p + ("?" + urlencode(sorted(q.items())) if q else "") for p, q, _ in reqs]
    docs = [col.find_one({"key": k}) for k in keys]
    out: list = [None] * len(reqs)
    todo = []
    for i, doc in enumerate(docs):
        if doc and doc.get("expires_ts", 0) > now:
            out[i] = doc.get("data") if doc.get("ok") else None
        else:
            out[i] = doc.get("data") if doc and doc.get("ok") else None  # stale but good, until a fresh answer comes
            todo.append(i)
    left = deadline - time.monotonic()
    if not todo or not config.settings.places_lookup or left <= 0.5:
        return out
    t = min(timeout, left)
    with ThreadPoolExecutor(max_workers=min(4, len(todo))) as pool:
        fresh = list(pool.map(lambda i: _fetch(reqs[i][0], reqs[i][1], reqs[i][2], t), todo))
    retry = time.time() + FAIL_MINUTES * 60
    for i, data in zip(todo, fresh, strict=True):
        k = keys[i]
        if data is not None:
            exp = time.time() + config.settings.places_cache_hours * 3600
            col.update_one(
                {"key": k}, {"$set": {"key": k, "ok": True, "data": data, "fetched_at": mongo.now(), "expires_ts": exp}}, upsert=True
            )
            out[i] = data
        elif out[i] is not None:  # keep the last good answer, retry later
            col.update_one({"key": k}, {"$set": {"expires_ts": retry}})
        else:
            col.update_one({"key": k}, {"$set": {"key": k, "ok": False, "fetched_at": mongo.now(), "expires_ts": retry}}, upsert=True)
    return out


def _num(v) -> float | None:  # noqa: ANN001
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _shape_meta(body: dict) -> list[dict]:
    """Destination ids, names and districts (no coordinates): enough to find the hotel's town. /meta is fast."""
    dnames = {str(d.get("id")): str(d.get("name") or "") for d in (body or {}).get("districts") or []}
    return [
        {
            "id": str(d["id"])[:60],
            "name": str(d["name"])[:80],
            "district": str(d.get("district") or "")[:40],
            "district_name": dnames.get(str(d.get("district")), "")[:60],
        }
        for d in (body or {}).get("destinations") or []
        if d.get("id") and d.get("name")
    ]


def _shape_destinations(body: dict) -> list[dict]:
    out = []
    for d in (body or {}).get("items") or []:
        lat, lon = _num(d.get("lat")), _num(d.get("lon"))
        if not d.get("id") or not d.get("name") or lat is None or lon is None:
            continue
        crowd = d.get("crowd_today") or {}
        out.append(
            {
                "id": str(d["id"])[:60],
                "name": str(d["name"])[:80],
                "district": str(d.get("district") or "")[:40],
                "district_name": str(d.get("district_name") or "")[:60],
                "lat": lat,
                "lon": lon,
                "tags": [str(t)[:30] for t in (d.get("tags") or [])][:8],
                "why_go": str(d.get("why_go") or "")[:200],
                "crowd_band": str(crowd.get("band") or "")[:20],
                "crowd_index": _num(crowd.get("index")),
                "distance_km": _num(d.get("distance_km")),  # only in /nearby answers (from the town centre)
            }
        )
    return out


def _shape_viewpoints(body: dict) -> list[dict]:
    out = []
    for g in (body or {}).get("groups") or []:
        for x in g.get("items") or []:
            lat, lon = _num(x.get("lat")), _num(x.get("lon"))
            if x.get("name") and lat is not None and lon is not None:
                out.append({"name": str(x["name"])[:80], "lat": lat, "lon": lon, "distance_km": _num(x.get("distance_km"))})
    return out[:6]


def _shape_experiences(body: dict) -> list[dict]:
    out = []
    for e in (body or {}).get("items") or []:
        if not e.get("title"):
            continue
        out.append(
            {
                "id": str(e.get("id") or "")[:40],
                "title": str(e["title"])[:100],
                "type": str(e.get("type") or "")[:30],
                "type_label": str(e.get("type_label") or "")[:60],
                "destination_id": str(e.get("destination_id") or "")[:60],
                "destination_name": str(e.get("destination_name") or "")[:80],
                "duration_hours": _num(e.get("duration_hours")),
                "group_max": _num(e.get("group_max")),
                "synthetic": bool(e.get("synthetic")),
            }
        )
    return out[:50]


# ------------------------------------------------------------------ matching
def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _fold(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split()) + " "


def anchor(dests: list[dict], text: str, loc: dict | None = None) -> tuple[dict | None, str]:
    """(the portal destination that is the hotel's town, how it was found: "name" | "district" | "coords" | "").
    A destination name in the hotel's town / region / name (earliest mention) wins, then a district name, then the
    nearest destination to the hotel's coordinates (only when `dests` carry coordinates and it is within ANCHOR_KM)."""
    loc = loc or {}
    t = _fold(f"{loc.get('town') or ''} {text}")
    best = None
    for d in dests:
        for part in d["name"].split("/"):
            p = _fold(part).strip()
            i = t.find(f" {p} ") if p else -1
            if i >= 0 and (best is None or i < best[0]):
                best = (i, d)
    if best:
        return best[1], "name"
    t = _fold(f"{loc.get('district') or ''} {text}")
    for d in dests:
        names = {_fold(d.get("district_name")).strip(), _fold(d.get("district", "").replace("-", " ")).strip()} - {""}
        if any(f" {n} " in t for n in names):
            same = [x for x in dests if x["district"] == d["district"]]
            return next((x for x in same if x["id"] == d["district"]), same[0]), "district"
    lat, lon = _num(loc.get("lat")), _num(loc.get("lon"))
    with_xy = [d for d in dests if d.get("lat") is not None and d.get("lon") is not None]
    if lat is not None and lon is not None and with_xy:
        km, d = min(((haversine_km(lat, lon, d["lat"], d["lon"]), d) for d in with_xy), key=lambda x: x[0])
        if km <= ANCHOR_KM:
            return d, "coords"
    return None, ""


# ------------------------------------------------------------------ cards
def maps_url(name: str, lat: float | None, lon: float | None, town: str = "") -> str:
    if lat is not None and lon is not None:
        return MAPS + quote(f"{lat:.5f},{lon:.5f}", safe=",")
    return MAPS + quote(", ".join(x for x in (name, town, "Uttarakhand") if x), safe=",")


def _kind_from_name(name: str) -> str:
    t = _fold(name)
    for kind, words in NAME_KINDS:
        if any(f" {w} " in t or (not w.isascii() and w in name) for w in words):
            return kind
    return "mountain"


def card(
    name: str,
    tip: str,
    kind: str,
    *,
    lat: float | None = None,
    lon: float | None = None,
    distance_km: float | None = None,
    distance_note: str = "",
    town: str = "",
    source: str = "hotel",
    offbeat: str | None = None,
    image: str | None = None,
    sample: bool = False,
) -> dict:
    """One place card. `offbeat` = the signal that makes it a quieter spot (a key of OFFBEAT_SIGNALS) or None."""
    if distance_km is not None and distance_km < 0.05:
        distance_km = None
    if distance_km is not None:
        distance_km = round(distance_km) if distance_km >= 1 else round(distance_km, 1)
    return {
        "name": name,
        "tip": " ".join(str(tip or "").split())[:160],
        "kind": kind,
        "image": image if image and SAFE_IMG.match(image) else IMG.format(kind),
        "distance_km": distance_km,
        "distance_note": str(distance_note or "")[:80],
        "maps_url": maps_url(name, lat, lon, town),
        "source": source,
        "offbeat": bool(offbeat),
        "why_quiet": OFFBEAT_SIGNALS.get(offbeat or "", ""),
        "why_quiet_hi": OFFBEAT_SIGNALS_HI.get(offbeat or "", ""),
        "sample": sample,
    }


def _hotel_cards(prof: dict, town: str) -> list[dict]:
    out = []
    for n in prof.get("nearby") or []:
        tip = n.get("tip") or ""
        quiet = n.get("offbeat") or any(w in tip.lower() for w in QUIET_TIP_WORDS)
        out.append(
            card(
                n["name"],
                tip,
                _kind_from_name(n["name"]),
                lat=_num(n.get("lat")),
                lon=_num(n.get("lon")),
                distance_note=n.get("distance_note") or "",
                town=town,
                source="hotel",
                offbeat="hotel" if quiet else None,
                image=n.get("photo_url"),
            )
        )
    return out


def _dest_kind(d: dict) -> str:
    return next((k for tag, k in DEST_KINDS if tag in d.get("tags", [])), "town")


EMPTY = {"viewpoints": [], "destinations": [], "experiences": []}


def _lookup(text: str, loc: dict, deadline: float) -> tuple[dict[str, list[dict]], dict | None]:
    """Portal cards around the hotel's town: ({"viewpoints", "destinations", "experiences"}, the town or None)."""
    meta = _get_many([("/meta", {}, _shape_meta)], deadline)[0] or []
    home, how = anchor(meta, text, loc)
    lat, lon = _num(loc.get("lat")), _num(loc.get("lon"))
    xy = (lat, lon) if lat is not None and lon is not None else None
    if home is None and xy:  # only coordinates: the full list has them (slow on the portal, so only in this case)
        full = _get_many([("/destinations", {}, _shape_destinations)], deadline, timeout=SLOW_TIMEOUT_S)[0] or []
        home, how = anchor(full, "", {"lat": lat, "lon": lon})
    if home is None:
        return EMPTY, None
    hid = quote(home["id"], safe="")
    in_district, around, views, exps = _get_many(
        [
            ("/destinations", {"district": home["district"]}, _shape_destinations),
            (f"/destinations/{hid}/nearby", {"limit": 8}, _shape_destinations),
            (f"/destinations/{hid}/places", {"category": "viewpoint"}, _shape_viewpoints),
            ("/local-experiences", {"district": home["district"], "page_size": 50}, _shape_experiences),
        ],
        deadline,
    )
    by_id: dict[str, dict] = {}
    for d in (around or []) + (in_district or []):  # the district list has the longer description: it wins
        by_id[d["id"]] = {**by_id.get(d["id"], {}), **{k: v for k, v in d.items() if v not in (None, "", [])}}
    town = by_id.get(home["id"], home)
    if not xy and how == "name" and town.get("lat") is not None:
        xy = (town["lat"], town["lon"])

    def km_to(d: dict) -> float | None:
        if xy and d.get("lat") is not None:
            return haversine_km(xy[0], xy[1], d["lat"], d["lon"])
        return d.get("distance_km") if how == "name" else None  # the portal's distance from the town centre

    out: dict[str, list[dict]] = {"viewpoints": [], "destinations": [], "experiences": []}
    for v in views or []:
        out["viewpoints"].append(
            card(
                v["name"],
                f"Viewpoint near {home['name']} (OpenStreetMap)",
                "viewpoint",
                lat=v["lat"],
                lon=v["lon"],
                distance_km=km_to(v),
                town=home["name"],
                source="openstreetmap",
            )
        )
    home_idx = town.get("crowd_index")
    near = []
    for d in by_id.values():
        if d["id"] == home["id"] or d.get("lat") is None:
            continue
        km = km_to(d)
        if (km is not None and km <= MAX_KM) or (km is None and d.get("district") == home["district"]):
            near.append((km, d))
    near.sort(key=lambda x: (x[0] is None, x[0] or 0))
    for km, d in near:
        idx = d.get("crowd_index")
        quiet = (
            d.get("crowd_band") in QUIET_BANDS
            and (home_idx is None or (idx is not None and idx < home_idx))
            and d["id"] not in WELL_KNOWN
            and not NOT_OFFBEAT_TAGS & set(d.get("tags") or [])
        )
        out["destinations"].append(
            card(
                d["name"],
                d.get("why_go") or ", ".join(d.get("tags") or []).capitalize(),
                _dest_kind(d),
                lat=d["lat"],
                lon=d["lon"],
                distance_km=km,
                source="portal",
                offbeat="crowd" if quiet else None,
                image=DEST_PHOTOS.get(d["id"]),
            )
        )
    exps = sorted(exps or [], key=lambda e: (e["destination_id"] != home["id"], e["type"] not in OFFBEAT_EXPERIENCES))
    seen = set()
    for e in exps:
        if (e["destination_id"], e["type"]) in seen:
            continue
        seen.add((e["destination_id"], e["type"]))
        d = by_id.get(e["destination_id"])
        km = km_to(d) if d and d["id"] != home["id"] else None  # an experience in the hotel's own town: no distance
        if km is not None and km > MAX_KM:
            continue
        bits = [e["type_label"]]
        if e.get("duration_hours"):
            bits.append(f"about {e['duration_hours']:g} h")
        if e.get("group_max"):
            bits.append(f"up to {e['group_max']:g} people")
        out["experiences"].append(
            card(
                e["title"],
                ", ".join(b for b in bits if b) + ". Book through the tourism portal.",
                EXP_KINDS.get(e["type"], "village"),
                distance_km=km,
                town=e.get("destination_name") or home["name"],
                source="portal",
                offbeat="experience" if e["type"] in OFFBEAT_EXPERIENCES else None,
                sample=e["synthetic"],
            )
        )
    return out, home


def _dedupe(cards: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in cards:
        k = _fold(c["name"]).strip()
        if k and k not in seen:
            seen.add(k)
            out.append(c)
    return out


def find(tid: str | None, property_id: str | None, prof: dict, offbeat: bool = False) -> dict:
    """{"near": town name or "", "cards": [...], "offbeat_found": bool, "from_portal": bool}. Never raises."""
    region = ""
    if tid:
        try:
            region = tenants.get_property(tid, property_id).get("region") or ""
        except Exception:  # noqa: BLE001 - a missing property only means no town to match
            region = ""
    loc = prof.get("location") or {}
    town_hint = (loc.get("town") or region.split(",")[0] or "").strip()
    hotel = _hotel_cards(prof, town_hint)
    need = len(hotel) < MIN_PLACES or (offbeat and sum(c["offbeat"] for c in hotel) < MIN_OFFBEAT)
    portal, home = EMPTY, None
    if need:
        try:
            portal, home = _lookup(f"{region} {prof.get('display_name') or ''}", loc, time.monotonic() + BUDGET_S)
        except Exception as e:  # noqa: BLE001 - never break the chat over the places lookup
            log.warning("places lookup failed: %s", type(e).__name__)
    near = (home["name"] if home else "") or town_hint
    if offbeat:
        quiet = _dedupe([c for c in hotel if c["offbeat"]] + [c for c in portal["experiences"] + portal["destinations"] if c["offbeat"]])
        if quiet:
            return {"near": near, "cards": quiet[:MAX_CARDS], "offbeat_found": True, "from_portal": need}
    general = _dedupe(hotel + portal["viewpoints"][:3] + portal["destinations"][:2] + portal["experiences"][:2])
    if offbeat:  # nothing quiet found: the popular ones, and the reply says so
        general = [{**c, "offbeat": False, "why_quiet": "", "why_quiet_hi": ""} for c in general]
    return {"near": near, "cards": general[:MAX_CARDS], "offbeat_found": False, "from_portal": need}
