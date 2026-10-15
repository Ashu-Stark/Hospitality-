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

REAL-DATA MODEL (Kedarnath, Badrinath, Gangotri, Yamunotri): when the bundle `hoi_portal/models/crowd_real_v1.json`
loads, these four shrines use the crowd model trained on official pilgrim counts (ml/realdata/crowd; byte-identical
predict code in `crowd_model.py`). Each day then carries the expected pilgrims, an 80% range, a confidence label and
its basis (model, last season's level, official count, closed season). Days the model cannot call (no announced
season dates, abstain) use the estimate above with confidence "low".
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .. import config, mongo
from ..errors import NotFound
from ..seed.destinations import BY_ID_DEST, DESTINATIONS
from ..seed.generator import PROFILES
from . import besttime
from . import crowd_model as cm
from . import events as events_svc

log = logging.getLogger(__name__)

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

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "crowd_real_v1.json"
MODEL_NOTE = (
    "Forecast from official pilgrim counts (Uttarakhand Tourism, the State Emergency Operations Centre and news reports"
    " of official figures). Real data; daily values between reports are estimated. Not a guarantee; plan with care."
)
CONF_ESTIMATE = "low"  # the synthetic-occupancy estimate is never more than a rough guide
BASIS_WORDS = {
    "model": "forecast from recent official counts",
    "seasonal_baseline": "last season's level (no recent official count)",
    "reported": "official count",
}
_MODEL: dict = {"loaded": False, "bundle": None}

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


def model_bundle() -> cm.Bundle | None:
    """The real-data crowd model, loaded once; None (estimate only) if the file is missing or invalid."""
    with _LOCK:
        if not _MODEL["loaded"]:
            try:
                _MODEL["bundle"] = cm.Bundle.load(MODEL_PATH)
            except Exception as e:  # noqa: BLE001 - a broken bundle must never take the portal down
                log.warning("crowd model unavailable (%s): using the estimate only", type(e).__name__)
                _MODEL["bundle"] = None
            _MODEL["loaded"] = True
        return _MODEL["bundle"]


def set_model(bundle: cm.Bundle | None) -> None:
    """Tests: replace the loaded model (None = estimate only)."""
    with _LOCK:
        _MODEL.update(loaded=True, bundle=bundle)


def reset_model() -> None:
    with _LOCK:
        _MODEL.update(loaded=False, bundle=None)


def model_covers(dest_id: str) -> bool:
    b = model_bundle()
    return bool(b and dest_id in b.dests)


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
        self._wx: dict = {}

    def weather(self, dest_id: str) -> dict:
        """{date: (precip_mm, snow_cm, max_c)} from the weather cache only (never calls Open-Meteo)."""
        if dest_id not in self._wx:
            doc = mongo.db().weather_cache.find_one({"destination_id": dest_id}) or {}
            days = (doc.get("data") or {}).get("daily") or [] if doc.get("ok") else []
            out = {}
            for d in days:
                vals = (d.get("precip_mm"), d.get("snow_cm"), d.get("max_c"))
                if d.get("date") and all(v is not None for v in vals):
                    out[d["date"]] = vals
            self._wx[dest_id] = out
        return self._wx[dest_id]

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
    est = estimate_day(ctx, dest_id, day)
    b = model_bundle()
    if not b or dest_id not in b.dests:
        return est
    try:
        r = cm.forecast_day(b, dest_id, day, weather=ctx.weather(dest_id))
    except ValueError as e:  # guardrail: invalid input never reaches the page
        log.warning("crowd model refused %s %s: %s", dest_id, day, e)
        return est
    if r["status"] == "closed":
        return {
            **est,
            "index": 0,
            "band": "low",
            "closed": True,
            "source": "real_model",
            "confidence": "high",
            "basis": "closed for the season",
            "pilgrims": 0,
            "range": [0, 0],
            "events": [],
        }
    if r["status"] != "ok":  # no announced season dates, or the model abstained: the rough estimate instead
        return {**est, "confidence": CONF_ESTIMATE, "model_status": r["status"]}
    out = {
        **est,
        "index": r["index"],
        "band": r["band"],
        "source": "real_model",
        "confidence": r["confidence"],
        "basis": BASIS_WORDS.get(r["basis"], r["basis"]),
        "pilgrims": r["pilgrims"],
        "range": [r["low"], r["high"]],
    }
    if r["band"] == "very_high":
        out["reason"] = cm.reason(b, dest_id, day)
    return out


def estimate_day(ctx: Context, dest_id: str, day: date) -> dict:
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
        "source": "estimate",
        "confidence": CONF_ESTIMATE,
    }


def usual_by_month(ctx: Context, dest_id: str) -> list[dict]:
    b = model_bundle()
    if b and dest_id in b.dests:
        return _usual_real(b, dest_id)
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


def _usual_real(b: cm.Bundle, dest_id: str) -> list[dict]:
    """Month by month from the official daily series (every real season); a month never open = 0 (closed)."""
    by_month: dict[int, list[int]] = defaultdict(list)
    for d, v in b.ctx.series[dest_id].items():
        by_month[d.month].append(cm.band_of(b, dest_id, v)[1])
    out = []
    for m in range(1, 13):
        vals = by_month.get(m)
        v = round(sum(vals) / len(vals)) if vals else 0
        out.append({"month": m, "index": v, "band": band(v), "closed": not vals})
    return out


def alert_days(look: list[dict]) -> list[dict]:
    """Very busy days in an outlook, each with a plain reason ("usual for opening weeks") and its confidence."""
    return [
        {
            "date": x["date"],
            "index": x["index"],
            "confidence": x.get("confidence", CONF_ESTIMATE),
            "reason": x.get("reason") or ("festival" if x.get("events") else "usual for this time of year"),
            "source": x.get("source", "estimate"),
        }
        for x in look
        if x["index"] >= ALERT_AT and not x.get("closed")
    ]


def outlook(ctx: Context, dest_id: str, start: date, days: int = 14) -> list[dict]:
    return [day_index(ctx, dest_id, start + timedelta(days=i)) for i in range(days)]


def for_destination(dest_id: str, ctx: Context | None = None) -> dict:
    if dest_id not in BY_ID_DEST:
        raise NotFound("Destination not found.")
    ctx = ctx or Context()
    today = mongo.today()
    look = outlook(ctx, dest_id, today, 14)
    peak = max(look, key=lambda x: x["index"])
    b = model_bundle()
    real = bool(b and dest_id in b.dests)
    return {
        "label": "estimate",
        "note": MODEL_NOTE if real else NOTE,
        "source": "real_model" if real else "estimate",
        "model": (
            {
                "version": b.raw.get("version"),
                "trained_on_seasons": b.raw.get("trained_on_seasons"),
                "last_official_count": b.last_observed(dest_id).isoformat() if b.last_observed(dest_id) else None,
            }
            if real
            else None
        ),
        "alerts": alert_days(look),
        "bands": BANDS,
        "today": look[0],
        "outlook": look,
        "outlook_peak": peak,
        "alert": peak["index"] >= ALERT_AT,
        "usual_by_month": usual_by_month(ctx, dest_id),
        "method": (
            "Gradient-boosted model on official pilgrim counts with an 80% range and guardrails (closed season,"
            " capacity cap, last season's level when counts are old or inputs look unusual)."
            if real
            else "0.8 x occupancy% + event (+12/+6/+2) + weekend (+5) + season (+5 peak / -10 closed); ASSUMED weights."
        ),
        # Real typical foot traffic at one well-known venue (BestTime, cached); shown alongside the estimate, never mixed in.
        "foot_traffic": besttime.foot_traffic(dest_id),
    }


def all_destination_ids(district: str | None = None) -> list[str]:
    return [d["id"] for d in DESTINATIONS if not district or d["district"] == district]
