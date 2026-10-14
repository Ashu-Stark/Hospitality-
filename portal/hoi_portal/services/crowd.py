"""Crowd level ("rush") index 0-100 per destination and day. Always an ESTIMATE.

Inputs:
  * occupancy of registered stays at the destination (`occupancy_agg`: seeded synthetic history, monthly submissions
    and HOI ingest). For a day with reported data the reported occupancy is used ("reported"); otherwise the
    occupancy is estimated from the same weekday a year and two years earlier (+-3 days), then from the usual level
    for that month, then from the destination's seasonal pattern ("estimate").
  * festivals / yatra calendar and officer events affecting the destination or its district,
  * weekends, and season (peak months / closed season of the destination's seasonal pattern).

    index = clamp(0.8 * occupancy% + event + weekend + season, 0, 100)
        event   = +12 high, +6 medium, +2 low impact (largest single event)        ASSUMED weights
        weekend = +5 on Saturday and Sunday                                          ASSUMED
        season  = +5 in the pattern's peak months, -10 in its closed months          ASSUMED

Bands (spec): low < 40, moderate 40-64, high 65-84, very high >= 85.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date, timedelta

from .. import config, mongo
from ..errors import NotFound
from ..seed.destinations import BY_ID_DEST, DESTINATIONS
from ..seed.generator import PROFILES
from . import besttime
from . import events as events_svc

BANDS = [
    {"key": "low", "label": "Low", "min": 0, "max": 39},
    {"key": "moderate", "label": "Moderate", "min": 40, "max": 64},
    {"key": "high", "label": "High", "min": 65, "max": 84},
    {"key": "very_high", "label": "Very high", "min": 85, "max": 100},
]
EVENT_BOOST = {"high": 12, "medium": 6, "low": 2}
WEEKEND_BOOST, PEAK_BOOST, CLOSED_PENALTY, OCC_WEIGHT = 5, 5, -10, 0.8
ALERT_AT = 85
NOTE = "Estimate based on synthetic and reported occupancy, festivals, weekends and season. Not a headcount; plan with care."

_LOCK = threading.Lock()
_CACHE: dict = {"key": None, "at": 0.0, "data": None}
TTL_S = 300


def band(index: float | int) -> str:
    i = round(index)
    if i >= 85:
        return "very_high"
    if i >= 65:
        return "high"
    if i >= 40:
        return "moderate"
    return "low"


def band_label(key: str) -> str:
    return next(b["label"] for b in BANDS if b["key"] == key)


def invalidate() -> None:
    with _LOCK:
        _CACHE["key"] = None


def occupancy_data() -> dict:
    """{(destination_id, stay_type): {date: (rooms_available, rooms_occupied)}} from occupancy_agg, cached in-process."""
    key = (mongo.generation, config.settings.db_name)
    with _LOCK:
        if _CACHE["key"] == key and time.monotonic() - _CACHE["at"] < TTL_S:
            return _CACHE["data"]
    data: dict = defaultdict(dict)
    for doc in mongo.db().occupancy_agg.find({}, {"_id": 0, "destination_id": 1, "stay_type": 1, "month": 1, "avail": 1, "occ": 1}):
        y, m = (int(x) for x in doc["month"].split("-"))
        first = date(y, m, 1)
        series = data[(doc["destination_id"], doc["stay_type"])]
        for i, (a, o) in enumerate(zip(doc["avail"], doc["occ"])):
            if a:
                series[first + timedelta(days=i)] = (a, o)
    data = dict(data)
    with _LOCK:
        _CACHE.update(key=key, at=time.monotonic(), data=data)
    return data


def dest_series(data: dict, dest_id: str, types: tuple[str, ...] = ("hotel", "homestay")) -> dict:
    out: dict = {}
    for t in types:
        for d, (a, o) in data.get((dest_id, t), {}).items():
            pa, po = out.get(d, (0, 0))
            out[d] = (pa + a, po + o)
    return out


def _rate(series: dict, days) -> float | None:
    a = o = 0
    for d in days:
        v = series.get(d)
        if v:
            a, o = a + v[0], o + v[1]
    return 100.0 * o / a if a else None


class Context:
    """Per-request bundle: occupancy series per destination, events and month averages (computed once)."""

    def __init__(self):
        self.data = occupancy_data()
        self.events = list(mongo.db().events.find({}, {"_id": 0, "search_text": 0}))
        self._series: dict = {}
        self._month: dict = {}

    def series(self, dest_id: str) -> dict:
        if dest_id not in self._series:
            self._series[dest_id] = dest_series(self.data, dest_id)
        return self._series[dest_id]

    def month_rate(self, dest_id: str, month: int) -> float | None:
        k = (dest_id, month)
        if k not in self._month:
            s = self.series(dest_id)
            self._month[k] = _rate(s, [d for d in s if d.month == month])
        return self._month[k]


def occupancy_for(ctx: Context, dest_id: str, day: date) -> tuple[float, str]:
    s = ctx.series(dest_id)
    if day in s:
        a, o = s[day]
        return 100.0 * o / a, "reported"
    near = []
    for back in (364, 728):  # same weekday one and two years earlier
        near += [day - timedelta(days=back + k) for k in range(-3, 4)]
    r = _rate(s, near)
    if r is not None:
        return r, "estimate"
    r = ctx.month_rate(dest_id, day.month)
    if r is not None:
        return r, "estimate"
    return 100.0 * PROFILES[BY_ID_DEST[dest_id]["profile"]][day.month - 1], "seasonal pattern"


def day_index(ctx: Context, dest_id: str, day: date) -> dict:
    occ, basis = occupancy_for(ctx, dest_id, day)
    evs = events_svc.active_on(ctx.events, dest_id, day)
    ev_boost = max((EVENT_BOOST.get(e.get("crowd_impact"), 0) for e in evs), default=0)
    weekend = WEEKEND_BOOST if day.weekday() >= 5 else 0
    base = PROFILES[BY_ID_DEST[dest_id]["profile"]][day.month - 1]
    season = PEAK_BOOST if base >= 0.8 else CLOSED_PENALTY if base <= 0.1 else 0
    idx = int(round(max(0.0, min(100.0, OCC_WEIGHT * occ + ev_boost + weekend + season))))
    return {
        "date": day.isoformat(),
        "index": idx,
        "band": band(idx),
        "occupancy_pct": round(occ, 1),
        "basis": basis,
        "events": [e["name"] for e in evs if EVENT_BOOST.get(e.get("crowd_impact"), 0) == ev_boost and ev_boost][:2],
        "weekend": bool(weekend),
    }


def usual_by_month(ctx: Context, dest_id: str) -> list[dict]:
    s = ctx.series(dest_id)
    by_month: dict[int, list[int]] = defaultdict(list)
    for d in s:
        by_month[d.month].append(day_index(ctx, dest_id, d)["index"])
    out = []
    for m in range(1, 13):
        vals = by_month.get(m)
        if vals:
            v = round(sum(vals) / len(vals))
        else:  # no history for this month: use the seasonal pattern on a mid-month weekday
            v = day_index(ctx, dest_id, date(2025, m, 15))["index"]
        out.append({"month": m, "index": v, "band": band(v)})
    return out


def outlook(ctx: Context, dest_id: str, start: date, days: int = 14) -> list[dict]:
    return [day_index(ctx, dest_id, start + timedelta(days=i)) for i in range(days)]


def for_destination(dest_id: str, ctx: Context | None = None) -> dict:
    if dest_id not in BY_ID_DEST:
        raise NotFound("Destination not found.")
    ctx = ctx or Context()
    today = mongo.today()
    look = outlook(ctx, dest_id, today, 14)
    peak = max(look, key=lambda x: x["index"])
    return {
        "label": "estimate",
        "note": NOTE,
        "bands": BANDS,
        "today": look[0],
        "outlook": look,
        "outlook_peak": peak,
        "alert": peak["index"] >= ALERT_AT,
        "usual_by_month": usual_by_month(ctx, dest_id),
        "method": "0.8 x occupancy% + event (+12/+6/+2) + weekend (+5) + season (+5 peak / -10 closed); ASSUMED weights.",
        # Real typical foot traffic at one well-known venue (BestTime, cached); shown alongside the estimate, never mixed in.
        "foot_traffic": besttime.foot_traffic(dest_id),
    }


def all_destination_ids(district: str | None = None) -> list[str]:
    return [d["id"] for d in DESTINATIONS if not district or d["district"] == district]
