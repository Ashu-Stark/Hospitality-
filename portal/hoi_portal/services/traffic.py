"""Road traffic PREDICTION per destination: an hourly congestion index 0-100 + band for the next 72 hours.

Predicted, not measured; for planning. A transparent weighted model; every weight, threshold and profile is ASSUMED
and lives in hoi_portal/traffic.yaml. For each hour (India time):

    index = time-of-day profile (corridor type)            + weekend / holiday windows
          (day-level demand terms below are x activity = profile[h] / max(profile); weather x (0.5 + 0.5 x activity))
          + season (destination seasonality x weight)      + Char Dham yatra months (hill pilgrim corridors)
          + Kanwar Yatra (Haridwar corridor)               + festivals / events (crowd impact)
          + our crowd estimate x weight                    + BestTime foot traffic at that hour x weight
          + rain / snow forecast (Open-Meteo, x1.5 on hill corridors) + landslide risk (heavy monsoon rain, hills)
          + posted road advisories (caution: +; closed: at least the closed floor)
          + live provider nowcast for the next 1-3 hours only (incidents; flow blended in)
          + calibration correction (only after enough live observations; scripts/traffic_calibrate.py)
    clamped to 0..100.

Every term except the live flow blend and the calibration correction only ADDS, so rain, snow, festivals and weekends
can never lower the index. Delays are bands ("likely slow in places"), never minutes, speeds or distances for a road.
The model starts expert-weighted and improves only as live observations accumulate (`traffic_observations`).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from .. import miniyaml, mongo
from ..errors import Invalid, NotFound
from ..seed.destinations import BY_ID_DEST
from ..seed.generator import PROFILES
from . import crowd, traffic_live
from . import events as events_svc

log = logging.getLogger("hoi.portal.traffic")
CONFIG_PATH = Path(__file__).resolve().parent.parent / "traffic.yaml"
CFG: dict = miniyaml.load(CONFIG_PATH)
IST = timezone(timedelta(hours=5, minutes=30))
BAND_LABEL = {"free": "Free-flowing", "moderate": "Moderate", "heavy": "Heavy", "severe": "Severe"}
DAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_CAL_CACHE: dict = {"at": 0.0, "gen": -1, "docs": {}}


def reload_config(path: Path = CONFIG_PATH) -> dict:
    """Re-read traffic.yaml (tests change weights through this)."""
    global CFG
    CFG = miniyaml.load(path)
    return CFG


def band(index: float) -> str:
    b = CFG["bands"]
    return "free" if index < b["free"] else "moderate" if index < b["moderate"] else "heavy" if index < b["heavy"] else "severe"


def corridor(dest: dict) -> str:
    return CFG["corridor_of_profile"].get(dest["profile"], "town")


def hour_label(h: int) -> str:
    h %= 24
    return f"{12 if h % 12 == 0 else h % 12} {'am' if h < 12 else 'pm'}"


def span_label(start: int, end: int) -> str:
    a, b = hour_label(start), hour_label(end)
    return f"{a.split()[0]}–{b}" if a.split()[1] == b.split()[1] else f"{a}–{b}"


def day_word(d: date, today: date) -> str:
    return "today" if d == today else "tomorrow" if d == today + timedelta(days=1) else d.strftime("%A")


# ------------------------------------------------------------------ inputs (all read once per request)
class Inputs:
    """Everything the model needs for one destination, read once (cache-only for weather / BestTime)."""

    def __init__(self, dest_id: str, ctx: crowd.Context | None = None, live: dict | None = None):
        self.dest = BY_ID_DEST[dest_id]
        self.ctx = ctx or crowd.Context()
        self.corridor = corridor(self.dest)
        self.hill = self.corridor in CFG["hill_corridors"]
        db = mongo.db()
        w = db.weather_cache.find_one({"destination_id": dest_id})
        self.weather = (w or {}).get("data") if w and w.get("ok") else None
        self.rain_by_hour, self.snow_by_hour, self.daily = {}, {}, {}
        if self.weather:
            h = self.weather.get("hourly") or {}
            for t, p, s in zip(h.get("time") or [], h.get("precip_mm") or [], h.get("snow_cm") or []):
                self.rain_by_hour[t[:13]] = p or 0.0
                self.snow_by_hour[t[:13]] = s or 0.0
            for d in self.weather.get("daily") or []:
                self.daily[d["date"]] = d
        ft = [
            x for x in db.crowd_forecasts.find({"destination_id": dest_id, "status": "ok"}, {"_id": 0}) if len(x.get("by_hour") or []) == 7
        ]
        self.foot = min(ft, key=lambda x: x.get("rank", 99)) if ft else None
        now = mongo.now()
        self.advisories = [
            a
            for a in db.advisories.find({"destination_id": dest_id, "kind": "road", "expires_at": {"$gt": now}}, {"_id": 0})
            if a.get("status") in ("caution", "closed")
        ]
        self.kanwar = next((e for e in self.ctx.events if e.get("id") == CFG["yatra"]["kanwar_event_id"]), None)
        self.live = live
        self.calibration = calibration_for(dest_id)
        self._crowd: dict = {}

    def crowd_index(self, day: date) -> int:
        if day not in self._crowd:
            self._crowd[day] = crowd.day_index(self.ctx, self.dest["id"], day)
        return self._crowd[day]["index"]

    def kanwar_on(self, day: date) -> bool:
        e = self.kanwar
        if not e or self.dest["id"] not in CFG["yatra"]["kanwar_destinations"]:
            return False
        if e.get("start_date"):
            return e["start_date"] <= day.isoformat() <= (e.get("end_date") or e["start_date"])
        return day.month in (e.get("months") or [])


# ------------------------------------------------------------------ the model
def hour_terms(inp: Inputs, t: datetime, offset_h: int | None = None) -> tuple[float, list[tuple[str, str, float]], dict]:
    """(index before clamping, [(key, text, contribution)], flags) for the hour starting at t (aware, IST)."""
    c = CFG
    h, day = t.hour, t.date()
    profile = c["hourly_base"][inp.corridor]
    terms: list[tuple[str, str, float]] = [("base", "time of day", float(profile[h]))]
    act = profile[h] / max(profile)  # day-level demand adds most at busy hours, little at night
    flags: dict = {}
    # weekend / holiday windows
    dk = DAY_KEYS[day.weekday()]
    holiday = day.strftime("%m-%d") in c.get("holidays", [])
    wk = c["weekend"].get(inp.corridor, {})
    windows = wk.get("sunday" if holiday else dk) or []
    add = sum(amt for s, e, amt in windows if s <= h < e)
    if add:
        terms.append(
            (
                "weekend",
                "public holiday" if holiday else "weekend" if dk in ("saturday", "sunday") else "Friday-evening arrivals",
                float(add),
            )
        )
    # season and yatra
    prof = PROFILES[inp.dest["profile"]][day.month - 1]
    y = c["yatra"]
    season = c["season_weight"] * prof * act
    if inp.corridor == "hill_pilgrim" and day.month in y["char_dham_months"]:  # one factor: season + yatra boost
        terms.append(("char_dham", "Char Dham yatra season", season + y["char_dham_boost"] * act))
    else:
        terms.append(("season", "peak season" if prof >= 0.8 else "season", season))
    if inp.kanwar_on(day):
        terms.append(("kanwar", "Kanwar Yatra (usual timing)", y["kanwar_boost"] * act))
    evs = [e for e in events_svc.active_on(inp.ctx.events, inp.dest["id"], day) if e.get("id") != y["kanwar_event_id"]]
    if evs:
        best = max(evs, key=lambda e: c["event_boost"].get(e.get("crowd_impact"), 0))
        boost = c["event_boost"].get(best.get("crowd_impact"), 0) * (1.0 if best.get("start_date") else c["event_month_only_share"])
        if boost:
            terms.append(("event", best["name"].replace("SAMPLE: ", ""), boost * act))
    # crowd estimate and BestTime foot traffic
    ci = inp.crowd_index(day)
    terms.append(("crowd", "high crowd estimate" if ci >= 65 else "crowd estimate", c["crowd_weight"] * ci * act))
    if inp.foot:
        v = inp.foot["by_hour"][day.weekday()][h]
        if v:
            terms.append(("foot_traffic", "busy visiting hours (BestTime)", c["foot_traffic_weight"] * v))
    # weather
    w = c["weather"]
    key = t.strftime("%Y-%m-%dT%H")
    dd = inp.daily.get(day.isoformat()) or {}
    rain = inp.rain_by_hour.get(key)
    if rain is None and dd:
        rain = (dd.get("precip_mm") or 0) / 24.0  # no hourly data: spread the day's rain evenly
    snow = inp.snow_by_hour.get(key)
    if snow is None and dd:
        snow = (dd.get("snow_cm") or 0) / 24.0
    mult = (w["hill_multiplier"] if inp.hill else 1.0) * (w["night_share"] + (1 - w["night_share"]) * act)
    if rain:
        terms.append(("rain", "rain", min(1.0, rain / w["rain_mm_h_full"]) * w["rain_boost"] * mult))
    if snow:
        terms.append(("snow", "snow", min(1.0, snow / w["snow_cm_h_full"]) * w["snow_boost"] * mult))
    if inp.hill and day.month in w["monsoon_months"] and (dd.get("precip_mm") or 0) >= w["landslide_daily_mm"]:
        terms.append(("landslide", "landslide risk (heavy monsoon rain)", float(w["landslide_boost"])))
        flags["landslide_risk"] = True
    # posted advisories (active at this hour)
    floor = 0.0
    for a in inp.advisories:
        if mongo.aware(a["expires_at"]) <= t.astimezone(UTC):
            continue
        sample = " (sample alert)" if a.get("sample") else ""
        if a["status"] == "closed":
            floor = max(floor, float(c["advisories"]["closed_floor"]))
            terms.append(("advisory_closed", "road closed (posted alert)" + sample, 0.0))
        else:
            terms.append(("advisory_caution", "caution on the road (posted alert)" + sample, float(c["advisories"]["caution_boost"])))
    # live nowcast (next few hours only)
    nc = c["nowcast"]
    if inp.live and offset_h is not None and 0 <= offset_h < nc["hours"]:
        decay = nc["decay"][offset_h]
        inc = inp.live.get("incidents") or []
        closed = any(i["status"] == "closed" for i in inc)
        jams = sum(1 for i in inc if i["category"] == "jam")
        other = sum(1 for i in inc if i["status"] != "closed" and i["category"] != "jam")
        boost = min(nc["max_boost"], nc["per_jam"] * jams + nc["per_other"] * other) * decay
        src = traffic_live.PROVIDERS.get(inp.live.get("provider"), traffic_live.PROVIDERS["tomtom"]).source
        if boost:
            terms.append(("live", f"live incidents ({src})", boost))
        if closed:
            floor = max(floor, float(nc["closed_floor"]))
            terms.append(("live_closed", f"road closure reported ({src})", 0.0))
        flags["nowcast"] = True
    total = sum(v for _, _, v in terms)
    flow = (inp.live or {}).get("flow") if offset_h is not None and 0 <= offset_h < nc["hours"] else None
    if flow and flow.get("ratio") is not None:
        k = nc["flow_weight"] * nc["decay"][offset_h]
        observed = observed_from_flow(flow)
        total = total * (1 - k) + observed * k
    if inp.calibration:
        bias = bucket_value(inp.calibration.get("bias") or [], h)
        if bias:
            terms.append(("calibration", "correction learned from live observations", bias))
            total += bias
    return max(total, floor), terms, flags


def observed_from_flow(flow: dict) -> float:
    o = CFG["observed_index"]
    if flow.get("road_closed"):
        return float(o["closed"])
    return max(0.0, min(100.0, (1 - float(flow["ratio"])) * o["flow_scale"]))


def observed_index(live: dict) -> float:
    """0-100 'observed' congestion from one live answer (used only to calibrate). ASSUMED conversion."""
    o = CFG["observed_index"]
    inc = live.get("incidents") or []
    if any(i["status"] == "closed" for i in inc):
        return float(o["closed"])
    v = (
        o["base"]
        + o["per_jam"] * sum(1 for i in inc if i["category"] == "jam")
        + o["per_other"] * sum(1 for i in inc if i["category"] != "jam")
    )
    if live.get("flow"):
        v = max(v, observed_from_flow(live["flow"]))
    return float(min(100.0, v))


def bucket_value(values: list, hour: int) -> float:
    for (s, e), v in zip(CFG["calibration"]["buckets"], values):
        if s <= hour < e:
            return float(v or 0.0)
    return 0.0


def calibration_for(dest_id: str) -> dict | None:
    """Fitted correction for a destination (cached in-process for 10 minutes)."""
    c = _CAL_CACHE
    if time.monotonic() - c["at"] > 600 or c["gen"] != mongo.generation:
        try:
            c["docs"] = {d["destination_id"]: d for d in mongo.db().traffic_calibration.find({}, {"_id": 0})}
        except Exception:  # noqa: BLE001
            c["docs"] = {}
        c["at"], c["gen"] = time.monotonic(), mongo.generation
    return c["docs"].get(dest_id)


def invalidate_calibration() -> None:
    _CAL_CACHE["at"] = 0.0


# ------------------------------------------------------------------ outputs
def _factor_text(rows: list[dict], today: date) -> list[dict]:
    """Plain-word top factors over the predicted hours (weather with its time window)."""
    agg: dict[str, dict] = {}
    for r in rows:
        for key, text, v in r["_terms"]:
            if (
                key in ("base", "crowd", "season")
                and not (key == "season" and text == "peak season")
                and not (key == "crowd" and text.startswith("high"))
            ):
                continue
            a = agg.setdefault(key, {"key": key, "text": text, "weight": 0.0, "hours": []})
            a["weight"] = max(a["weight"], v if v else 90.0 if key.endswith("closed") else 0.0)
            a["hours"].append(r["_t"])
    out = []
    for a in sorted(agg.values(), key=lambda x: -x["weight"]):
        text = a["text"]
        if a["key"] in ("rain", "snow"):
            first = a["hours"][0]
            run = [first]
            for t in a["hours"][1:]:
                if t - run[-1] == timedelta(hours=1):
                    run.append(t)
                else:
                    break
            text = f"{text} expected {day_word(first.date(), today)} {span_label(first.hour, (run[-1].hour + 1) % 24)}".replace(
                "today ", ""
            )
        out.append({"key": a["key"], "text": text[0].upper() + text[1:], "weight": round(a["weight"], 1)})
    return out[:4]


def best_window(rows: list[dict], today: date) -> dict | None:
    bt = CFG["best_time"]
    n, (lo, hi) = int(bt["window_hours"]), bt["drive_hours"]
    rows24 = rows[:24]
    best = None
    for i in range(len(rows24) - n + 1):
        win = rows24[i : i + n]
        t0 = win[0]["_t"]
        if t0.hour < lo or t0.hour + n > hi or any(w["_t"].date() != t0.date() for w in win):
            continue
        mean = sum(w["index"] for w in win) / n
        if best is None or mean < best[0]:
            best = (mean, t0)
    if not best:
        return None
    mean, t0 = best
    dw = day_word(t0.date(), today)
    return {
        "start": t0.isoformat(),
        "label": f"{span_label(t0.hour, t0.hour + n)}" + ("" if dw == "today" else f" {dw}"),
        "day": dw,
        "index": round(mean),
        "band": band(mean),
    }


def predict(dest_id: str, hours: int = 72, *, now: datetime | None = None, ctx: crowd.Context | None = None, use_live: bool = True) -> dict:
    if dest_id not in BY_ID_DEST:
        raise NotFound("Destination not found.")
    hmax = int(CFG["horizon_hours_max"])
    if not 1 <= hours <= hmax:
        raise Invalid(f"hours must be between 1 and {hmax}.")
    live_doc, fresh = traffic_live.get(dest_id) if use_live else (None, False)
    inp = Inputs(dest_id, ctx, live_doc)
    t_now = (now or datetime.now(UTC)).astimezone(IST)
    start = t_now.replace(minute=0, second=0, microsecond=0)
    today = start.date()
    rows, flags = [], {}
    for k in range(max(hours, 24)):
        t = start + timedelta(hours=k)
        total, terms, fl = hour_terms(inp, t, k)
        idx = int(round(max(0.0, min(100.0, total))))
        flags.update(fl)
        rows.append(
            {
                "time": t.isoformat(),
                "hour": t.hour,
                "index": idx,
                "band": band(idx),
                "_t": t,
                "_terms": terms,
                "nowcast": bool(fl.get("nowcast")),
            }
        )
    if fresh and live_doc:
        _observe(inp, live_doc, rows[0])
    factors = _factor_text(rows[:24], today)
    cur = rows[0]
    dest = inp.dest
    out = {
        "destination_id": dest_id,
        "destination_name": dest["name"],
        "corridor": {"type": inp.corridor, "label": CFG["corridor_labels"][inp.corridor]},
        "label": CFG["label"],
        "now": {"index": cur["index"], "band": cur["band"], "band_label": BAND_LABEL[cur["band"]], "delay": CFG["delay_text"][cur["band"]]},
        "hours": [{k: r[k] for k in ("time", "hour", "index", "band", "nowcast")} for r in rows[:hours]],
        "best_time": best_window(rows, today),
        "factors": factors,
        "factors_text": " + ".join(f["text"] for f in factors[:3]) or "Usual pattern for the time of day",
        "landslide_risk": bool(flags.get("landslide_risk")),
        "live": traffic_live.shape(dest, live_doc) if live_doc else None,
        "live_providers": traffic_live.provider_status(),
        "model": {
            "version": CFG["version"],
            "calibrated": bool(inp.calibration),
            "observations_used": (inp.calibration or {}).get("n", 0),
            "note": "Expert-weighted (ASSUMED weights in traffic.yaml); corrected only after enough live observations.",
        },
        "bands": {k: BAND_LABEL[k] for k in BAND_LABEL},
        "timezone": "Asia/Kolkata",
        "generated_at": mongo.iso(mongo.now()),
    }
    return out


def summary(dest_id: str, ctx: crowd.Context | None = None) -> dict:
    """Compact block for the destination page: now, next 24 hours, best time, factors, live incidents."""
    p = predict(dest_id, 24, ctx=ctx)
    return {k: p[k] for k in ("label", "corridor", "now", "hours", "best_time", "factors_text", "landslide_risk", "live", "model")}


def predict_day(dest_id: str, day: date, ctx: crowd.Context | None = None) -> dict:
    """Typical level over daylight driving hours on a day (itinerary stops; no live data)."""
    inp = Inputs(dest_id, ctx, None)
    lo, hi = CFG["best_time"]["drive_hours"]
    vals = []
    for h in range(lo, hi):
        t = datetime(day.year, day.month, day.day, h, tzinfo=IST)
        total, _, _ = hour_terms(inp, t, None)
        vals.append(max(0.0, min(100.0, total)))
    v = round(sum(vals) / len(vals))
    return {"date": day.isoformat(), "index": v, "band": band(v), "band_label": BAND_LABEL[band(v)], "label": CFG["label"]}


def _observe(inp: Inputs, live_doc: dict, row: dict) -> None:
    """Store one live observation with the model's features at that hour (the calibration data)."""
    try:
        predicted_raw = sum(v for k, _, v in row["_terms"] if k not in ("live", "live_closed", "calibration"))
        mongo.db().traffic_observations.insert_one(
            {
                "destination_id": inp.dest["id"],
                "corridor": inp.corridor,
                "ts": mongo.now(),
                "hour": row["_t"].hour,
                "weekday": row["_t"].weekday(),
                "provider": live_doc.get("provider"),
                "incidents": len(live_doc.get("incidents") or []),
                "closed": sum(1 for i in live_doc.get("incidents") or [] if i["status"] == "closed"),
                "jams": sum(1 for i in live_doc.get("incidents") or [] if i["category"] == "jam"),
                "flow_ratio": (live_doc.get("flow") or {}).get("ratio"),
                "observed_index": observed_index(live_doc),
                "predicted_index": round(max(0.0, min(100.0, predicted_raw)), 1),
                "features": {k: round(v, 2) for k, _, v in row["_terms"] if k not in ("live", "live_closed", "calibration")},
                "model_version": CFG["version"],
            }
        )
    except Exception as e:  # noqa: BLE001 - never break a page for the learning loop
        log.warning("could not store a traffic observation: %s", type(e).__name__)
