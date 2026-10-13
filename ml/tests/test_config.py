from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ml.generator.config import DEFAULT_CONFIG_PATH, GeneratorConfig, load_config


def _raw() -> dict:
    with DEFAULT_CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write(tmp_path: Path, raw: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return p


def test_default_config_loads() -> None:
    cfg = load_config()
    assert isinstance(cfg, GeneratorConfig)
    assert cfg.seed == 42
    assert cfg.property.rooms == 45
    assert cfg.property.start < cfg.property.end


def test_departments_sum_to_55() -> None:
    cfg = load_config()
    assert sum(cfg.departments.values()) == 55 == cfg.staff_target


def test_negative_rooms_raises(tmp_path: Path) -> None:
    raw = _raw()
    raw["property"]["rooms"] = -5
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_occupancy_out_of_range_raises(tmp_path: Path) -> None:
    raw = _raw()
    raw["month_base_occupancy"][5] = 1.3
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_department_sum_mismatch_raises(tmp_path: Path) -> None:
    raw = _raw()
    raw["departments"]["kitchen"] += 1
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_start_after_end_raises(tmp_path: Path) -> None:
    raw = _raw()
    raw["property"]["start"], raw["property"]["end"] = "2025-12-31", "2023-01-01"
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_new_blocks_load() -> None:
    cfg = load_config()
    assert cfg.occupancy.weekend_days == [4, 5]
    assert cfg.weather.rain_prob_by_month[8] == 0.75
    assert cfg.road_closures.duration_days_range == (1, 4)
    assert cfg.adr.base_by_month[5] == 5200
    assert cfg.booking_pace.pickup_fraction_mean == 0.7


@pytest.mark.parametrize(
    ("block", "key", "value"),
    [
        ("occupancy", "min", 1.0),  # min must be below max
        ("occupancy", "weekend_days", [5, 7]),  # 7 is not a weekday
        ("occupancy", "ar1_phi", 1.0),  # non-stationary
        ("occupancy", "noise_sd", -0.1),
        ("weather", "temp_sd", -1),
        ("weather", "heavy_rain_occupancy_penalty", 1.5),
        ("weather", "monsoon_months", [6, 13]),
        ("road_closures", "duration_days_range", [4, 1]),
        ("road_closures", "duration_days_range", [0, 2]),
        ("road_closures", "monsoon_share", 1.2),
        ("adr", "weekend_premium", -0.1),
        ("booking_pace", "pickup_fraction_mean", 1.1),
        ("occupancy", "unexpected_key", 1),  # unknown keys rejected
    ],
)
def test_invalid_new_block_values_raise(
    tmp_path: Path, block: str, key: str, value: object
) -> None:
    raw = _raw()
    raw[block][key] = value
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_rain_prob_out_of_range_raises(tmp_path: Path) -> None:
    raw = _raw()
    raw["weather"]["rain_prob_by_month"][7] = 1.2
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_missing_month_raises(tmp_path: Path) -> None:
    raw = _raw()
    del raw["adr"]["base_by_month"][12]
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_non_positive_adr_raises(tmp_path: Path) -> None:
    raw = _raw()
    raw["adr"]["base_by_month"][1] = 0
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_staff_blocks_load() -> None:
    cfg = load_config()
    assert cfg.roles["kitchen"]["head_chef"].pay_mean == 45000
    assert cfg.skills["front_office"] == ["fo_system", "cash_handling", "form_c_reporting"]
    assert cfg.staff.seasonal_share_by_role["helper"] == 0.30
    assert cfg.workload["security"].per_occupied_room_night_hours == 0.0
    for dept, roles in cfg.roles.items():
        assert sum(r.count for r in roles.values()) == cfg.departments[dept]


def _mutate(tmp_path: Path, change) -> None:
    raw = _raw()
    change(raw)
    with pytest.raises(ValidationError):
        load_config(_write(tmp_path, raw))


def test_role_counts_must_match_departments(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["roles"]["housekeeping"]["attendant"].update(count=13))


def test_department_needs_one_head(tmp_path: Path) -> None:
    def two_heads(r: dict) -> None:
        r["roles"]["security"]["head_guard"] = r["roles"]["security"].pop("guard")

    _mutate(tmp_path, two_heads)


def test_negative_pay_sd_raises(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["roles"]["kitchen"]["cook"].update(pay_sd=-1))


def test_unknown_role_key_raises(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["roles"]["kitchen"]["cook"].update(bonus=5))


def test_skills_must_cover_departments(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["skills"].pop("security"))


def test_duplicate_skill_raises(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["skills"].update(security=["patrol", "patrol"]))


def test_infeasible_skill_coverage_raises(tmp_path: Path) -> None:
    many = [f"s{i}" for i in range(9)]  # 9 skills x 2 holders > 3 x 5 security staff
    _mutate(tmp_path, lambda r: r["skills"].update(security=many))


def test_seasonal_share_unknown_role_raises(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["staff"]["seasonal_share_by_role"].update(pilot=0.1))


def test_bad_contract_end_option_raises(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["staff"].update(seasonal_contract_end_options=["13-01"]))


def test_tenure_min_above_max_raises(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["staff"].update(tenure_min_years=9))


def test_workload_must_cover_departments(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["workload"].pop("kitchen"))


def test_negative_workload_hours_raise(tmp_path: Path) -> None:
    _mutate(tmp_path, lambda r: r["workload"]["kitchen"].update(base_hours=-5))
