"""Destination list and detail page (weather, roads, crowd, advisories, nearby businesses, events)."""

from __future__ import annotations

import copy
import threading
import time

from .. import config, mongo
from ..errors import Invalid, NotFound
from ..seed.districts import BY_ID as DISTRICTS
from . import advisories, crowd, events, registry, search, traffic, traffic_live, weather

FIELDS = (
    "id",
    "name",
    "district",
    "division",
    "lat",
    "lon",
    "altitude_m",
    "altitude_note",
    "tags",
    "themes",
    "best_months",
    "season_notes",
    "route_facts",
    "facts_note",
    "why_go",
)


# Short in-process cache for the unfiltered list (the home page and the list page call it on every visit). Keyed on the
# database generation (tests reset it), the database name and today's date (crowd_today changes daily); dropped by
# invalidate_list() when road alerts, events, local experiences or occupancy change. Weather in the list is cache-only
# anyway, so a 2-minute delay there is acceptable.
LIST_TTL_S = 120
_LIST_LOCK = threading.Lock()
_LIST_CACHE: dict = {"key": None, "at": 0.0, "data": None}


def invalidate_list() -> None:
    with _LIST_LOCK:
        _LIST_CACHE["key"] = None
        _LIST_CACHE["data"] = None


def summary(d: dict, ctx: crowd.Context | None = None) -> dict:
    out = {k: d.get(k) for k in FIELDS}
    out["district_name"] = DISTRICTS[d["district"]]["name"]
    if ctx is not None:
        t = crowd.day_index(ctx, d["id"], mongo.today())
        out["crowd_today"] = {"index": t["index"], "band": t["band"], "label": "estimate"}
        # Usual band per month (Jan..Dec), the same estimate as the detail page's usual_by_month; feeds the month strip.
        out["usual_busy"] = [m["band"] for m in crowd.usual_by_month(ctx, d["id"])]
    return out


def list_destinations(district: str | None = None, tag: str | None = None, q: str | None = None, with_crowd: bool = True) -> dict:
    if district or tag or q or not with_crowd:
        return _list(district, tag, q, with_crowd)
    key = (mongo.generation, config.settings.db_name, mongo.today().isoformat())
    with _LIST_LOCK:
        if _LIST_CACHE["key"] == key and time.monotonic() - _LIST_CACHE["at"] < LIST_TTL_S:
            return copy.deepcopy(_LIST_CACHE["data"])
    data = _list(None, None, None, True)
    with _LIST_LOCK:
        _LIST_CACHE.update(key=key, at=time.monotonic(), data=copy.deepcopy(data))
    return data


def _list(district: str | None, tag: str | None, q: str | None, with_crowd: bool) -> dict:
    f: dict = {}
    if district:
        if district not in DISTRICTS:
            raise Invalid("Unknown district.")
        f["district"] = district
    if tag:
        f["tags"] = tag
    f.update(search.regex_filter(q))
    from . import local_experiences

    ctx = crowd.Context() if with_crowd else None
    lx = local_experiences.counts_by_destination()
    docs = list(mongo.db().destinations.find(f).sort("name", 1))
    wx = weather.cached_summaries([d["id"] for d in docs])  # cache only, never calls the forecast service
    items = []
    for d in docs:
        s = summary(d, ctx)
        s["weather_now"] = wx[d["id"]]
        s["local_experiences"] = lx.get(d["id"], 0)
        items.append(s)
    tags = sorted({t for d in mongo.db().destinations.find({}, {"tags": 1}) for t in d.get("tags", [])})
    return {"items": items, "total": len(items), "tags": tags, "note": "Coordinates and facts are approximate; verify before travel."}


def get_doc(dest_id: str) -> dict:
    d = mongo.db().destinations.find_one({"id": dest_id})
    if not d:
        raise NotFound("Destination not found.")
    return d


def detail(dest_id: str) -> dict:
    d = get_doc(dest_id)
    ctx = crowd.Context()
    road_adv = advisories.list_public(destination=dest_id)
    road_items = [a for a in road_adv["items"] if a["kind"] == "road"]
    try:
        tr = traffic.summary(dest_id, ctx)  # prediction (always) + live incidents (when a provider answers)
    except Exception:  # noqa: BLE001 - never break the destination page
        tr = None
    live = (tr or {}).get("live")
    return {
        "destination": summary(d),
        "weather": weather.for_destination(dest_id),
        "crowd": crowd.for_destination(dest_id, ctx),
        "roads": {
            "facts": d["route_facts"],
            "facts_note": d["facts_note"],
            "advisories": road_items,
            "traffic": tr,  # predicted congestion (not measured), next 24 h + best time to drive + factors
            "live": live,  # live incidents from a provider (None when unavailable or nothing reported)
            "worst": worst_road(road_items, live),
        },
        "advisories": road_adv["items"],
        "nearby": registry.nearby(dest_id),
        "events": events.for_destination(dest_id),
        "local_experiences": _local(dest_id),
        "last_updated": mongo.iso(mongo.now()),
    }


def worst_road(road_advisories: list[dict], live: dict | None) -> dict | None:
    """The worst road status from officer advisories and TomTom live traffic, with its source (None = nothing reported)."""
    order = traffic_live.STATUS_ORDER
    cands = [(order.get(a.get("status"), 3), "advisory", a.get("status")) for a in road_advisories if a.get("status")]
    if live and live.get("total"):
        cands.append((order[live["status"]], live["source"], live["status"]))
    if not cands:
        return None
    _, source, status = min(cands, key=lambda c: (c[0], c[1] != "advisory"))
    return {"status": status, "source": source}


def _local(dest_id: str) -> dict:
    from . import local_experiences

    return local_experiences.for_destination(dest_id)
