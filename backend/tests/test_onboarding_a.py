"""Onboarding Part A: HotelProfile schema, config, size-based templates (SYNTHETIC)."""

import pytest
from pydantic import ValidationError

from backend.config import load_backend_config
from backend.onboarding.config import load_config, load_templates
from backend.onboarding.schema import (
    FIELD_NAMES,
    LEGAL_FIELDS,
    FieldValue,
    HotelProfile,
    Shift,
)
from backend.onboarding.templates import apply_template, resolve, template_values
from ml.generator.config import load_config as load_ml_config


def test_profile_defaults_are_empty_and_legal_fields_need_verification() -> None:
    p = HotelProfile()
    assert all(not p.field(f).filled and p.field(f).source == "default" for f in FIELD_NAMES)
    for f in LEGAL_FIELDS:
        assert p.field(f).needs_verification
    # no path can clear the flag: even an explicit False is overridden
    forced = HotelProfile.model_validate(
        {"min_rest_hours": {"value": 10, "needs_verification": False}})
    assert forced.min_rest_hours.needs_verification


def test_field_values_are_type_checked() -> None:
    p = HotelProfile()
    ok = p.with_field("rooms", FieldValue[int](value=12, source="typed", confidence=0.8))
    assert ok.rooms.value == 12
    with pytest.raises(ValidationError):
        p.with_field("rooms", {"value": "twelve"})
    with pytest.raises(ValidationError):
        p.with_field("hotel_type", {"value": "palace"})
    with pytest.raises(ValidationError):
        p.with_field("rooms", {"value": 12, "confidence": 1.5})
    with pytest.raises(KeyError):
        p.field("salary")


def test_shift_times_and_hours() -> None:
    assert Shift(name="night", start="22:00", end="06:00").hours == 8
    assert Shift(name="m", start="07:30", end="15:00").hours == 7.5
    with pytest.raises(ValidationError):
        Shift(name="x", start="25:00", end="06:00")


def test_size_bands() -> None:
    cfg = load_config()
    assert cfg.max_questions == 8
    assert [cfg.hotel_type_for(n) for n in (5, 12, 15, 16, 35, 50, 51, 400)] == [
        "homestay", "homestay", "homestay", "small_hotel", "small_hotel", "small_hotel",
        "resort", "resort"]
    assert cfg.hotel_type_for(3) is None


def test_templates_reference_the_ml_and_backend_standards_not_copies() -> None:
    t = load_templates()
    for name in ("standard_weekly_hours", "weekly_off_days", "min_rest_hours",
                 "max_consecutive_days", "overtime_rate_multiplier"):
        assert getattr(t.common, name).split(":")[0] in ("ml", "backend")
    ml, backend = load_ml_config(), load_backend_config()
    v = template_values("small_hotel", 35)
    assert v["standard_weekly_hours"] == ml.staff.standard_weekly_hours
    assert v["min_rest_hours"] == backend.roster.min_rest_hours
    assert v["max_consecutive_days"] == backend.roster.max_consecutive_days
    assert v["overtime_rate_multiplier"] == backend.roster.overtime_premium
    assert v["weekly_off_days"] == backend.roster.min_days_off
    assert resolve("ml:workload")["housekeeping"].base_hours == ml.workload[
        "housekeeping"].base_hours
    with pytest.raises(ValueError):
        resolve("nowhere:x")


def test_templates_scale_with_rooms_and_type() -> None:
    home, small, resort = (template_values(t, n) for t, n in
                           (("homestay", 12), ("small_hotel", 35), ("resort", 80)))
    assert len(home["departments"]) < len(small["departments"])
    assert load_templates().hotel_types["homestay"].roles_can_be_combined
    assert sum(resort["departments"].values()) > sum(small["departments"].values()) > sum(
        home["departments"].values())
    ratio = load_config().staff_to_room_ratio
    for v, n in ((home, 12), (small, 35), (resort, 80)):
        assert ratio.contains(sum(v["departments"].values()) / n)
        assert all(1 <= m <= 12 for m in v["peak_months"])


def test_apply_template_fills_unfilled_fields_only() -> None:
    p = apply_template(HotelProfile(), "homestay")
    for f in FIELD_NAMES:
        fv = p.field(f)
        if f in ("location", "hotel_name", "incentive_monthly_budget_cap"):
            assert not fv.filled  # no template value exists for these
        else:
            assert fv.filled and fv.source == "template" and fv.confidence == 0.5, f
    answered = HotelProfile().with_field(
        "rooms", {"value": 40, "source": "typed", "confidence": 0.8, "method": "rules"})
    q = apply_template(answered, "small_hotel")
    assert q.rooms.value == 40 and q.rooms.source == "typed"
    assert q.departments.value == template_values("small_hotel", 40)["departments"]
    # re-applying another type refreshes template fields but never answers
    r = apply_template(q, "resort")
    assert r.rooms.value == 40 and r.hotel_type.value == "resort"
    assert r.min_rest_hours.needs_verification
