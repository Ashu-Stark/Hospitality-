"""Char Dham crowd forecast (REAL public data) with guardrails. Standard library only.

This file is the single source of the feature code and the predict function. Training
(ml/realdata/crowd/train.py) builds its feature rows with `feature_row`, and the portal runs a
byte-identical copy (portal/hoi_portal/services/crowd_model.py, kept in sync by
`python -m ml.realdata.crowd.train --export-only` and checked by ml/tests/test_crowd_real.py), so
training and serving can never compute features differently.

The bundle (ml/artifacts/crowd_forecast/real_v1/bundle.json) holds the XGBoost trees (trained on
the GPU) as plain JSON, the season dates, the calendar, the recent daily counts, the training
feature ranges and the band edges. No numpy, GPU or XGBoost is needed to predict.

Guardrails, in the order `predict` applies them:
  1. input validation (known destination, real dates, horizon 1..MAX_H, numeric weather in range);
  2. closed season: a day outside the shrine's announced open..close dates is "closed" (0 pilgrims);
     a year with no announced dates is "unknown_season" (the caller uses its own fallback);
  3. missing inputs: no recent counts (stale or absent) -> seasonal baseline, confidence "low";
  4. drift: a feature outside the training range (+ margin) -> seasonal baseline, confidence "low";
  5. clipping: every number is clipped to 0..cap (the destination's capacity cap) and the range is
     ordered low <= point <= high;
  6. width: a very wide 80% range -> confidence "low"; wider still -> abstain (no band shown).
"""

from __future__ import annotations

import json
import math
import struct
from datetime import date, timedelta
from pathlib import Path

MAX_H = 14
WEATHER_MAX_H = 7  # the weather forecast used at serving time covers 7 days (today + 6)
HEAVY_RAIN_MM = 35.0  # ASSUMED road-closure proxy on the Open-Meteo grid (see DATA_CARD.md)
DESTS = ("kedarnath", "badrinath", "gangotri", "yamunotri")
FEATURES = (
    "dest_kedarnath",
    "dest_badrinath",
    "dest_gangotri",
    "dest_yamunotri",
    "h",
    "dos",
    "days_to_close",
    "season_len",
    "dow",
    "is_weekend",
    "is_holiday",
    "is_long_weekend",
    "is_festival",
    "school_vac",
    "w_precip",
    "w_precip_prev1",
    "w_snow",
    "w_tmax",
    "heavy_rain",
    "lag1",
    "lag7",
    "lag_trend",
    "prev7",
    "yoy",
)
# Features that only describe the calendar or weather: never drift-checked (any date is valid).
NO_DRIFT_CHECK = {
    "h",
    "dow",
    "is_weekend",
    "is_holiday",
    "is_long_weekend",
    "is_festival",
    "dest_kedarnath",
    "dest_badrinath",
    "dest_gangotri",
    "dest_yamunotri",
}
BAND_KEYS = ("low", "moderate", "high", "very_high")
BAND_WORDS = {"low": "Quiet", "moderate": "Normal", "high": "Busy", "very_high": "Very busy"}
WEATHER_RANGES = {"precip": (0.0, 500.0), "snow": (0.0, 200.0), "tmax": (-45.0, 45.0)}


def _d(x: str | date) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x))


# ----------------------------------------------------------------------------- context


class Context:
    """Everything feature_row needs: seasons, daily series, calendar, scales.

    seasons: {dest: {year: (open_date, close_date)}}
    series:  {dest: {date: pilgrims}} (in-season daily counts, real or estimated)
    holidays / festivals: sets of dates; school: {date: share of source states on vacation}
    scale:   {dest: mean in-season daily pilgrims in the training seasons}
    """

    def __init__(
        self,
        seasons: dict,
        series: dict,
        holidays: set,
        festivals: set,
        school: dict,
        scale: dict,
        weather: dict | None = None,
    ):
        self.seasons = seasons
        self.series = series
        self.holidays = holidays
        self.festivals = festivals
        self.school = school
        self.scale = scale
        self.weather = weather or {}  # {dest: {date: (precip, snow, tmax)}}

    def season_of(self, dest: str, day: date) -> tuple[date, date] | None:
        s = self.seasons.get(dest, {}).get(day.year)
        return s if s and s[0] <= day <= s[1] else None

    def off_day(self, day: date) -> bool:
        return day.weekday() >= 5 or day in self.holidays

    def long_weekend(self, day: date) -> bool:
        """Day sits in a run of >= 3 consecutive weekend / gazetted-holiday days."""
        if not self.off_day(day):
            return False
        n, k = 1, day - timedelta(days=1)
        while self.off_day(k):
            n, k = n + 1, k - timedelta(days=1)
        k = day + timedelta(days=1)
        while self.off_day(k):
            n, k = n + 1, k + timedelta(days=1)
        return n >= 3


def _mean(vals: list) -> float | None:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def _window(series: dict, days: list[date], need: int) -> float | None:
    vals = [series[d] for d in days if d in series]
    return sum(vals) / len(vals) if len(vals) >= need else None


def feature_row(ctx: Context, dest: str, day: date, as_of: date, weather: dict | None = None) -> dict:
    """Features for pilgrims at `dest` on `day`, using only counts up to `as_of` (inclusive).

    `weather` maps date -> (precip_mm, snow_cm, tmax_c) for the days a forecast exists; when it is
    None the context's weather is used (training uses the archive). Weather is only used for
    horizons <= WEATHER_MAX_H, the reach of the serving-time forecast.
    """
    season = ctx.season_of(dest, day)
    if season is None:
        raise ValueError(f"{dest} is closed on {day}")
    op, cl = season
    h = (day - as_of).days
    scale = ctx.scale[dest]
    s = ctx.series.get(dest, {})
    row = {f"dest_{k}": float(dest == k) for k in DESTS}
    row.update(
        h=float(h),
        dos=float((day - op).days),
        days_to_close=float((cl - day).days),
        season_len=float((cl - op).days),
        dow=float(day.weekday()),
        is_weekend=float(day.weekday() >= 5),
        is_holiday=float(day in ctx.holidays),
        is_long_weekend=float(ctx.long_weekend(day)),
        is_festival=float(day in ctx.festivals),
        school_vac=float(ctx.school.get(day, 0.0)),
    )
    w = weather if weather is not None else ctx.weather.get(dest, {})
    today_w = w.get(day) if h <= WEATHER_MAX_H else None
    prev_w = w.get(day - timedelta(days=1)) if h <= WEATHER_MAX_H else None
    nan = float("nan")
    row["w_precip"] = today_w[0] if today_w else nan
    row["w_snow"] = today_w[1] if today_w else nan
    row["w_tmax"] = today_w[2] if today_w else nan
    row["w_precip_prev1"] = prev_w[0] if prev_w else nan
    if today_w:
        rain_prev = prev_w[0] if prev_w else 0.0
        row["heavy_rain"] = float(today_w[0] >= HEAVY_RAIN_MM or rain_prev >= HEAVY_RAIN_MM)
    else:
        row["heavy_rain"] = nan
    # Lags: counts this season up to as_of (never after it).
    last7 = [as_of - timedelta(days=i) for i in range(7) if as_of - timedelta(days=i) >= op]
    prev7d = [as_of - timedelta(days=i) for i in range(7, 14) if as_of - timedelta(days=i) >= op]
    lag1 = s.get(as_of) if as_of >= op else None
    lag7 = _window(s, last7, 3)
    lag_prev = _window(s, prev7d, 3)
    row["lag1"] = lag1 / scale if lag1 is not None else nan
    row["lag7"] = lag7 / scale if lag7 is not None else nan
    row["lag_trend"] = (lag7 + 1.0) / (lag_prev + 1.0) if lag7 is not None and lag_prev is not None else nan
    # Previous season, aligned by day of season.
    prev = ctx.seasons.get(dest, {}).get(day.year - 1)
    p7 = py = None
    if prev:
        pop = prev[0]
        dos = (day - op).days
        p7 = _window(s, [pop + timedelta(days=dos + k) for k in range(-3, 4)], 3)
        if lag7 is not None and as_of >= op:
            dos_o = (as_of - op).days
            py = _window(s, [pop + timedelta(days=dos_o - k) for k in range(7)], 3)
    row["prev7"] = p7 / scale if p7 is not None else nan
    row["yoy"] = (lag7 + 1.0) / (py + 1.0) if lag7 is not None and py is not None else nan
    return row


def seasonal_baseline(ctx: Context, dest: str, day: date) -> float | None:
    """Previous season's 7-day mean around the same day of season; when last season was shorter
    and has no such day, the same number of days before closing instead (None if unknown)."""
    season = ctx.season_of(dest, day)
    prev = ctx.seasons.get(dest, {}).get(day.year - 1)
    if season is None or prev is None:
        return None
    s = ctx.series.get(dest, {})
    dos = (day - season[0]).days
    by_open = _window(s, [prev[0] + timedelta(days=dos + k) for k in range(-3, 4)], 3)
    if by_open is not None:
        return by_open
    to_close = (season[1] - day).days
    return _window(s, [prev[1] - timedelta(days=to_close + k) for k in range(-3, 4)], 3)


# ----------------------------------------------------------------------------- trees


def _f32(v: float) -> float:
    """Round to float32, as XGBoost does with its inputs (thresholds are float32 already)."""
    try:
        return struct.unpack("f", struct.pack("f", v))[0]
    except OverflowError:
        return math.copysign(math.inf, v)


def _tree_value(node, x: list[float]) -> float:
    """Walk one compact XGBoost tree: [feat, thr, default_left, left, right] or a leaf value.
    x < thr goes left; a missing value (NaN) goes the split's default side."""
    while isinstance(node, list):
        feat, thr, default_left, left, right = node
        v = x[feat]
        if math.isnan(v):
            node = left if default_left else right
        else:
            node = left if _f32(v) < thr else right
    return float(node)


def tree_predict(model: dict, x: list[float]) -> float:
    """Base margin + the sum of the leaves (identity link: these are regression models)."""
    return model["base"] + sum(_tree_value(t, x) for t in model["trees"])


# ----------------------------------------------------------------------------- bundle


class Bundle:
    """The exported model: trees, context data, band edges, drift ranges and guard thresholds."""

    def __init__(self, raw: dict):
        self.raw = raw
        self.models = raw["models"]
        self.features = tuple(raw["feature_names"])
        if self.features != FEATURES:
            raise ValueError("bundle features do not match this code")
        self.dests = raw["destinations"]
        self.guard = raw["guard"]
        self.ranges = raw["feature_ranges"]
        cal = raw["calendar"]
        seasons = {k: {int(y): (_d(v[0]), _d(v[1])) for y, v in d["seasons"].items()} for k, d in self.dests.items()}
        series = {k: {_d(dt): float(c) for dt, c in d["series"].items()} for k, d in self.dests.items()}
        self.ctx = Context(
            seasons,
            series,
            {_d(x) for x in cal["holidays"]},
            {_d(x) for x in cal["festivals"]},
            {_d(k): float(v) for k, v in cal["school_vacation_share"].items()},
            {k: float(d["scale"]) for k, d in self.dests.items()},
        )

    @classmethod
    def load(cls, path: str | Path) -> Bundle:
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def last_observed(self, dest: str) -> date | None:
        s = self.ctx.series.get(dest)
        return max(s) if s else None


def band_of(b: Bundle, dest: str, pilgrims: float) -> tuple[str, int]:
    """Band and a 0-100 index: piecewise linear through the destination's band edges.

    Edges are the 25th / 60th / 85th percentiles of in-season daily pilgrims in the training
    seasons (ASSUMED cut points) mapped to the portal's index cut points 40 / 65 / 85; the cap
    maps to 100.
    """
    d = b.dests[dest]
    xs = [0.0, *d["band_edges"], float(d["cap"])]
    ys = [0.0, 40.0, 65.0, 85.0, 100.0]
    v = min(max(pilgrims, 0.0), xs[-1])
    for i in range(1, len(xs)):
        if v <= xs[i]:
            span = xs[i] - xs[i - 1]
            idx = ys[i - 1] + (ys[i] - ys[i - 1]) * ((v - xs[i - 1]) / span if span > 0 else 1.0)
            break
    else:
        idx = 100.0
    i = int(round(idx))
    key = "very_high" if i >= 85 else "high" if i >= 65 else "moderate" if i >= 40 else "low"
    return key, i


def _clean_weather(weather: dict | None) -> tuple[dict | None, list[str]]:
    if not weather:
        return None, []
    out, notes = {}, []
    for k, v in weather.items():
        try:
            day = _d(k)
            vals = tuple(float(x) for x in v)
            if len(vals) != 3 or any(math.isnan(x) for x in vals):
                raise ValueError
        except (TypeError, ValueError):
            notes.append(f"weather for {k} ignored (not three numbers)")
            continue
        names = ("precip", "snow", "tmax")
        if all(WEATHER_RANGES[n][0] <= x <= WEATHER_RANGES[n][1] for n, x in zip(names, vals, strict=True)):
            out[day] = vals
        else:
            notes.append(f"weather for {k} ignored (outside physical range)")
    return out, notes


def _drift(b: Bundle, row: dict) -> list[str]:
    bad = []
    for f in FEATURES:
        if f in NO_DRIFT_CHECK:
            continue
        v = row[f]
        if v is None or math.isnan(v):
            continue
        lo, hi = b.ranges[f]
        margin = b.guard["drift_margin"] * max(hi - lo, 1e-9)
        if v < lo - margin or v > hi + margin:
            bad.append(f)
    return bad


def _with_recent(b: Bundle, dest: str, recent: dict) -> Bundle:
    """A shallow copy of the bundle whose series for `dest` includes caller-supplied counts."""
    cap = float(b.dests[dest]["cap"])
    clean = {}
    for k, v in recent.items():
        try:
            day, val = _d(k), float(v)
        except (TypeError, ValueError):
            raise ValueError(f"recent count for {k!r} is not a date and a number") from None
        if math.isnan(val) or val < 0 or val > 2 * cap:
            raise ValueError(f"recent count {val} on {day} is outside 0..{2 * cap:.0f}")
        clean[day] = val
    nb = Bundle.__new__(Bundle)
    nb.__dict__.update(b.__dict__)
    series = dict(b.ctx.series)
    series[dest] = {**series.get(dest, {}), **clean}
    c = b.ctx
    nb.ctx = Context(c.seasons, series, c.holidays, c.festivals, c.school, c.scale, c.weather)
    return nb


def predict(
    b: Bundle,
    dest: str,
    day: str | date,
    as_of: str | date | None = None,
    weather: dict | None = None,
    recent: dict | None = None,
) -> dict:
    """Pilgrims expected at `dest` on `day` with an 80% range, band, index and confidence.

    as_of: last day whose counts may be used (default: the latest day in the bundle's series).
    weather: optional {date: (precip_mm, snow_cm, tmax_c)} forecast for the target days.
    recent: optional {date: pilgrims} official counts newer than the bundle (validated).
    Raises ValueError for invalid input (unknown destination, bad dates or counts, horizon
    outside 1..MAX_H).
    """
    if dest not in b.dests:
        raise ValueError(f"unknown destination {dest!r}")
    if recent:
        b = _with_recent(b, dest, recent)
    try:
        day = _d(day)
        as_of = _d(as_of) if as_of is not None else b.last_observed(dest)
    except ValueError as e:
        raise ValueError(f"invalid date: {e}") from None
    if as_of is None:
        raise ValueError("no as_of date and no observed counts in the bundle")
    h = (day - as_of).days
    if not 1 <= h <= MAX_H:
        raise ValueError(f"horizon {h} days is outside 1..{MAX_H}")
    out = {
        "destination": dest,
        "date": day.isoformat(),
        "as_of": as_of.isoformat(),
        "horizon": h,
        "real_data": True,
        "notes": [],
    }
    if not b.ctx.seasons.get(dest, {}).get(day.year):
        return {
            **out,
            "status": "unknown_season",
            "notes": ["no announced opening dates for this year"],
        }
    if b.ctx.season_of(dest, day) is None:
        return {
            **out,
            "status": "closed",
            "pilgrims": 0,
            "low": 0,
            "high": 0,
            "band": None,
            "index": 0,
            "confidence": "high",
            "basis": "closed_season",
        }
    weather, wnotes = _clean_weather(weather)
    out["notes"] += wnotes
    cap = float(b.dests[dest]["cap"])
    scale = b.ctx.scale[dest]
    row = feature_row(b.ctx, dest, day, as_of, weather=weather if weather is not None else {})
    op = b.ctx.season_of(dest, day)[0]
    started = (as_of - op).days >= b.guard["lag_grace_days"]
    missing_lags = started and math.isnan(row["lag7"])
    drift = _drift(b, row)
    if missing_lags or drift:
        base = seasonal_baseline(b.ctx, dest, day)
        if base is None:
            return {
                **out,
                "status": "abstain",
                "band": None,
                "confidence": "none",
                "basis": "no_baseline",
                "notes": out["notes"] + ["no recent counts and no last season"],
            }
        p = min(max(base, 0.0), cap)
        lo, hi = p * b.guard["fallback_low"], min(p * b.guard["fallback_high"], cap)
        why = "recent counts missing" if missing_lags else "inputs outside training range: " + ", ".join(drift)
        key, idx = band_of(b, dest, p)
        return {
            **out,
            "status": "ok",
            "pilgrims": round(p),
            "low": round(lo),
            "high": round(hi),
            "band": key,
            "index": idx,
            "confidence": "low",
            "basis": "seasonal_baseline",
            "notes": out["notes"] + [why],
        }
    x = [row[f] for f in FEATURES]
    p, q10, q90 = (tree_predict(b.models[k], x) for k in ("point", "q10", "q90"))
    cq = float(b.raw.get("conformal_q", 0.0))  # split-conformal widening (scaled units)
    lo, hi = (min(q10, q90) - cq) * scale, (max(q10, q90) + cq) * scale
    p = min(max(p * scale, lo), hi)  # quantile models can cross: keep low <= point <= high
    p, lo, hi = (min(max(v, 0.0), cap) for v in (p, lo, hi))
    width = (hi - lo) / max(p, b.guard["width_floor"])
    if width > b.guard["abstain_width"]:
        return {
            **out,
            "status": "abstain",
            "pilgrims": round(p),
            "low": round(lo),
            "high": round(hi),
            "band": None,
            "confidence": "none",
            "basis": "model",
            "notes": out["notes"] + ["range too wide to call"],
        }
    conf = "high" if width <= b.guard["high_width"] else "medium" if width <= b.guard["low_width"] else "low"
    key, idx = band_of(b, dest, p)
    return {
        **out,
        "status": "ok",
        "pilgrims": round(p),
        "low": round(lo),
        "high": round(hi),
        "band": key,
        "index": idx,
        "confidence": conf,
        "basis": "model",
    }


def forecast_day(b: Bundle, dest: str, day: str | date, weather: dict | None = None) -> dict:
    """What a page shows for one day: the model within MAX_H days of the last real count, the
    seasonal baseline (low confidence) further out, and closed / unknown outside the season."""
    day = _d(day)
    as_of = b.last_observed(dest)
    if as_of is not None and 1 <= (day - as_of).days <= MAX_H:
        return predict(b, dest, day, as_of, weather=weather)
    out = {"destination": dest, "date": day.isoformat(), "real_data": True, "notes": []}
    if not b.ctx.seasons.get(dest, {}).get(day.year):
        return {**out, "status": "unknown_season"}
    if b.ctx.season_of(dest, day) is None:
        return {
            **out,
            "status": "closed",
            "pilgrims": 0,
            "low": 0,
            "high": 0,
            "band": None,
            "index": 0,
            "confidence": "high",
            "basis": "closed_season",
        }
    if as_of is not None and day <= as_of:  # a day we hold a real (or spread) count for
        v = b.ctx.series[dest].get(day)
        if v is not None:
            key, idx = band_of(b, dest, v)
            return {
                **out,
                "status": "ok",
                "pilgrims": round(v),
                "low": round(v),
                "high": round(v),
                "band": key,
                "index": idx,
                "confidence": "high",
                "basis": "reported",
            }
    base = seasonal_baseline(b.ctx, dest, day)
    if base is None:
        return {
            **out,
            "status": "abstain",
            "band": None,
            "confidence": "none",
            "basis": "no_baseline",
        }
    cap = float(b.dests[dest]["cap"])
    p = min(max(base, 0.0), cap)
    key, idx = band_of(b, dest, p)
    return {
        **out,
        "status": "ok",
        "pilgrims": round(p),
        "low": round(p * b.guard["fallback_low"]),
        "high": round(min(p * b.guard["fallback_high"], cap)),
        "band": key,
        "index": idx,
        "confidence": "low",
        "basis": "seasonal_baseline",
        "notes": ["more than two weeks after the last official count: last season's level"],
    }


def reason(b: Bundle, dest: str, day: str | date) -> str:
    """Plain words for why a day is busy (calendar only, never a claim about the model)."""
    day = _d(day)
    s = b.ctx.season_of(dest, day)
    if s and (day - s[0]).days < 14:
        return "usual for opening weeks"
    if s and (s[1] - day).days < 7:
        return "last days before closing"
    if b.ctx.long_weekend(day):
        return "long weekend"
    if day in b.ctx.holidays or day in b.ctx.festivals:
        return "holiday"
    if b.ctx.school.get(day, 0.0) >= 0.5:
        return "school holidays"
    return "usual for this time of season"
