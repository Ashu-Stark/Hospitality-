"""Trip planning: experiences (themes), circuits, sample itineraries, nearby destinations, official links, district offices.

Live data per destination comes from the existing services: crowd estimate (always "estimate"), weather (Open-Meteo,
cached) and active road advisories. Itineraries are SAMPLE planning suggestions; no distances, drive times or prices.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, timedelta

from .. import mongo
from ..errors import NotFound
from ..seed.destinations import BY_ID_DEST, DESTINATIONS
from ..seed.districts import BY_ID as DISTRICTS
from ..seed.districts import DISTRICTS as DISTRICT_LIST
from ..seed.experiences import (
    BY_ID_EXP,
    BY_ID_ITIN,
    CIRCUITS,
    EXPERIENCES,
    ITINERARIES,
    ITINERARY_NOTE,
    OFFICIAL_SERVICES,
    OFFICIAL_SERVICES_NOTE,
)
from . import advisories, crowd, events, locationiq, traffic, weather

ROAD_ORDER = {"closed": 0, "caution": 1, "open": 2}
DISTANCE_NOTE = "Straight-line distance between approximate coordinates, not road distance or travel time."
EARTH_KM = 6371.0
WEATHER_BUDGET_S = 6.0  # itinerary detail: live weather for all stops in parallel within this budget, else cache only


def haversine_km(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


def _dest_card(d: dict, ctx: crowd.Context, today: date) -> dict:
    t = crowd.day_index(ctx, d["id"], today)
    return {
        "id": d["id"],
        "name": d["name"],
        "district": d["district"],
        "district_name": DISTRICTS[d["district"]]["name"],
        "division": d["division"],
        "lat": d["lat"],
        "lon": d["lon"],
        "themes": d.get("themes", []),
        "tags": d["tags"],
        "best_months": d["best_months"],
        "crowd_today": {"index": t["index"], "band": t["band"], "label": "estimate"},
        "weather_now": weather.cached_summary(d["id"]),
    }


def _worst_road(dest_id: str) -> dict | None:
    items = [a for a in advisories.list_public(destination=dest_id)["items"] if a["kind"] == "road"]
    if not items:
        return None
    w = min(items, key=lambda a: ROAD_ORDER.get(a.get("status"), 3))
    return {
        "status": w.get("status"),
        "title": w["title"],
        "segment": w.get("segment"),
        "count": len(items),
        "sample": w.get("sample", False),
    }


# ------------------------------------------------------------------ experiences
def _exp_summary(e: dict) -> dict:
    ids = [d["id"] for d in DESTINATIONS if e["id"] in d.get("themes", [])]
    return {k: e[k] for k in ("id", "name", "short", "icon")} | {"destination_count": len(ids), "destination_ids": ids}


def list_experiences() -> dict:
    return {"items": [_exp_summary(e) for e in EXPERIENCES], "total": len(EXPERIENCES)}


def get_experience(exp_id: str) -> dict:
    e = BY_ID_EXP.get(exp_id)
    if not e:
        raise NotFound("Experience not found.")
    ctx = crowd.Context()
    today = mongo.today()
    dests = [_dest_card(d, ctx, today) for d in DESTINATIONS if exp_id in d.get("themes", [])]
    db = mongo.db()
    fest = [events.public(x) for x in db.events.find({"id": {"$in": e["festival_ids"]}})]
    fest.sort(key=lambda x: e["festival_ids"].index(x["id"]))
    terms = {
        t["id"]: t for t in db.dictionary.find({"id": {"$in": e["term_ids"]}}, {"_id": 0, "id": 1, "term": 1, "hindi": 1, "definition": 1})
    }
    return {
        **{k: e[k] for k in ("id", "name", "short", "intro", "icon")},
        "destinations": dests,
        "festivals": fest,
        "terms": [terms[t] for t in e["term_ids"] if t in terms],
        "itineraries": [_itin_summary(i) for i in ITINERARIES if i["theme"] == exp_id],
        "circuits": [_circuit(c) for c in CIRCUITS if c["theme"] == exp_id],
        "crowd_note": "Crowd level is an estimate. Weather shown only when recently loaded; open a destination for the live forecast.",
    }


# ------------------------------------------------------------------ circuits
def _circuit(c: dict) -> dict:
    return {
        **{k: c[k] for k in ("id", "name", "theme", "description", "destination_ids")},
        "destinations": [
            {"id": d, "name": BY_ID_DEST[d]["name"], "lat": BY_ID_DEST[d]["lat"], "lon": BY_ID_DEST[d]["lon"]} for d in c["destination_ids"]
        ],
    }


def list_circuits() -> dict:
    return {
        "items": [_circuit(c) for c in CIRCUITS],
        "total": len(CIRCUITS),
        "note": "Groupings for planning; the order is a suggestion. Verify routes.",
    }


# ------------------------------------------------------------------ itineraries
def _itin_summary(i: dict) -> dict:
    return {
        "id": i["id"],
        "name": i["name"],
        "theme": i["theme"],
        "theme_name": BY_ID_EXP[i["theme"]]["name"],
        "circuit_id": i["circuit_id"],
        "summary": i["summary"],
        "stops": [{"destination_id": d, "name": BY_ID_DEST[d]["name"], "suggested_days": n} for d, n in i["stops"]],
        "suggested_days_total": sum(n for _, n in i["stops"]),
        "sample": True,
        "note": ITINERARY_NOTE,
    }


def list_itineraries(theme: str | None = None) -> dict:
    items = [_itin_summary(i) for i in ITINERARIES if not theme or i["theme"] == theme]
    return {"items": items, "total": len(items), "note": ITINERARY_NOTE}


def best_start(ctx: crowd.Context, stops: list[tuple[str, int]], today: date, window: int = 14) -> dict:
    """Start day in the next `window` days with the lowest average crowd index over the whole trip (stops in order)."""
    plan: list[str] = [d for d, n in stops for _ in range(max(1, n))]
    cache: dict = {}

    def idx(dest_id: str, day: date) -> int:
        k = (dest_id, day)
        if k not in cache:
            cache[k] = crowd.day_index(ctx, dest_id, day)["index"]
        return cache[k]

    scored = []
    for s in range(window):
        start = today + timedelta(days=s)
        vals = [idx(d, start + timedelta(days=k)) for k, d in enumerate(plan)]
        scored.append((sum(vals) / len(vals), s, start, max(vals)))
    avg, s, start, peak = min(scored)
    today_avg = scored[0][0]
    return {
        "date": start.isoformat(),
        "offset_days": s,
        "avg_index": round(avg),
        "band": crowd.band(avg),
        "peak_index": peak,
        "if_start_today": {"avg_index": round(today_avg), "band": crowd.band(today_avg)},
        "window_days": window,
        "label": "estimate",
        "method": "Lowest average crowd estimate over all trip days, for start dates in the next 14 days, following the suggested days per stop.",
    }


def _compact_weather(w: dict) -> dict:
    if not w.get("available"):
        return {"available": False}
    return {
        "available": True,
        "temperature_c": w["current"].get("temperature_c"),
        "summary": w["current"].get("summary"),
        "warning": (w["warnings"] or [None])[0],
    }


def _stop_weather(dest_ids: list[str]) -> dict:
    """Live weather for all stops in parallel within WEATHER_BUDGET_S; stops not done in time fall back to the cache."""
    ids = list(dict.fromkeys(dest_ids))
    out: dict = {}
    pool = ThreadPoolExecutor(max_workers=min(6, len(ids)) or 1)
    futures = {pool.submit(weather.for_destination, d): d for d in ids}
    done, _ = wait(futures, timeout=WEATHER_BUDGET_S)
    for f in done:
        try:
            out[futures[f]] = _compact_weather(f.result())
        except Exception:  # noqa: BLE001 - weather is optional on this page
            out[futures[f]] = {"available": False}
    pool.shutdown(wait=False, cancel_futures=True)
    for d in ids:
        if d not in out:
            out[d] = weather.cached_summary(d) or {"available": False}
    return out


def get_itinerary(itin_id: str) -> dict:
    i = BY_ID_ITIN.get(itin_id)
    if not i:
        raise NotFound("Itinerary not found.")
    ctx = crowd.Context()
    today = mongo.today()
    wx_by_dest = _stop_weather([d for d, _ in i["stops"]])
    bs = best_start(ctx, i["stops"], today)
    arrive = date.fromisoformat(bs["date"])  # day each stop is reached when starting on the suggested day
    stops = []
    for n, (dest_id, days) in enumerate(i["stops"]):
        d = BY_ID_DEST[dest_id]
        t = crowd.day_index(ctx, dest_id, today)
        wx = wx_by_dest.get(dest_id) or {"available": False}
        stops.append(
            {
                "order": n + 1,
                "destination_id": dest_id,
                "name": d["name"],
                "district_name": DISTRICTS[d["district"]]["name"],
                "suggested_days": days,
                "best_months": d["best_months"],
                "route_facts": d["route_facts"],
                "crowd_today": {"index": t["index"], "band": t["band"], "label": "estimate"},
                "weather": wx,
                "road": _worst_road(dest_id),
                # predicted road congestion over daylight hours on the day this stop is reached (not measured)
                "traffic": _stop_traffic(dest_id, arrive, ctx),
            }
        )
        arrive += timedelta(days=max(1, days))
    return {**_itin_summary(i), "stops": stops, "best_start": bs, "generated_at": mongo.iso(mongo.now())}


def _stop_traffic(dest_id: str, day: date, ctx: crowd.Context) -> dict | None:
    try:
        return traffic.predict_day(dest_id, day, ctx)
    except Exception:  # noqa: BLE001 - optional on this page
        return None


# ------------------------------------------------------------------ nearby, map, links, offices
def nearby(dest_id: str, limit: int = 6) -> dict:
    d = BY_ID_DEST.get(dest_id)
    if not d:
        raise NotFound("Destination not found.")
    ctx = crowd.Context()
    today = mongo.today()
    others = sorted((haversine_km(d, o), o) for o in DESTINATIONS if o["id"] != dest_id)
    items = [{**_dest_card(o, ctx, today), "distance_km": round(km)} for km, o in others[:limit]]
    return {"destination_id": dest_id, "items": items, "total": len(items), "distance_note": DISTANCE_NOTE}


def map_points() -> dict:
    ctx = crowd.Context()
    today = mongo.today()
    pts = [_dest_card(d, ctx, today) | {"circuits": [c["id"] for c in CIRCUITS if d["id"] in c["destination_ids"]]} for d in DESTINATIONS]
    return {
        "items": pts,
        "circuits": [_circuit(c) for c in CIRCUITS],
        "experiences": [{"id": e["id"], "name": e["name"]} for e in EXPERIENCES],
        "districts": [dict(x) for x in DISTRICT_LIST],
        "bounds": {
            "lat": [min(p["lat"] for p in pts), max(p["lat"] for p in pts)],
            "lon": [min(p["lon"] for p in pts), max(p["lon"] for p in pts)],
        },
        "note": "Schematic dot map from approximate coordinates; not to scale; no boundaries shown.",
        "static_map": locationiq.map_info(),
    }


def official_services() -> dict:
    return {"items": [dict(s, external=True) for s in OFFICIAL_SERVICES], "note": OFFICIAL_SERVICES_NOTE}


def district_offices() -> dict:
    items = [
        {
            "district": x["id"],
            "district_name": x["name"],
            "division": x["division"],
            "office": f"District tourism office, {x['name']}",
            "contact": None,
            "note": "Contact details to be filled by the department.",
        }
        for x in DISTRICT_LIST
    ]
    return {"items": items, "total": len(items), "note": "Placeholders: names and numbers are to be filled by the department."}
