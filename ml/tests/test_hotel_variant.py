"""Hotel variant (fictional Himsagar Ridge Resort, SYNTHETIC data): config, ids, scoring."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from ml.attrition.features import MODEL_FEATURES
from ml.generator import hotel_variant as hv
from ml.generator.config import load_config

DATA = hv.data_dir("himsagar")
FILES = [
    "event_calendar.csv",
    "weather_daily.csv",
    "occupancy_daily.csv",
    "employee.csv",
    "employee_skill.csv",
    "dept_week_load.csv",
    "employee_v2.csv",
    "weekly_behaviour.csv",
    "weekly_signals.csv",
    "exits.csv",
    "contract_renewals.csv",
    "pay_changes.csv",
    "dept_week_load_dynamic.csv",
    "leave_records.csv",
    "pulse_responses.csv",
    "attrition_calibration.json",
    "hotel.json",
    "demo/hero_employees.csv",
    "demo/hero_weekly.csv",
    "demo/hero_display_names.json",
]
PERSONAL = {
    "name",
    "full_name",
    "first_name",
    "last_name",
    "gender",
    "sex",
    "age",
    "dob",
    "religion",
    "caste",
    "health",
    "family",
    "family_status",
    "marital_status",
}
needs_data = pytest.mark.skipif(
    not (DATA / "hotel.json").exists(), reason="run python run.py generate-hotel"
)


def test_variant_config_merges_without_touching_default() -> None:
    cfg, spec = hv.load_hotel("himsagar")
    assert cfg.property.rooms == 24 and cfg.staff_target == 19 and len(spec.positions) == 19
    assert cfg.departments == {
        "housekeeping": 6,
        "fnb_service": 3,
        "kitchen": 3,
        "front_office": 3,
        "maintenance": 2,
        "security": 2,
    }
    default = load_config()
    assert (
        default.property.rooms == 45 and default.staff_target == 55
    )  # the default dataset's config
    # role vocabulary and pay are the default hotel's, so the trained model sees known categories
    for dept, roles in cfg.roles.items():
        for role, spec_ in roles.items():
            assert default.roles[dept][role].pay_mean == spec_.pay_mean
    # Mussoorie seasonality: summer peak, monsoon dip, winter above the monsoon
    m = cfg.month_base_occupancy
    assert m[5] > m[12] > m[8] and m[2] < m[1]


def test_merge_replaces_whole_blocks() -> None:
    out = hv._merge(
        {"roles": {"a": 1, "b": 2}, "occupancy": {"x": 1, "y": 2}},
        {"roles": {"a": 3}, "occupancy": {"x": 5}},
    )
    assert out == {"roles": {"a": 3}, "occupancy": {"x": 5, "y": 2}}


def test_unknown_variant() -> None:
    with pytest.raises(FileNotFoundError):
        hv.load_hotel("no_such_hotel")


@needs_data
def test_file_set_and_ids() -> None:
    for name in FILES:
        assert (DATA / name).exists(), name
    record = json.loads((DATA / "hotel.json").read_text(encoding="utf-8"))
    ids = [s["employee_id"] for s in record["staff"]]
    assert (
        ids == [f"HS{n:02d}" for n in range(1, 21)]
        and record["rooms"] == 24
        and record["synthetic"]
    )
    week, staff = hv.demo_week_staff(DATA)
    assert (
        week == record["demo_week"] and sorted(staff["employee_id"]) == ids[1:]
    )  # HS01 = manager, not rostered
    contracts = {s["contract_type"] for s in record["staff"]}
    assert contracts == {"permanent", "seasonal"}
    emp = pd.read_csv(DATA / "employee_v2.csv")
    assert all(e.startswith(("HS", "HSX")) for e in emp["employee_id"])
    for name in FILES:
        if name.endswith(".csv"):
            cols = pd.read_csv(DATA / name, nrows=0).columns
            assert not PERSONAL & {c.lower() for c in cols}, name
    heroes = pd.read_csv(DATA / "demo" / "hero_employees.csv")
    assert heroes.empty  # no demo heroes in the hotel variant


@needs_data
def test_generation_is_reproducible(tmp_path: Path) -> None:
    hv.generate("himsagar", root=tmp_path)
    for name in FILES + ["internal/employee_latent.csv"]:
        a, b = (tmp_path / "himsagar" / name).read_bytes(), (DATA / name).read_bytes()
        assert hashlib.sha256(a).digest() == hashlib.sha256(b).digest(), name


@needs_data
def test_existing_models_score_the_variant() -> None:
    from ml import attrition, forecast
    from ml.attrition.explain import feature_frame, tables_with_heroes

    frame = feature_frame(tables_with_heroes(DATA))
    assert set(MODEL_FEATURES) <= set(frame.columns)  # identical feature columns
    scores = attrition.score("2029-12-24", data_dir=DATA)
    assert sorted(s.employee_id for s in scores) == [f"HS{n:02d}" for n in range(2, 21)]
    assert all(0 <= s.risk <= 1 and s.synthetic for s in scores)
    assert any(
        s.band == "high" and s.segment == "resignation" for s in scores
    )  # the closed loop has people
    days = forecast.predict("2029-12-24", "2029-12-30", data_dir=DATA, rooms=24).days
    assert len(days) == 7 and all(0 <= d.mean <= 1 for d in days)
