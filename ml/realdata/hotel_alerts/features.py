"""Booking cancellation features on REAL data (Hotel Booking Demand, CC BY 4.0).

A row is a SNAPSHOT of one booking at a prediction time t: either the moment it was made
(t = created = arrival - lead_time) or h days before arrival (h in SNAPSHOT_DAYS) if it was
already made and not yet cancelled by then. Label: the booking is cancelled or a no-show
(is_canceled == 1) after t. Features use only what a booking system holds at t.

EXCLUDED columns, and why (checked on the full file, 119,390 bookings):
  reservation_status, reservation_status_date  the outcome itself and its date
  assigned_room_type        assigned at check-in: bookings whose assigned room differs from the
                            reserved one cancel 5.4% of the time vs 41.6% otherwise (a leak)
  required_car_parking_spaces  recorded at arrival: 0 of 7,416 bookings with a space cancelled
  booking_changes           a FINAL count, updated until arrival or cancellation
  country                   filled in at check-in for many bookings (known leak in this file);
                            also nationality, which HOI never uses
  adults, children, babies  party / family composition: not used (project rule)
  agent, company            ids of Portuguese agents / companies: replaced by has_agent /
                            has_company flags, which carry over to another hotel
  arrival_date_year         a trend term that cannot extrapolate
Kept but noted: adr and total_of_special_requests are FINAL values in the file and may have
been edited after booking; an ablation without them is reported (RESULTS.md).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LABEL = "is_canceled"
SNAPSHOT_DAYS = (1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90)
CATEGORICAL = ["hotel", "meal", "market_segment", "distribution_channel", "reserved_room_type",
               "deposit_type", "customer_type"]
NUMERIC = ["lead_time", "days_to_arrival", "days_since_booking", "arrival_month", "arrival_dow",
           "stays_in_weekend_nights", "stays_in_week_nights", "is_repeated_guest",
           "previous_cancellations", "previous_bookings_not_canceled", "days_in_waiting_list",
           "adr", "total_of_special_requests", "has_agent", "has_company"]
FEATURES = CATEGORICAL + NUMERIC
LOG1P = ["lead_time", "days_to_arrival", "days_since_booking", "previous_cancellations",
         "previous_bookings_not_canceled", "days_in_waiting_list", "adr"]
EXCLUDED = {
    "reservation_status": "the outcome",
    "reservation_status_date": "the outcome date",
    "assigned_room_type": "assigned at check-in (leak)",
    "required_car_parking_spaces": "recorded at arrival (leak: never > 0 for a cancellation)",
    "booking_changes": "final count, updated until arrival",
    "country": "filled at check-in for many bookings (leak); nationality is not used",
    "adults": "party composition: not used",
    "children": "family composition: not used",
    "babies": "family composition: not used",
    "agent": "replaced by has_agent",
    "company": "replaced by has_company",
    "arrival_date_year": "trend term, cannot extrapolate",
}
ABLATION_DROP = ["adr", "total_of_special_requests"]  # final values that may change after booking
# Base-rate buckets of days to arrival (inclusive upper bounds).
BUCKETS = (0, 1, 7, 14, 30, 90, 180, 10_000)


def _static(b: pd.DataFrame) -> pd.DataFrame:
    """Booking fields known when it is made (no leaky column is ever read)."""
    out = pd.DataFrame({
        "hotel": b["hotel"].astype(str),
        "meal": b["meal"].astype(str).str.strip().replace({"Undefined": "SC"}),
        "market_segment": b["market_segment"].astype(str),
        "distribution_channel": b["distribution_channel"].astype(str),
        "reserved_room_type": b["reserved_room_type"].astype(str).str.strip(),
        "deposit_type": b["deposit_type"].astype(str),
        "customer_type": b["customer_type"].astype(str),
        "lead_time": b["lead_time"].astype(float),
        "arrival_month": b["arrival"].dt.month.astype(float),
        "arrival_dow": b["arrival"].dt.dayofweek.astype(float),
        "stays_in_weekend_nights": b["stays_in_weekend_nights"].astype(float),
        "stays_in_week_nights": b["stays_in_week_nights"].astype(float),
        "is_repeated_guest": b["is_repeated_guest"].astype(float),
        "previous_cancellations": b["previous_cancellations"].astype(float),
        "previous_bookings_not_canceled": b["previous_bookings_not_canceled"].astype(float),
        "days_in_waiting_list": b["days_in_waiting_list"].astype(float),
        "adr": b["adr"].astype(float).clip(lower=0),
        "total_of_special_requests": b["total_of_special_requests"].astype(float),
        "has_agent": b["agent"].notna().astype(float) if "agent" in b else 0.0,
        "has_company": b["company"].notna().astype(float) if "company" in b else 0.0,
    }, index=b.index)
    for c in ("agent", "company"):  # the TidyTuesday copy writes missing ids as the text NULL
        if c in b:
            out[f"has_{c}"] = (b[c].notna() & (b[c].astype(str).str.upper() != "NULL")).astype(
                float)
    return out


def snapshots(b: pd.DataFrame, days: tuple[int, ...] = SNAPSHOT_DAYS) -> pd.DataFrame:
    """One row per (booking, prediction time): at booking + h days before arrival when the
    booking exists and is not cancelled by then (cancelled_on <= t means gone at t)."""
    static = _static(b)
    parts = []
    at_booking = static.assign(days_to_arrival=b["lead_time"].astype(float), snapshot="booking")
    parts.append(at_booking)
    for h in days:
        t = b["arrival"] - pd.Timedelta(days=h)
        alive = (b["lead_time"] >= h) & ~(b["cancelled_on"].notna() & (b["cancelled_on"] <= t))
        parts.append(static[alive].assign(days_to_arrival=float(h), snapshot=f"{h}d"))
    rows = pd.concat(parts)
    rows["days_since_booking"] = rows["lead_time"] - rows["days_to_arrival"]
    rows[LABEL] = b.loc[rows.index, LABEL].astype(int).to_numpy()
    rows["arrival"] = b.loc[rows.index, "arrival"].to_numpy()
    rows["booking_id"] = rows.index.to_numpy()
    return rows.reset_index(drop=True)


def bucket_of(days_to_arrival: np.ndarray | pd.Series) -> np.ndarray:
    """Index into BUCKETS (0: same day, 1: 1 day, 2: 2-7, ...)."""
    return np.searchsorted(np.asarray(BUCKETS), np.asarray(days_to_arrival, dtype=float),
                           side="left")


def bucket_label(i: int) -> str:
    lo = 0 if i == 0 else BUCKETS[i - 1] + 1
    hi = BUCKETS[i]
    return f"{lo}" if lo == hi else (f"{lo}+" if hi >= 10_000 else f"{lo}-{hi}")


def encode(rows: pd.DataFrame, columns: list[str] | None = None,
           drop: list[str] | None = None) -> pd.DataFrame:
    """One-hot categoricals + log1p heavy-tailed numerics. `columns` = the training columns
    (unseen categories become all-zero, missing columns 0)."""
    num = [c for c in NUMERIC if c not in (drop or [])]
    x = rows[num].astype(float).copy()
    for c in LOG1P:
        if c in x:
            x[c] = np.log1p(x[c].clip(lower=0))
    x = pd.concat([x, pd.get_dummies(rows[CATEGORICAL].astype(str), prefix_sep="=",
                                     dtype=float)], axis=1)
    if columns is not None:
        x = x.reindex(columns=columns, fill_value=0.0)
    return x
