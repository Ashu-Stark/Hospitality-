"""Cancellation interface (loads ml/artifacts/cancellation/real_v1; never trains).

    from ml.realdata.hotel_alerts import api as cancellation
    cancellation.score_bookings([{...}], as_of="2029-12-24")   # -> BookingScores (guarded)
    cancellation.night_adjustment(on_books=20, days_ahead=5, rooms=24)  # -> NightAdjustment

The model was trained on REAL Portuguese hotel bookings (Hotel Booking Demand, CC BY 4.0).
Applying it to another hotel is an ASSUMPTION until it is retrained on that hotel's bookings;
every result says so. Night-level counts use the source chosen on validation per horizon
(the base-rate table at every horizon in real_v1); per-booking probabilities come from the
model and are meant for ranking ("which bookings to reconfirm first").
"""

from __future__ import annotations

import math
from datetime import date
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel

from ml import guardrails as G
from ml.realdata.hotel_alerts import features as F

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "cancellation" / "real_v1"
DEFAULT_HOTEL = "Resort Hotel"  # the closer of the two training hotels to a hill resort
MODEL = "cancellation/real_v1"
NOTE = ("Trained on REAL bookings from two Portuguese hotels (Hotel Booking Demand, CC BY 4.0); "
        "not yet validated on this hotel. Retrain on the hotel's own bookings.")
REQUIRED = ["arrival", "booked_on", "deposit_type", "market_segment"]
DEFAULTS = {"nights": 2, "meal": "BB", "distribution_channel": "Direct",
            "customer_type": "Transient", "reserved_room_type": "A", "is_repeated_guest": 0,
            "previous_cancellations": 0,
            "previous_bookings_not_canceled": 0, "days_in_waiting_list": 0,
            "total_of_special_requests": 0, "has_agent": 0, "has_company": 0}
LIMITS = {"lead_time": (0, 800), "days_to_arrival": (0, 800), "nights": (0, 60),
          "previous_cancellations": (0, 50), "previous_bookings_not_canceled": (0, 100),
          "days_in_waiting_list": (0, 400), "adr": (0, 2000), "total_of_special_requests": (0, 10)}


class BookingRisk(BaseModel):
    booking_ref: str
    arrival: date
    days_to_arrival: int
    p_cancel: float
    source: str  # model / base_rate (guardrail fallback)


class BookingScores(BaseModel):
    as_of: date
    model: str = MODEL
    bookings: list[BookingRisk]
    confidence: str
    checks: list[G.Check]
    fallback_used: bool
    note: str = NOTE
    data_provenance: str = "REAL training data; scored inputs as supplied"


class NightAdjustment(BaseModel):
    on_books: int
    days_ahead: int
    source: str  # base_rate_table / model (per-booking probabilities supplied)
    expected_cancellations: float
    expected_rooms: float
    low: float
    high: float
    note: str = NOTE


@lru_cache(maxsize=2)
def load(artifact_dir: Path = ARTIFACT_DIR) -> tuple[dict, dict | None]:
    return joblib.load(artifact_dir / "model.joblib"), G.load_reference(artifact_dir)


def horizon_key(days_ahead: int) -> str:
    for h in (1, 7, 14, 30):
        if days_ahead <= h:
            return str(h)
    return "30"


def base_rate(days_to_arrival: float, artifact_dir: Path = ARTIFACT_DIR,
              hotel: str = DEFAULT_HOTEL) -> float:
    bundle, _ = load(artifact_dir)
    table = bundle["table"].get(hotel, bundle["table"]["all"])
    return float(table[str(int(F.bucket_of([days_to_arrival])[0]))])


def _frame(bookings: list[dict], as_of: date) -> pd.DataFrame:
    df = pd.DataFrame(bookings).copy()
    for c in REQUIRED:
        if c not in df:
            df[c] = None
    arrival = pd.to_datetime(df["arrival"], errors="coerce")
    booked = pd.to_datetime(df["booked_on"], errors="coerce")
    t = pd.Timestamp(as_of)
    out = pd.DataFrame(index=df.index)
    out["arrival_ts"] = arrival
    out["hotel"] = df.get("hotel", pd.Series(DEFAULT_HOTEL, index=df.index)).fillna(DEFAULT_HOTEL)
    for c, v in DEFAULTS.items():
        out[c] = df[c].fillna(v) if c in df else v
    for c in ("deposit_type", "market_segment"):
        out[c] = df[c]
    out["lead_time"] = (arrival - booked).dt.days
    out["days_to_arrival"] = (arrival - t).dt.days
    out["days_since_booking"] = (t - booked).dt.days
    out["arrival_month"] = arrival.dt.month
    out["arrival_dow"] = arrival.dt.dayofweek
    nights = pd.to_numeric(out["nights"], errors="coerce").fillna(DEFAULTS["nights"])
    # weekend nights as in the dataset: nights that fall on a Saturday or Sunday
    out["stays_in_weekend_nights"] = [
        float(sum((a + pd.Timedelta(days=i)).dayofweek >= 5 for i in range(int(n))))
        if pd.notna(a) else 0.0 for a, n in zip(arrival, nights, strict=True)]
    out["stays_in_week_nights"] = nights - out["stays_in_weekend_nights"]
    out["adr"] = pd.to_numeric(df["adr_eur"], errors="coerce") if "adr_eur" in df else np.nan
    refs = df.get("booking_ref", pd.Series(range(len(df)), index=df.index))
    out["booking_ref"] = refs.astype(str)
    return out


def score_bookings(bookings: list[dict], as_of: date | str,
                   artifact_dir: Path = ARTIFACT_DIR, today: date | None = None) -> BookingScores:
    """Per-booking chance of cancelling or not showing, with guardrails. Each booking needs
    arrival, booked_on, deposit_type and market_segment (training vocabulary, e.g.
    'No Deposit' / 'Online TA'); optional: nights, adr_eur, meal, customer_type, ... .
    A booking with a missing / out-of-range / unseen input gets the base-rate table instead."""
    as_of = date.fromisoformat(str(as_of)[:10])
    bundle, ref = load(artifact_dir)
    checks: list[G.Check] = []
    stale = G.staleness(ref, today or date.today(), checks, MODEL)
    x = _frame(bookings, as_of)
    if x["adr"].isna().all() and len(x):
        median = (ref or {}).get("features", {}).get("adr", {}).get("mean", 100.0)
        x["adr"] = median
        G.record(checks, "input_default", "warn", "adr_eur not supplied: training mean "
                 f"{median:.0f} EUR used (price effect not personalised)", MODEL)
    missing = G.validate_schema(x.rename(columns={"arrival_ts": "arrival"}),
                                ["arrival", "lead_time", "deposit_type", "market_segment"],
                                checks, MODEL)
    bad = G.validate_ranges(x, LIMITS, checks, MODEL)
    past = x["days_to_arrival"] < 0
    if past.any():
        G.record(checks, "input_range", "warn", f"{int(past.sum())} booking(s) arrive before "
                 "as_of; scored with the base rate", MODEL)
    ood, level = G.drift_check(x[F.FEATURES], ref, checks, MODEL)
    use_base = missing | bad | past | ood | stale
    dta = x["days_to_arrival"].fillna(0).clip(lower=0)
    p = np.array([base_rate(d, artifact_dir) for d in dta])
    ok = ~use_base.to_numpy()
    if ok.any():
        p[ok] = bundle["model"].predict_proba(F.encode(x[ok], bundle["columns"]))[:, 1]
    p = G.clip(p, 0.0, 1.0, checks, "probability", MODEL)
    share = float(use_base.mean()) if len(x) else 0.0
    if share:
        G.record(checks, "fallback", "warn", f"{int(use_base.sum())} of {len(x)} booking(s) "
                 "scored with the base-rate table", MODEL)
    rows = [BookingRisk(booking_ref=r.booking_ref,
                        arrival=(r.arrival_ts.date() if pd.notna(r.arrival_ts) else as_of),
                        days_to_arrival=int(d), p_cancel=round(float(pi), 4),
                        source="base_rate" if u else "model")
            for r, d, pi, u in zip(x.itertuples(), dta, p, use_base, strict=True)]
    return BookingScores(as_of=as_of, bookings=rows, confidence=G.confidence(
        None, level, share, stale), checks=checks, fallback_used=bool(share))


def night_adjustment(on_books: int, days_ahead: int, rooms: int | None = None,
                     probs: list[float] | None = None,
                     artifact_dir: Path = ARTIFACT_DIR) -> NightAdjustment:
    """Rooms on the books for one night -> rooms expected to really stay, with an 80% range.
    probs: per-booking probabilities (from score_bookings) for those rooms; without them every
    room gets the base-rate table's chance for `days_ahead` (the deployed source in real_v1)."""
    bundle, _ = load(artifact_dir)
    on_books = max(0, int(on_books))
    key = horizon_key(max(1, days_ahead))
    if probs is not None and len(probs) == on_books:
        p, src, qkey = np.clip(np.asarray(probs, float), 0, 1), "model", "model"
    else:
        p = np.full(on_books, base_rate(days_ahead, artifact_dir))
        src, qkey = "base_rate_table", "base"
    exp_c = float(p.sum())
    sd = math.sqrt(float((p * (1 - p)).sum()))
    q = bundle["range_q"][key][qkey]
    mean = on_books - exp_c
    cap = on_books if rooms is None else min(on_books, rooms)
    exp = min(max(mean, 0.0), float(cap))
    low = min(max(mean + q[0] * sd, 0.0), exp)  # 0 <= low <= expected <= high <= cap
    high = max(min(mean + q[1] * sd, float(cap)), exp)
    return NightAdjustment(on_books=on_books, days_ahead=days_ahead, source=src,
                           expected_cancellations=round(exp_c, 2), expected_rooms=round(exp, 2),
                           low=round(low, 2), high=round(high, 2))
