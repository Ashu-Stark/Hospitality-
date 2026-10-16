"""Booking cancellation features + interface (ml/realdata/hotel_alerts). Tiny in-memory
fixtures for the features (no download); the interface tests load the committed real_v1
artifact (trained on REAL public data)."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from ml.realdata.hotel_alerts import api
from ml.realdata.hotel_alerts import features as F

LEAKY = {"reservation_status", "reservation_status_date", "assigned_room_type",
         "required_car_parking_spaces", "booking_changes", "country", "adults", "children",
         "babies"}


def _bookings() -> pd.DataFrame:
    rows = []
    for i, (lead, canc, cancelled_on) in enumerate([(40, 0, None), (40, 1, "2016-05-05"),
                                                    (3, 1, "2016-05-29"), (0, 0, None)]):
        rows.append({"hotel": "Resort Hotel", "is_canceled": canc, "lead_time": lead,
                     "arrival": pd.Timestamp("2016-06-01"), "meal": "BB",
                     "market_segment": "Online TA", "distribution_channel": "TA/TO",
                     "reserved_room_type": "A", "deposit_type": "No Deposit",
                     "customer_type": "Transient", "stays_in_weekend_nights": 0,
                     "stays_in_week_nights": 2, "is_repeated_guest": 0,
                     "previous_cancellations": 0, "previous_bookings_not_canceled": 0,
                     "days_in_waiting_list": 0, "adr": 90.0, "total_of_special_requests": i,
                     "agent": "NULL" if i else "9", "company": None,
                     "cancelled_on": pd.Timestamp(cancelled_on) if cancelled_on else pd.NaT,
                     # leaky columns present in the raw file, must never be read
                     "reservation_status": "x", "assigned_room_type": "Z",
                     "required_car_parking_spaces": 99, "country": "PRT"})
    return pd.DataFrame(rows)


def test_no_leaky_or_personal_column_is_a_feature() -> None:
    assert not LEAKY & set(F.FEATURES)
    assert LEAKY <= set(F.EXCLUDED)
    meta = json.loads((api.ARTIFACT_DIR / "feature_list.json").read_text("utf-8"))
    assert not any(c.split("=")[0] in LEAKY for c in meta["encoded_columns"])


def test_snapshots_only_while_booked_and_not_yet_cancelled() -> None:
    s = F.snapshots(_bookings(), days=(30, 7, 1))
    by = s.groupby("booking_id")["snapshot"].apply(sorted).to_dict()
    assert by[0] == ["1d", "30d", "7d", "booking"]    # kept booking, made 40 days ahead
    assert by[1] == ["30d", "booking"]                 # cancelled 27 days before arrival
    assert by[2] == ["booking"]                        # made 3 days ahead: no 7d/30d rows
    assert by[3] == ["booking"]                        # same-day booking
    row = s[(s.booking_id == 0) & (s.snapshot == "7d")].iloc[0]
    assert row["days_to_arrival"] == 7 and row["days_since_booking"] == 33


def test_leaky_values_do_not_change_the_encoding() -> None:
    b = _bookings()
    x1 = F.encode(F.snapshots(b))
    b2 = b.assign(required_car_parking_spaces=0, assigned_room_type="A", country="GBR")
    x2 = F.encode(F.snapshots(b2))
    pd.testing.assert_frame_equal(x1, x2)
    assert F._static(b)["has_agent"].tolist() == [1.0, 0.0, 0.0, 0.0]  # "NULL" = no agent


def test_encode_unseen_category_is_all_zero() -> None:
    s = F.snapshots(_bookings())
    cols = list(F.encode(s).columns)
    odd = F.encode(s.assign(deposit_type="Something new"), cols)
    assert list(odd.columns) == cols
    assert odd.filter(like="deposit_type=").sum().sum() == 0


def test_buckets() -> None:
    assert F.bucket_of([0, 1, 2, 7, 8, 30, 500]).tolist() == [0, 1, 2, 2, 3, 4, 7]
    assert F.bucket_label(2) == "2-7" and F.bucket_label(7) == "181+"


# ------------------------------------------------------------------ interface (real_v1)
OK = {"arrival": "2029-12-28", "booked_on": "2029-12-01", "deposit_type": "No Deposit",
      "market_segment": "Online TA", "nights": 2}


def test_metrics_record_real_data_split_and_baselines() -> None:
    m = json.loads((api.ARTIFACT_DIR / "metrics.json").read_text("utf-8"))
    assert m["data"]["provenance"] == "REAL" and m["data"]["licence"] == "CC BY 4.0"
    assert m["split"]["by"] == "arrival date"
    t = m["test_at_booking"]
    assert {"base_rate", "logistic", "xgboost"} <= set(t)
    assert t[m["deployed"]["model"]]["roc_auc"] > t["base_rate"]["roc_auc"]
    assert (api.ARTIFACT_DIR / "reference_stats.json").exists()


def test_score_bookings_guards_each_booking() -> None:
    r = api.score_bookings([OK, {**OK, "deposit_type": "Non Refund"},
                            {"arrival": "2029-12-28"},
                            {**OK, "booked_on": "2027-01-01"}],  # 1,092-day lead time
                           as_of="2029-12-24", today=date(2026, 10, 15))
    src = [b.source for b in r.bookings]
    assert src == ["model", "model", "base_rate", "base_rate"]
    assert all(0 <= b.p_cancel <= 1 for b in r.bookings)
    assert r.fallback_used and r.confidence == "low"
    assert "REAL" in r.note and any(c.name == "input_default" for c in r.checks)


def test_score_bookings_stale_model_uses_base_rates() -> None:
    r = api.score_bookings([OK], as_of="2029-12-24", today=date(2031, 1, 1))
    assert r.bookings[0].source == "base_rate" and r.confidence == "low"


def test_night_adjustment_bounds_and_sources() -> None:
    a = api.night_adjustment(20, 5, rooms=24)
    assert a.source == "base_rate_table"
    assert 0 <= a.low <= a.expected_rooms <= a.high <= 20
    assert a.expected_cancellations == pytest.approx(20 * api.base_rate(5), abs=0.01)
    b = api.night_adjustment(3, 2, rooms=24, probs=[0.1, 0.5, 0.9])
    assert b.source == "model" and b.expected_cancellations == pytest.approx(1.5)
    z = api.night_adjustment(0, 3)
    assert z.expected_rooms == 0 and z.high == 0
    over = api.night_adjustment(24, 1, rooms=10)  # more bookings than rooms: capped
    assert 0 <= over.low <= over.expected_rooms <= over.high <= 10
