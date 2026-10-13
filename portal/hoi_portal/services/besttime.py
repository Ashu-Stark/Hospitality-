"""Foot-traffic forecasts from BestTime (besttime.app), fetched once per venue and cached in `crowd_forecasts`.

* `refresh()` (run by `python -m hoi_portal.scripts.besttime_refresh`, never by a web request) creates a forecast per
  venue in seed/besttime_venues.py with POST /api/v1/forecasts. It skips venues fetched less than 7 days ago and venues
  BestTime could not find (that result is stored too, so credits are not spent again; `retry_not_found` overrides).
* `foot_traffic(dest_id)` reads the cache only (no network) and returns the block shown on destination pages, or None.

BestTime's `day_raw` holds 24 values from 6 am to 5 am the next morning (0-100, relative to the venue's busiest hour;
0 usually means closed). We store per-day clock-hour arrays (index 0 = midnight): hours 0-5 of a day come from the
previous day's 4-5 am tail. The raw API response is never stored (it echoes the private key).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import httpx

from .. import config, mongo
from ..seed.besttime_venues import BY_KEY, VENUES

log = logging.getLogger("hoi.portal.besttime")
FORECAST_URL = "https://besttime.app/api/v1/forecasts"
KEYS_URL = "https://besttime.app/api/v1/keys/"
TIMEOUT_S = 60.0  # a new forecast can take a while on BestTime's side
IST = timezone(timedelta(hours=5, minutes=30))
SOURCE = "BestTime"
NOTE = "Forecast of typical foot traffic from BestTime; not a headcount"
CREDIT = "Foot-traffic forecast: BestTime (besttime.app)"
METHOD = (
    "Best time = the 2 consecutive open hours with the lowest forecast today. Peak hours: open hours at 90% or more of "
    "today's highest value. Quiet hours: open hours within 5 points of today's lowest open value."
)
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class KeyRejected(RuntimeError):
    """BestTime refused the key or the credits ran out: stop the run."""


def http_forecast(venue_name: str, venue_address: str, key: str) -> tuple[int, dict]:
    r = httpx.post(
        FORECAST_URL, params={"api_key_private": key, "venue_name": venue_name, "venue_address": venue_address}, timeout=TIMEOUT_S
    )
    try:
        body = r.json()
    except ValueError:
        body = {}
    return r.status_code, body if isinstance(body, dict) else {}


def http_key_info(key: str) -> dict:
    r = httpx.get(KEYS_URL + key, timeout=15.0)
    r.raise_for_status()
    return r.json()


_FETCH: Callable[[str, str, str], tuple[int, dict]] = http_forecast
_KEY_INFO: Callable[[str], dict] = http_key_info


def set_fetcher(fetch: Callable | None = None, key_info: Callable | None = None) -> None:
    """Inject fakes (tests). None restores the real HTTP calls."""
    global _FETCH, _KEY_INFO
    _FETCH = fetch or http_forecast
    _KEY_INFO = key_info or http_key_info


def credits() -> dict | None:
    """Remaining credits ({"forecast": n, "query": n}) or None when there is no key or the call fails."""
    key = config.settings.besttime_key
    if not key:
        return None
    try:
        j = _KEY_INFO(key)
        return {"forecast": j.get("credits_forecast"), "query": j.get("credits_query")}
    except Exception as e:  # noqa: BLE001
        log.warning("BestTime key info failed: %s", type(e).__name__)
        return None


# ------------------------------------------------------------------ parsing
def _num(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def parse(body: dict) -> dict:
    """The parts we keep from a successful forecast. ValueError if the shape is not what we expect."""
    days: dict[int, dict] = {}
    for a in body.get("analysis") or []:
        info = a.get("day_info") or {}
        raw = a.get("day_raw") or []
        di = info.get("day_int")
        if not isinstance(di, int) or not 0 <= di <= 6 or len(raw) != 24:
            continue
        days[di] = {"day_int": di, "day_text": DAYS[di], "day_mean": _num(info.get("day_mean")), "raw": [_num(v) for v in raw]}
    if len(days) != 7:
        raise ValueError("forecast does not have 7 days of 24 hourly values")
    week = [days[i] for i in range(7)]
    by_hour = []
    for i in range(7):
        prev = week[(i - 1) % 7]["raw"]
        by_hour.append(prev[18:24] + week[i]["raw"][0:18])  # 0-5 am from the previous day's tail, then 6 am-11 pm
    vi = body.get("venue_info") or {}
    return {
        "week": [{k: d[k] for k in ("day_int", "day_text", "day_mean")} for d in week],
        "by_hour": by_hour,
        "matched_name": str(vi.get("venue_name") or "")[:200],
        "matched_address": str(vi.get("venue_address") or "")[:300],
        "venue_id": str(vi.get("venue_id") or "")[:120],
        "lat": vi.get("venue_lat"),
        "lon": vi.get("venue_lon") if vi.get("venue_lon") is not None else vi.get("venue_lng"),
        "timezone": vi.get("venue_timezone"),
    }


def _message(body: dict, key: str) -> str:
    msg = str(body.get("message") or body.get("status") or "not found")
    return msg.replace(key, "<key>")[:300] if key else msg[:300]


# ------------------------------------------------------------------ refresh (the only place that spends credits)
def refresh(
    venues: list[dict] | None = None,
    *,
    force: bool = False,
    retry_not_found: bool = False,
    dry_run: bool = False,
    say: Callable[[str], None] = lambda s: None,
) -> dict:
    """Create/update forecasts. Returns counts: fetched, not_found, skipped, errors (+ planned for a dry run)."""
    key = config.settings.besttime_key
    if not key:
        raise KeyRejected("BESTTIME_API_KEY_PRIVATE is not set")
    col = mongo.db().crowd_forecasts
    now = mongo.now()
    fresh_after = now - timedelta(days=config.settings.external_cache_days)
    out = {"fetched": 0, "not_found": 0, "skipped": 0, "errors": 0, "planned": 0}
    for v in venues if venues is not None else VENUES:
        old = col.find_one({"key": v["key"]})
        if old and not force:
            if old.get("status") == "ok" and mongo.aware(old["fetched_at"]) > fresh_after:
                out["skipped"] += 1
                say(f"skip  {v['key']}: fetched {mongo.iso(old['fetched_at'])}")
                continue
            if old.get("status") == "not_found" and not retry_not_found:
                out["skipped"] += 1
                say(f"skip  {v['key']}: BestTime did not find it earlier ({old.get('message')})")
                continue
        if dry_run:
            out["planned"] += 1
            say(f"would fetch {v['key']}: {v['venue_name']} / {v['venue_address']}")
            continue
        base = {k: v[k] for k in ("key", "destination_id", "venue_name", "venue_address", "rank")}
        try:
            status, body = _FETCH(v["venue_name"], v["venue_address"], key)
        except Exception as e:  # noqa: BLE001 - network: try again on the next run
            out["errors"] += 1
            say(f"error {v['key']}: {type(e).__name__}")
            continue
        if status in (401, 403) or status == 429:
            raise KeyRejected(f"BestTime answered HTTP {status} ({_message(body, key)}); stopping")
        if status >= 500:
            out["errors"] += 1
            say(f"error {v['key']}: HTTP {status}")
            continue
        if status == 200 and body.get("status") == "OK":
            try:
                doc = {**base, "status": "ok", **parse(body), "message": None, "fetched_at": now}
            except ValueError as e:
                out["errors"] += 1
                say(f"error {v['key']}: {e}")
                continue
            col.update_one({"key": v["key"]}, {"$set": doc}, upsert=True)
            out["fetched"] += 1
            say(f"ok    {v['key']}: matched '{doc['matched_name']}'")
        else:
            msg = _message(body, key)
            if old and old.get("status") == "ok":  # keep a good forecast rather than replacing it with "not found"
                col.update_one({"key": v["key"]}, {"$set": {"last_refresh_error": msg, "last_refresh_at": now}})
            else:
                col.update_one({"key": v["key"]}, {"$set": {**base, "status": "not_found", "message": msg, "fetched_at": now}}, upsert=True)
            out["not_found"] += 1
            say(f"miss  {v['key']}: {msg}")
    return out


# ------------------------------------------------------------------ read side (cache only)
def hour_label(h: int) -> str:
    h %= 24
    return f"{12 if h % 12 == 0 else h % 12} {'am' if h < 12 else 'pm'}"


def window_label(start: int, end: int) -> str:
    a, b = hour_label(start), hour_label(end)
    if a.split()[1] == b.split()[1]:
        return f"{a.split()[0]}–{b}"
    return f"{a}–{b}"


def summarize(by_hour: list[int]) -> dict:
    open_h = [h for h in range(24) if by_hour[h] > 0]
    if not open_h:
        return {"peak_hours": [], "quiet_hours": [], "best_window": None}
    top = max(by_hour[h] for h in open_h)
    low = min(by_hour[h] for h in open_h)
    pairs = [(by_hour[h] + by_hour[h + 1], h) for h in range(23) if by_hour[h] > 0 and by_hour[h + 1] > 0]
    best = None
    if pairs:
        _, s = min(pairs)
        best = {"start_hour": s, "end_hour": s + 2, "label": window_label(s, s + 2)}
    return {
        "peak_hours": [h for h in open_h if by_hour[h] >= 0.9 * top],
        "quiet_hours": [h for h in open_h if by_hour[h] <= low + 5],
        "best_window": best,
    }


def foot_traffic(dest_id: str, now: datetime | None = None) -> dict | None:
    """The BestTime block for a destination (first venue found, in list order), or None. Never calls BestTime."""
    try:
        docs = list(mongo.db().crowd_forecasts.find({"destination_id": dest_id, "status": "ok"}, {"_id": 0}))
    except Exception:  # noqa: BLE001 - optional enrichment
        return None
    docs = [d for d in docs if d.get("key") in BY_KEY and len(d.get("by_hour") or []) == 7]
    if not docs:
        return None
    d = min(docs, key=lambda x: x.get("rank", 99))
    today = (now or datetime.now(UTC)).astimezone(IST)
    di = today.weekday()  # Monday = 0, as BestTime's day_int
    by_hour = [int(x) for x in d["by_hour"][di]]
    busiest = max(d["week"], key=lambda w: w["day_mean"])
    return {
        "source": SOURCE,
        "venue_name": d.get("matched_name") or d["venue_name"],
        "venue_address": d.get("matched_address") or d["venue_address"],
        "day": DAYS[di],
        "today_by_hour": by_hour,
        **summarize(by_hour),
        "busiest_day": busiest["day_text"],
        "fetched_at": mongo.iso(d["fetched_at"]),
        "note": NOTE,
        "credit": CREDIT,
        "method": METHOD,
        "timezone": "Asia/Kolkata",
    }
