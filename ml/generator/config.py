"""Load and validate the synthetic data generator config (config.yaml)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")

MONTHS = frozenset(range(1, 13))

Probability = Annotated[float, Field(ge=0, le=1)]
NonNegative = Annotated[float, Field(ge=0)]
Positive = Annotated[float, Field(gt=0)]


def _all_months[V](v: dict[int, V]) -> dict[int, V]:
    if set(v) != MONTHS:
        raise ValueError(f"must have exactly months 1..12, got {sorted(v)}")
    return v


ProbabilityByMonth = Annotated[dict[int, Probability], AfterValidator(_all_months)]
FloatByMonth = Annotated[dict[int, float], AfterValidator(_all_months)]
PositiveByMonth = Annotated[dict[int, Positive], AfterValidator(_all_months)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PropertyConfig(_Strict):
    rooms: int = Field(gt=0)
    start: date
    end: date

    @model_validator(mode="after")
    def _start_before_end(self) -> PropertyConfig:
        if self.start >= self.end:
            raise ValueError(f"property.start ({self.start}) must be before end ({self.end})")
        return self


def _parse_month_day(value: str) -> str:
    # 2024 is a leap year, so "02-29" is accepted.
    datetime.strptime(f"2024-{value}", "%Y-%m-%d")
    return value


class CharDhamSeason(_Strict):
    start_month_day: str
    end_month_day: str

    @field_validator("start_month_day", "end_month_day")
    @classmethod
    def _valid_month_day(cls, v: str) -> str:
        try:
            return _parse_month_day(v)
        except ValueError as exc:
            raise ValueError(f"expected MM-DD, got {v!r}") from exc

    @model_validator(mode="after")
    def _start_before_end(self) -> CharDhamSeason:
        if self.start_month_day >= self.end_month_day:
            raise ValueError("char_dham_season start must be before end")
        return self


class OccupancyConfig(_Strict):
    festival_bump: NonNegative
    char_dham_bump: NonNegative
    weekend_days: list[int]
    noise_sd: NonNegative
    ar1_phi: float = Field(ge=0, lt=1)
    min: Probability
    max: Probability

    @field_validator("weekend_days")
    @classmethod
    def _valid_weekdays(cls, v: list[int]) -> list[int]:
        if not v or len(set(v)) != len(v) or not set(v) <= set(range(7)):
            raise ValueError(f"weekend_days must be unique ints in 0..6 (Mon=0), got {v}")
        return v

    @model_validator(mode="after")
    def _min_below_max(self) -> OccupancyConfig:
        if self.min >= self.max:
            raise ValueError(f"occupancy.min ({self.min}) must be below max ({self.max})")
        return self


class WeatherConfig(_Strict):
    monthly_temp_c: FloatByMonth
    temp_sd: NonNegative
    rain_prob_by_month: ProbabilityByMonth
    heavy_rain_occupancy_penalty: Probability
    monsoon_months: list[int]
    heavy_rain_prob_monsoon: Probability
    heavy_rain_prob_other: Probability

    @field_validator("monsoon_months")
    @classmethod
    def _valid_months(cls, v: list[int]) -> list[int]:
        if not v or len(set(v)) != len(v) or not set(v) <= MONTHS:
            raise ValueError(f"monsoon_months must be unique ints in 1..12, got {v}")
        return v


class RoadClosureConfig(_Strict):
    per_year_mean: NonNegative
    monsoon_share: Probability
    duration_days_range: tuple[int, int]
    occupancy_penalty: Probability

    @field_validator("duration_days_range")
    @classmethod
    def _valid_range(cls, v: tuple[int, int]) -> tuple[int, int]:
        lo, hi = v
        if not 1 <= lo <= hi:
            raise ValueError(f"duration_days_range must satisfy 1 <= lo <= hi, got {list(v)}")
        return v


class AdrConfig(_Strict):
    base_by_month: PositiveByMonth
    weekend_premium: NonNegative
    noise_sd: NonNegative


class BookingPaceConfig(_Strict):
    pickup_fraction_mean: Probability
    noise_sd: NonNegative


HEAD_ROLE_PREFIX = "head"
MAX_SKILLS_PER_EMPLOYEE = 3
SKILL_MIN_HOLDERS_DEFAULT = 2
SKILL_MIN_HOLDERS = {"fo_system": 3}


def is_head_role(role: str) -> bool:
    return role.startswith(HEAD_ROLE_PREFIX)


def skill_min_holders(skill: str) -> int:
    return SKILL_MIN_HOLDERS.get(skill, SKILL_MIN_HOLDERS_DEFAULT)


class RoleSpec(_Strict):
    count: int = Field(gt=0)
    pay_mean: Positive
    pay_sd: NonNegative


class StaffConfig(_Strict):
    tenure_mean_years: Positive
    tenure_min_years: NonNegative
    tenure_max_years: Positive
    seasonal_share_by_role: dict[str, Probability]
    seasonal_contract_end_options: list[str]
    standard_weekly_hours: Positive

    @field_validator("seasonal_contract_end_options")
    @classmethod
    def _valid_options(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("seasonal_contract_end_options must not be empty")
        for md in v:
            try:
                _parse_month_day(md)
            except ValueError as exc:
                raise ValueError(f"expected MM-DD, got {md!r}") from exc
        return v

    @model_validator(mode="after")
    def _tenure_range(self) -> StaffConfig:
        if self.tenure_min_years >= self.tenure_max_years:
            raise ValueError("staff.tenure_min_years must be below tenure_max_years")
        return self


class WorkloadStandard(_Strict):
    base_hours: NonNegative
    per_occupied_room_night_hours: NonNegative


class HazardConfig(_Strict):
    """Coefficients of the logistic weekly resignation hazard (see config.yaml)."""

    overtime_window_weeks: int = Field(gt=0)
    overtime_ref_hours: NonNegative
    coef_overtime_per_hour: NonNegative
    no_leave_ref_weeks: NonNegative
    coef_no_leave_per_week: NonNegative
    low_pulse_ref: float = Field(ge=1, le=5)
    coef_low_pulse: NonNegative
    pulse_drop_ref: NonNegative
    coef_pulse_drop: NonNegative
    pay_ratio_ref: Positive
    coef_pay_gap: NonNegative
    stalled_ref_months: NonNegative
    coef_stalled_per_month: NonNegative
    load_ref: NonNegative
    coef_load: NonNegative
    peer_exit_window_weeks: int = Field(gt=0)
    coef_peer_exit: NonNegative
    new_hire_years: NonNegative
    coef_new_hire: NonNegative
    coef_latent_frustration: NonNegative
    noise_sd: NonNegative
    max_weekly_hazard: Probability


class RaiseConfig(_Strict):
    eligible_after_months: NonNegative
    weekly_prob_when_eligible: Probability
    pct_mean: NonNegative
    pct_sd: NonNegative


class CalibrationConfig(_Strict):
    intercept_low: float
    intercept_high: float
    tolerance: Positive
    max_iterations: int = Field(gt=0)
    refine_half_width: NonNegative
    refine_steps: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> CalibrationConfig:
        if self.intercept_low >= self.intercept_high:
            raise ValueError("calibration.intercept_low must be below intercept_high")
        return self


class AttritionConfig(_Strict):
    seasonal_contract_end_is_exit: bool
    seasonal_renewal_prob: Probability
    vacancy_days_mean: Positive
    vacancy_days_min: int = Field(ge=0)
    vacancy_days_max: int = Field(ge=0)
    overtime_hours_cap_weekly: NonNegative
    overtime_trigger_load_ratio: NonNegative
    pulse_load_sensitivity: float
    pulse_overtime_sensitivity: float
    pulse_noise_sd: NonNegative
    leave_days_per_year_mean: NonNegative
    leave_days_per_year_sd: NonNegative
    leave_seasonal_block_weeks: list[int]
    hazard: HazardConfig
    raises: RaiseConfig
    calibration: CalibrationConfig
    visible_driver_min_logit: Positive
    high_driver_min_count: int = Field(gt=0)

    @field_validator("leave_seasonal_block_weeks")
    @classmethod
    def _valid_iso_weeks(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v) or not set(v) <= set(range(1, 54)):
            raise ValueError(f"leave_seasonal_block_weeks must be unique ISO weeks 1..53, got {v}")
        return v

    @model_validator(mode="after")
    def _vacancy_range(self) -> AttritionConfig:
        if not self.vacancy_days_min < self.vacancy_days_mean < self.vacancy_days_max:
            raise ValueError("need vacancy_days_min < vacancy_days_mean < vacancy_days_max")
        return self


class SignalsConfig(_Strict):
    task_fatigue_ref_hours: NonNegative
    task_fatigue_per_hour: NonNegative
    task_noise_sd: NonNegative
    task_score_min: float
    task_score_max: float
    skip_weekly_off_base_logit: float
    skip_weekly_off_per_overtime_hour: float
    weekend_off_share: Probability
    festival_lookahead_days: int = Field(ge=0)

    @model_validator(mode="after")
    def _range(self) -> SignalsConfig:
        if self.task_score_min >= self.task_score_max:
            raise ValueError("signals.task_score_min must be below task_score_max")
        return self


class ForecastConfig(_Strict):
    horizons_days: list[int]
    train_end: date
    test_start: date
    test_end: date
    booking_pace_max_horizon_days: int = Field(ge=0)
    band_quantiles: tuple[Probability, Probability]
    conformal_calibration_start: date
    alert_high_occupancy: Probability
    alert_low_occupancy: Probability

    @model_validator(mode="after")
    def _ordered(self) -> ForecastConfig:
        if not (self.train_end < self.test_start <= self.test_end):
            raise ValueError("forecast: need train_end < test_start <= test_end")
        if not self.conformal_calibration_start < self.train_end:
            raise ValueError("forecast: conformal_calibration_start must be before train_end")
        if not self.band_quantiles[0] < self.band_quantiles[1]:
            raise ValueError("forecast.band_quantiles must be increasing")
        if not self.alert_low_occupancy < self.alert_high_occupancy:
            raise ValueError("forecast alert_low must be below alert_high")
        if not self.horizons_days or min(self.horizons_days) < 1:
            raise ValueError("forecast.horizons_days must be positive")
        return self


class AttritionModelConfig(_Strict):
    test_years: list[int] = Field(min_length=1)
    festival_leave_window_weeks: int = Field(gt=0)
    rule_sustained_overtime_hours: NonNegative
    rule_weeks_without_weekend_off: int = Field(ge=0)
    rule_pulse_drop: NonNegative
    band_high_share: Probability
    band_watch_share: Probability
    seasonal_high_max_days: int = Field(ge=0)
    seasonal_watch_max_days: int = Field(ge=0)
    driver_min_logodds: NonNegative

    @model_validator(mode="after")
    def _ordered(self) -> AttritionModelConfig:
        if self.test_years != sorted(set(self.test_years)):
            raise ValueError("attrition_model: test_years must be increasing and unique")
        if self.band_high_share + self.band_watch_share > 1:
            raise ValueError("attrition_model: band shares must sum to at most 1")
        if not self.seasonal_high_max_days < self.seasonal_watch_max_days:
            raise ValueError("attrition_model: seasonal_high_max_days must be below watch days")
        return self


class GeneratorConfig(_Strict):
    seed: int
    property: PropertyConfig
    staff_target: int = Field(gt=0)
    departments: dict[str, int]
    month_base_occupancy: ProbabilityByMonth
    weekend_uplift: Probability
    char_dham_season: CharDhamSeason
    target_annual_attrition: Probability
    label_horizon_days: int = Field(gt=0)
    occupancy: OccupancyConfig
    weather: WeatherConfig
    road_closures: RoadClosureConfig
    adr: AdrConfig
    booking_pace: BookingPaceConfig
    roles: dict[str, dict[str, RoleSpec]]
    skills: dict[str, list[str]]
    staff: StaffConfig
    workload: dict[str, WorkloadStandard]
    attrition: AttritionConfig
    signals: SignalsConfig
    forecast: ForecastConfig
    attrition_model: AttritionModelConfig

    @field_validator("departments")
    @classmethod
    def _positive_departments(cls, v: dict[str, int]) -> dict[str, int]:
        bad = {k: n for k, n in v.items() if n <= 0}
        if bad:
            raise ValueError(f"department counts must be positive: {bad}")
        return v

    @model_validator(mode="after")
    def _departments_sum_to_target(self) -> GeneratorConfig:
        total = sum(self.departments.values())
        if total != self.staff_target:
            raise ValueError(
                f"department counts sum to {total}, expected staff_target={self.staff_target}"
            )
        return self

    @model_validator(mode="after")
    def _blocks_cover_departments(self) -> GeneratorConfig:
        depts = set(self.departments)
        for name in ("roles", "skills", "workload"):
            keys = set(getattr(self, name))
            if keys != depts:
                raise ValueError(f"{name} departments {sorted(keys)} != {sorted(depts)}")
        return self

    @model_validator(mode="after")
    def _roles_match_departments(self) -> GeneratorConfig:
        for dept, roles in self.roles.items():
            total = sum(r.count for r in roles.values())
            if total != self.departments[dept]:
                want = self.departments[dept]
                raise ValueError(f"roles in {dept} sum to {total}, expected {want}")
            heads = [r for r in roles if is_head_role(r)]
            if len(heads) != 1 or roles[heads[0]].count != 1:
                raise ValueError(f"{dept} needs exactly one head role with count 1, got {heads}")
        all_roles = {r for roles in self.roles.values() for r in roles}
        unknown = set(self.staff.seasonal_share_by_role) - all_roles
        if unknown:
            raise ValueError(f"seasonal_share_by_role has unknown roles {sorted(unknown)}")
        return self

    @model_validator(mode="after")
    def _skills_feasible(self) -> GeneratorConfig:
        for dept, skills in self.skills.items():
            if not skills or len(set(skills)) != len(skills):
                raise ValueError(f"skills for {dept} must be a non-empty unique list")
            size = self.departments[dept]
            if size < 2:
                continue
            needed = sum(min(skill_min_holders(s), size) for s in skills)
            if needed > MAX_SKILLS_PER_EMPLOYEE * size:
                raise ValueError(f"{dept}: skill coverage needs {needed} holdings, too many")
        return self


def load_config(path: str | Path | None = None) -> GeneratorConfig:
    """Load config.yaml (default: next to this module) and validate it."""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return GeneratorConfig.model_validate(raw)
