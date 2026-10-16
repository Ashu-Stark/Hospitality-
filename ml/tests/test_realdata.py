"""ml/realdata on tiny in-memory fixtures: no downloads, no GPU, no torch / xgboost needed."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.realdata import attrition as attr
from ml.realdata import forecast as fc
from ml.realdata import hotels, sources, tfm

# ---- fixtures -------------------------------------------------------------------------

def _booking(hotel, arrival, nights, lead=10, canceled=0, status_date=None, weekend=0):
    a = pd.Timestamp(arrival)
    return {"hotel": hotel, "is_canceled": canceled, "lead_time": lead,
            "arrival_date_year": a.year, "arrival_date_month": a.month_name(),
            "arrival_date_day_of_month": a.day, "stays_in_weekend_nights": weekend,
            "stays_in_week_nights": nights - weekend,
            "reservation_status": "Canceled" if canceled else "Check-Out",
            "reservation_status_date": status_date or str((a + pd.Timedelta(days=nights)).date())}


@pytest.fixture
def tiny_csv(tmp_path: Path) -> Path:
    rows = [
        _booking("City Hotel", "2016-01-10", 2, weekend=1),       # nights 10, 11
        _booking("City Hotel", "2016-01-11", 1, lead=0),          # night 11, booked same day
        _booking("City Hotel", "2016-01-10", 3, canceled=1, lead=20,
                 status_date="2016-01-05"),                         # cancelled 5 days before
        _booking("City Hotel", "2016-01-10", 1, canceled=1, lead=20,
                 status_date="2016-01-10"),                         # no-show style, late cancel
        _booking("Resort Hotel", "2016-01-10", 0),                  # day use: no night
        _booking("Resort Hotel", "2016-01-09", 3),                  # nights 9, 10, 11
    ]
    path = tmp_path / "hotels.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


# ---- loader / daily series -----------------------------------------------------------

def test_loader_shape_and_columns(tiny_csv: Path) -> None:
    b = hotels.load_bookings(tiny_csv)
    assert len(b) == 6
    assert {"arrival", "nights", "created", "cancelled_on"} <= set(b.columns)
    assert b["nights"].tolist() == [2, 1, 3, 1, 0, 3]
    assert b.loc[1, "created"] == pd.Timestamp("2016-01-11")


def test_loader_rejects_missing_columns(tmp_path: Path) -> None:
    p = tmp_path / "bad.csv"
    pd.DataFrame({"hotel": ["City Hotel"]}).to_csv(p, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        hotels.load_bookings(p)


def test_daily_room_nights_counts_only_stayed_nights(tiny_csv: Path) -> None:
    d = hotels.daily_room_nights(hotels.load_bookings(tiny_csv))
    city = d["City Hotel"]
    assert city["2016-01-10"] == 1 and city["2016-01-11"] == 2 and city["2016-01-12"] == 0
    resort = d["Resort Hotel"]
    assert resort["2016-01-09"] == 1 and resort["2016-01-11"] == 1 and resort["2016-01-12"] == 0
    # each hotel's series starts at its SERIES_START (earlier days are NaN)
    assert np.isnan(city[pd.Timestamp("2015-08-15")])
    assert d.index.max() == pd.Timestamp(hotels.SERIES_END)


def test_on_the_books_uses_only_information_known_at_origin(tiny_csv: Path) -> None:
    b = hotels.load_bookings(tiny_csv)
    otb1 = hotels.on_the_books(b, 1)["City Hotel"]
    # night 10, origin 9: the stay (created 31 Dec) + the late-cancelled booking (alive on 9th);
    # the booking cancelled on 5 Jan is gone.
    assert otb1["2016-01-10"] == 2
    # night 11, origin 10: the 2-night stay only (same-day booking not yet made; the early
    # cancellation is gone; the late-cancelled 1-night booking does not cover night 11)
    assert otb1["2016-01-11"] == 1
    otb30 = hotels.on_the_books(b, 30)["City Hotel"]
    assert otb30["2016-01-10"] == 0  # nothing booked 30 days ahead


def test_holiday_flags() -> None:
    idx = pd.date_range("2016-06-08", "2016-06-14")
    city = hotels.holiday_flags(idx, "City Hotel")
    resort = hotels.holiday_flags(idx, "Resort Hotel")
    assert city.loc["2016-06-10", "is_holiday"] == 1
    assert city.loc["2016-06-13", "is_holiday"] == 1 and resort.loc["2016-06-13", "is_holiday"] == 0
    assert city.loc["2016-06-08", "days_to_holiday"] == 2


# ---- split and leakage -----------------------------------------------------------------

def _toy_daily(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-08-01", hotels.SERIES_END, name="date")
    base = 150 + 30 * np.sin(np.arange(len(idx)) * 2 * np.pi / 365) + 10 * (idx.dayofweek >= 4)
    return pd.DataFrame({h: base + rng.normal(0, 5, len(idx)) for h in hotels.HOTELS}, index=idx)


def test_split_is_by_time_with_gaps() -> None:
    daily = _toy_daily()
    otb = daily * 0.8
    for h in fc.HORIZONS:
        parts = fc.split_frame(fc.build_frame(daily, otb, h, fc.capacities(daily)))
        tr, va, te = parts["train"], parts["val"], parts["test"]
        assert tr.index.max() < va.index.min() < te.index.min()
        assert (va.index.min() - tr.index.max()).days > 28
        assert (te.index.min() - va.index.max()).days > 27
        assert te.index.min() == pd.Timestamp("2017-03-01")
        assert te.index.max() == pd.Timestamp("2017-08-31")


@pytest.mark.parametrize("h", fc.HORIZONS)
def test_features_do_not_see_past_the_origin(h: int) -> None:
    daily = _toy_daily()
    otb = daily * 0.8
    caps = fc.capacities(daily)
    d = pd.Timestamp("2017-05-10")
    origin = d - pd.Timedelta(days=h)
    before = fc.build_frame(daily, otb, h, caps)
    corrupted = daily.copy()
    corrupted.loc[corrupted.index > origin] = 9999.0  # every night after the origin
    after = fc.build_frame(corrupted, otb, h, caps)
    feats = fc.features("pace")
    pd.testing.assert_frame_equal(before.loc[d, feats], after.loc[d, feats])
    assert after.loc[d, "y_true"].iloc[0] == 9999.0  # the target itself did change


def test_capacity_comes_from_train_window_only() -> None:
    daily = _toy_daily()
    daily.loc["2017-06-01", "City Hotel"] = 10_000  # test-period spike
    assert fc.capacities(daily)["City Hotel"] < 1000


def test_last_week_lag() -> None:
    assert [fc.last_week_lag(h) for h in (1, 7, 8, 30)] == [7, 7, 14, 35]


# ---- metrics ---------------------------------------------------------------------------

def test_metrics() -> None:
    y = np.array([100.0, 200.0, 0.0])
    p = np.array([110.0, 180.0, 5.0])
    assert fc.mape(y, p) == pytest.approx(0.1)  # zero-actual rows skipped
    assert fc.mae(y, p) == pytest.approx(35 / 3)
    assert fc.coverage(y, p - 15, p + 15) == pytest.approx(2 / 3)
    lo, hi = fc.conformal_offsets(np.arange(-50, 51, dtype=float))
    assert lo < 0 < hi and lo == pytest.approx(-hi, abs=2)


def test_score_rows_per_hotel() -> None:
    test = pd.DataFrame({"hotel": ["A", "A", "B"], "y_true": [10.0, 20.0, 30.0],
                         "capacity": [20.0, 20.0, 40.0]})
    rows = fc.score_rows(test, np.array([12.0, 20.0, 27.0]), np.array([0, 0, 0.0]),
                         np.array([50, 15, 50.0]))
    a, b = rows
    assert a["hotel"] == "A" and a["mae_room_nights"] == 1.0 and a["coverage_80"] == 0.5
    assert b["mae_pct_of_capacity"] == pytest.approx(3 / 40)


# ---- TimesFM windows (pure numpy, no torch) --------------------------------------------

def test_fine_tune_windows_stay_inside_train() -> None:
    daily = _toy_daily()
    cfg = tfm.FineTuneConfig(context=128, horizon=30, min_context=64)
    last = pd.Timestamp(fc.SPLIT.train_end)
    v, m, y = tfm.make_windows({h: daily[h] for h in hotels.HOTELS}, None, last, cfg)
    assert v.shape[1] == 128 and y.shape[1] == 30 and len(v) == len(m) == len(y)
    # the last window's final target is the train end: its 30 targets equal the series there
    city = daily["City Hotel"]
    per_hotel = len(v) // 2
    np.testing.assert_allclose(y[per_hotel - 1], city[:last].to_numpy()[-30:], rtol=1e-6)
    assert m[0].sum() == 128 - 64  # first window: 64 real nights, rest padded + masked


# ---- attrition: protected columns -----------------------------------------------------

def _ibm_like(n: int = 120, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    over = rng.choice(["Yes", "No"], n)
    sat = rng.integers(1, 5, n)
    y = ((over == "Yes") & (sat <= 2)) | (rng.random(n) < 0.08)
    return pd.DataFrame({
        "Age": rng.integers(20, 60, n), "Gender": rng.choice(["Male", "Female"], n),
        "MaritalStatus": rng.choice(["Single", "Married"], n),
        "Attrition": np.where(y, "Yes", "No"), "EmployeeCount": 1,
        "EmployeeNumber": np.arange(n), "Over18": "Y", "StandardHours": 80,
        "BusinessTravel": "Travel_Rarely", "Department": rng.choice(["Sales", "R&D"], n),
        "EducationField": "Other", "JobRole": rng.choice(["A", "B"], n), "OverTime": over,
        "JobSatisfaction": sat, "WorkLifeBalance": rng.integers(1, 5, n),
        "MonthlyIncome": rng.integers(2000, 9000, n), "label": y.astype(int)})


def test_protected_columns_are_dropped_ibm() -> None:
    x, y = attr.model_table(_ibm_like(), attr.IBM_SPEC)
    banned = {"Age", "Gender", "MaritalStatus", "Attrition", "label", "EmployeeNumber"}
    assert not banned & set(x.columns)
    assert len(y) == len(x) == 120


def test_protected_columns_are_dropped_turnover(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    n = 60
    df = pd.DataFrame({
        "stag": rng.uniform(1, 40, n), "event": rng.integers(0, 2, n),
        "gender": rng.choice(["m", "f"], n), "age": rng.integers(20, 50, n),
        "industry": "Retail", "profession": "HR", "traffic": "youjs", "coach": "no",
        "head_gender": "f", "greywage": "white", "way": "bus",
        **{c: rng.uniform(1, 10, n) for c in
           ("extraversion", "independ", "selfcontrol", "anxiety", "novator")}})
    p = tmp_path / "turnover.csv"
    df.to_csv(p, index=False, encoding="latin-1")
    t = attr.load_turnover(p)
    # censored people (still employed, tenure <= 12 months) are excluded
    keep = ((df["event"] == 1) & (df["stag"] <= 12)) | (df["stag"] > 12)
    assert len(t) == int(keep.sum())
    assert t["label"].sum() == int(((df["event"] == 1) & (df["stag"] <= 12)).sum())
    x, _ = attr.model_table(t, attr.TURNOVER_SPEC)
    assert set(x.columns) == {"industry", "profession", "traffic", "coach", "greywage", "way"}


@pytest.mark.gpu  # trains a model: GPU only
def test_rules_and_cross_validation_on_gpu() -> None:
    df = _ibm_like(200)
    x, _ = attr.model_table(df, attr.IBM_SPEC)
    s = attr.rule_score(x, attr.IBM_SPEC)
    assert s.min() >= 0 and s.max() <= 3
    res = attr.cross_validate(df, attr.IBM_SPEC, seeds=(42,), kinds=("rules", "logistic"))
    assert set(res["scorers"]) == {"rules", "logistic"}
    for v in res["scorers"].values():
        assert 0.0 <= v["roc_auc"]["mean"] <= 1.0 and 0.0 <= v["ece"]["mean"] <= 1.0
    assert res["dropped_protected"] == ["Age", "Gender", "MaritalStatus"]
    assert "Age" not in res["features"]


def test_ece_perfect_and_bad() -> None:
    y = np.array([0, 0, 1, 1] * 25)
    assert attr.ece(y.astype(float), y.astype(float)) == 0.0
    assert attr.ece(y, np.full(len(y), 0.9)) == pytest.approx(0.4)


# ---- sources ---------------------------------------------------------------------------

def test_fetch_verifies_hash_without_network(tmp_path: Path) -> None:
    data = b"a,b\n1,2\n"
    ds = dataclasses.replace(sources.HOTELS, filename="x.csv", url="http://invalid.invalid/",
                             sha256=sources.sha256_of(data))
    (tmp_path / "x.csv").write_bytes(data)
    assert sources.fetch(ds, tmp_path) == tmp_path / "x.csv"
    (tmp_path / "x.csv").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        sources.fetch(ds, tmp_path)


def test_every_dataset_documents_licence_and_provenance() -> None:
    for ds in sources.ALL:
        assert ds.licence and ds.provenance and ds.citation and len(ds.sha256) == 64
    assert sources.IBM_HR.provenance == "fictional"
