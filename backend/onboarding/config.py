"""Load and validate the onboarding YAML files (every value in them is ASSUMED)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.onboarding.schema import HOTEL_TYPES

ONBOARDING_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ONBOARDING_DIR / "onboarding.yaml"
TEMPLATES_PATH = ONBOARDING_DIR / "templates.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Band(_Strict):
    min: float
    max: float | None = None

    def contains(self, x: float) -> bool:
        return x >= self.min and (self.max is None or x <= self.max)


class Ranges(_Strict):
    rooms: Band
    headcount_per_department: Band
    shift_hours: Band
    standard_weekly_hours: Band
    weekly_off_days: Band
    min_rest_hours: Band
    max_consecutive_days: Band
    overtime_rate_multiplier: Band
    incentive_monthly_budget_cap: Band


class Confidence(_Strict):
    template: float = Field(ge=0, le=1)
    rules_pattern: float = Field(ge=0, le=1)
    rules_context: float = Field(ge=0, le=1)
    rules_free_text: float = Field(ge=0, le=1)
    llm_checked: float = Field(ge=0, le=1)
    llm_unchecked: float = Field(ge=0, le=1)
    mismatch: float = Field(ge=0, le=1)
    edit: float = Field(ge=0, le=1)
    accept_threshold: float = Field(ge=0, le=1)


class OnboardingConfig(_Strict):
    review: dict[str, str | bool]
    size_bands: dict[str, Band]
    default_hotel_type: str
    ranges: Ranges
    staff_to_room_ratio: Band
    max_questions: int = Field(ge=1)
    confidence: Confidence

    @model_validator(mode="after")
    def _types(self) -> OnboardingConfig:
        if set(self.size_bands) != set(HOTEL_TYPES):
            raise ValueError(f"size_bands must cover exactly {HOTEL_TYPES}")
        if self.default_hotel_type not in HOTEL_TYPES:
            raise ValueError("default_hotel_type must be a hotel type")
        return self

    def hotel_type_for(self, rooms: int) -> str | None:
        """The size band that contains `rooms` (None below the smallest band)."""
        return next((t for t in HOTEL_TYPES if self.size_bands[t].contains(rooms)), None)


class TypeTemplate(_Strict):
    typical_rooms: int = Field(ge=1)
    base_hours_scale: float = Field(ge=0)
    min_headcount: int = Field(ge=0)
    departments: list[str] = Field(min_length=1)
    shifts: list[str] = Field(min_length=1)
    roles_can_be_combined: bool
    head_role: str | None


class CommonTemplate(_Strict):
    standard_weekly_hours: str
    weekly_off_days: str
    min_rest_hours: str
    max_consecutive_days: str
    overtime_rate_multiplier: str
    peak_occupancy_threshold: float = Field(gt=0, le=1)
    incentive_monthly_budget_cap: int | None


class Templates(_Strict):
    review: dict[str, str | bool]
    references: dict[str, str]
    common: CommonTemplate
    hotel_types: dict[str, TypeTemplate]

    @model_validator(mode="after")
    def _all_types(self) -> Templates:
        if set(self.hotel_types) != set(HOTEL_TYPES):
            raise ValueError(f"templates must cover exactly {HOTEL_TYPES}")
        return self


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_config(path: Path = CONFIG_PATH) -> OnboardingConfig:
    return OnboardingConfig.model_validate(_yaml(path))


@lru_cache(maxsize=4)
def load_templates(path: Path = TEMPLATES_PATH) -> Templates:
    return Templates.model_validate(_yaml(path))
