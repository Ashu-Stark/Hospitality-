"""Hotel Booking Demand (REAL data, CC BY 4.0) -> daily occupied room-nights per hotel.

Method
  One booking row = one room (the dataset has no room-count column; this is the standard
  reading of it). A non-cancelled booking (is_canceled == 0, reservation_status Check-Out)
  occupies one room on each night from arrival_date to arrival_date + nights - 1, where
  nights = stays_in_weekend_nights + stays_in_week_nights. Summing over bookings gives the
  occupied room-nights of each date. Day-use rows (0 nights) occupy no night and are skipped.

Limits (also in ml/realdata/README.md)
  - The hotels' room counts are NOT published, so we forecast room-nights, and report an
    occupancy PROXY = room-nights / the hotel's highest observed nightly count.
  - Only arrivals 2015-07-01..2017-08-31 are in the file: guests who arrived before July 2015
    are missing (first nights undercounted -> series starts later, see SERIES_START) and
    nights after 2017-08-31 are incomplete (series ends 2017-08-31).
  - City Hotel July-August 2015 looks incomplete (2 of 3 July bookings are cancellations and
    nightly counts are about half of September's), so its series starts 2015-09-01.
  - Arrival dates are FINAL dates: if a booking was moved, the original date is not recorded,
    so the on-the-books feature below is an approximation of what the hotel saw at the time.

On-the-books (booking pace) at origin t for night d: bookings created on or before t
(created = arrival - lead_time days) that cover night d and had not been cancelled by t
(cancelled bookings count until their reservation_status_date). It uses only information a
hotel's booking system holds at t, including bookings that LATER cancel, so it does not leak
the eventual cancellation outcome.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = [
    "hotel", "is_canceled", "lead_time", "arrival_date_year", "arrival_date_month",
    "arrival_date_day_of_month", "stays_in_weekend_nights", "stays_in_week_nights",
    "reservation_status", "reservation_status_date",
]
EXPECTED_ROWS = 119_390
HOTELS = ("City Hotel", "Resort Hotel")
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], start=1)}
SERIES_START = {"City Hotel": "2015-09-01", "Resort Hotel": "2015-08-01"}
SERIES_END = "2017-08-31"

# Portuguese NATIONAL public holidays 2015-2017 (the `holidays` package is not installed, so a
# small table). Corpus Christi, 5 Oct, 1 Nov and 1 Dec were suspended 2013-2015 and restored
# from 2016. Lisbon's municipal holiday (St Anthony, 13 June) applies to the City Hotel (Lisbon).
PT_HOLIDAYS: dict[str, str] = {
    "2015-01-01": "New Year", "2015-04-03": "Good Friday", "2015-04-05": "Easter",
    "2015-04-25": "Freedom Day", "2015-05-01": "Labour Day", "2015-06-10": "Portugal Day",
    "2015-08-15": "Assumption", "2015-12-08": "Immaculate Conception", "2015-12-25": "Christmas",
    "2016-01-01": "New Year", "2016-03-25": "Good Friday", "2016-03-27": "Easter",
    "2016-04-25": "Freedom Day", "2016-05-01": "Labour Day", "2016-05-26": "Corpus Christi",
    "2016-06-10": "Portugal Day", "2016-08-15": "Assumption", "2016-10-05": "Republic Day",
    "2016-11-01": "All Saints", "2016-12-01": "Restoration of Independence",
    "2016-12-08": "Immaculate Conception", "2016-12-25": "Christmas",
    "2017-01-01": "New Year", "2017-04-14": "Good Friday", "2017-04-16": "Easter",
    "2017-04-25": "Freedom Day", "2017-05-01": "Labour Day", "2017-06-10": "Portugal Day",
    "2017-06-15": "Corpus Christi", "2017-08-15": "Assumption",
}
LISBON_MUNICIPAL = ("2015-06-13", "2016-06-13", "2017-06-13")


def load_bookings(path: Path) -> pd.DataFrame:
    """Read the CSV, check its columns, add arrival / created / cancelled dates and nights."""
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"hotels.csv is missing columns {missing}")
    df["arrival"] = pd.to_datetime(pd.DataFrame({
        "year": df["arrival_date_year"], "month": df["arrival_date_month"].map(MONTHS),
        "day": df["arrival_date_day_of_month"]}))
    df["nights"] = (df["stays_in_weekend_nights"] + df["stays_in_week_nights"]).astype(int)
    df["created"] = df["arrival"] - pd.to_timedelta(df["lead_time"], unit="D")
    status_date = pd.to_datetime(df["reservation_status_date"])
    df["cancelled_on"] = status_date.where(df["is_canceled"] == 1)
    return df


def _explode_nights(b: pd.DataFrame) -> pd.DataFrame:
    """One row per (booking, occupied night) for bookings with >= 1 night."""
    b = b[b["nights"] > 0]
    reps = b["nights"].to_numpy()
    offsets = np.concatenate([np.arange(k) for k in reps]) if len(reps) else np.array([], int)
    out = b.loc[b.index.repeat(reps), ["hotel", "created", "cancelled_on", "is_canceled"]]
    out["night"] = np.repeat(b["arrival"].to_numpy(), reps) + pd.to_timedelta(offsets, unit="D")
    return out.reset_index(drop=True)


def daily_room_nights(bookings: pd.DataFrame) -> pd.DataFrame:
    """Date-indexed frame, one column per hotel: occupied room-nights from non-cancelled stays.

    Each hotel's series is cut to [SERIES_START[hotel], SERIES_END]; days outside a hotel's
    window are NaN.
    """
    nights = _explode_nights(bookings[bookings["is_canceled"] == 0])
    idx = pd.date_range(min(SERIES_START.values()), SERIES_END, freq="D", name="date")
    counts = nights.groupby(["night", "hotel"]).size().unstack("hotel").reindex(idx).fillna(0)
    out = pd.DataFrame(index=idx)
    for h in HOTELS:
        s = counts[h] if h in counts else pd.Series(0.0, index=idx)
        out[h] = s.where(s.index >= pd.Timestamp(SERIES_START[h]))
    return out


def on_the_books(bookings: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Room-nights on the books for each night d as of origin t = d - horizon (see module doc)."""
    nights = _explode_nights(bookings)
    origin = nights["night"] - pd.Timedelta(days=horizon)
    alive = (nights["created"] <= origin) & ~(nights["cancelled_on"] <= origin)
    idx = pd.date_range(min(SERIES_START.values()), SERIES_END, freq="D", name="date")
    return (nights[alive].groupby(["night", "hotel"]).size().unstack("hotel")
            .reindex(idx).fillna(0).reindex(columns=list(HOTELS), fill_value=0.0))


def holiday_flags(index: pd.DatetimeIndex, hotel: str) -> pd.DataFrame:
    """is_holiday (national, plus Lisbon's municipal day for the City Hotel) and days to the
    nearest holiday (capped at 14)."""
    days = list(PT_HOLIDAYS) + (list(LISBON_MUNICIPAL) if hotel == "City Hotel" else [])
    hol = pd.DatetimeIndex(sorted(pd.to_datetime(days)))
    is_hol = index.isin(hol).astype(int)
    diff = np.abs(index.to_numpy()[:, None] - hol.to_numpy()[None, :]).min(axis=1)
    near = np.minimum(diff / np.timedelta64(1, "D"), 14).astype(int)
    return pd.DataFrame({"is_holiday": is_hol, "days_to_holiday": near}, index=index)


def capacity_proxy(series: pd.Series) -> float:
    """Highest observed nightly room-nights (a lower bound on the hotel's room count)."""
    return float(series.max())
