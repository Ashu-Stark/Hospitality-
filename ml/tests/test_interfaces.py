"""T9 interfaces on the committed SYNTHETIC data and artifacts (no training)."""

import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ml import attrition, forecast, voice

DATA = Path(__file__).resolve().parents[1] / "data"


def test_forecast_predict_small_range() -> None:
    r = forecast.predict("2029-12-01", "2029-12-03")
    assert r.synthetic and r.as_of == date(2029, 11, 30)
    assert [d.horizon_days for d in r.days] == [1, 7, 7]
    for d in r.days:
        assert 0 <= d.low <= d.mean <= d.high <= 1
        assert isinstance(d.high_demand_alert, bool) and d.source in {"model", "baseline"}


def test_forecast_refuses_too_far_or_outside_data() -> None:
    with pytest.raises(ValueError, match="trained horizons"):
        forecast.predict("2029-12-01", "2029-12-05", as_of="2029-10-01")
    with pytest.raises(ValueError, match="inside the SYNTHETIC data"):
        forecast.predict("2030-01-01", "2030-01-02")


def test_forecast_never_reads_occupancy_after_as_of(tmp_path) -> None:
    for name in ("event_calendar.csv", "weather_daily.csv"):
        shutil.copy(DATA / name, tmp_path / name)
    occ = pd.read_csv(DATA / "occupancy_daily.csv")
    after = occ["date"] > "2029-11-30"
    occ.loc[after, ["occupancy_pct", "rooms_sold"]] = [0.01, 0]  # booking pace stays as known
    occ.to_csv(tmp_path / "occupancy_daily.csv", index=False)
    a = forecast.predict("2029-12-01", "2029-12-20")
    b = forecast.predict("2029-12-01", "2029-12-20", data_dir=tmp_path)
    assert [d.mean for d in a.days] == [d.mean for d in b.days]


def test_attrition_score_heroes() -> None:
    week = attrition.api.latest_week()
    res = {r.employee_id: r for r in attrition.score(week, ["H901", "H904", "H905"])}
    assert res["H901"].segment == "resignation" and res["H904"].segment == "contract_end"
    from ml.attrition.drivers import DRIVER_GROUPS

    cats = [d.category for d in res["H901"].drivers]
    assert set(cats) <= set(DRIVER_GROUPS) and len(cats) <= 3
    assert res["H905"].band != "high"
    assert all(r.is_demo_hero and 1 <= r.rank <= r.group_size + 1 for r in res.values())
    assert res["H901"].actions and res["H901"].actions[0].expected_effect.startswith("ASSUMPTION")
    assert all(0 <= r.risk <= 1 for r in res.values())


def test_attrition_score_all_and_errors() -> None:
    week = attrition.api.latest_week()
    everyone = attrition.score(week)
    assert len(everyone) > 5 and len({r.employee_id for r in everyone}) == len(everyone)
    with pytest.raises(ValueError, match="no active employees"):
        attrition.score("2029-12-25")
    with pytest.raises(ValueError, match="not active"):
        attrition.score(week, ["NOPE"])


def test_rescore_sunita_two_protected_weekends() -> None:
    overrides = attrition.protected_weekends_off("H901", 2)
    assert overrides["weeks_since_weekend_off"] == 0
    r = attrition.rescore("H901", overrides)
    assert r.features_before["weeks_since_weekend_off"] == 5
    assert r.features_after == {k: pytest.approx(v) for k, v in overrides.items()}
    assert r.risk_change == pytest.approx(r.after.risk - r.before.risk, abs=1e-4)
    assert "SIMULATION" in r.note
    with pytest.raises(ValueError, match="unknown features"):
        attrition.rescore("H901", {"religion": 1.0})


def test_voice_extract_reports_what_is_missing() -> None:
    with pytest.raises(voice.api.VoiceUnavailable, match="not found"):
        voice.extract("no_such_clip.wav")
