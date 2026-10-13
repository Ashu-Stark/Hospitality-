"""HotelProfile: the onboarding draft, one FieldValue per field (Part A).

Every field carries where its value came from (template | voice | typed | default), a confidence
in [0, 1], needs_verification and confirmed. Legal values (min_rest_hours,
overtime_rate_multiplier, weekly_off_days) ALWAYS have needs_verification=True: they depend on
labour rules a qualified person must confirm, so no extraction or template can clear the flag.
Range checks live in validators.py (config ranges), so an out-of-range draft can still be stored
and shown with a clear error instead of being rejected silently.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

HotelType = Literal["homestay", "small_hotel", "resort"]
HOTEL_TYPES: tuple[str, ...] = ("homestay", "small_hotel", "resort")
Source = Literal["template", "voice", "typed", "default"]
# How the value was produced: template, rule-based extractor, LLM extractor, owner edit, none.
Method = Literal["template", "rules", "llm", "edit", "default"]
ANSWER_SOURCES = ("voice", "typed")
LEGAL_FIELDS: tuple[str, ...] = ("min_rest_hours", "overtime_rate_multiplier", "weekly_off_days")
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
MINUTES_PER_HOUR, HOURS_PER_DAY = 60, 24

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Shift(_Strict):
    name: str = Field(min_length=1)
    start: str = Field(pattern=TIME_PATTERN, description="HH:MM, 24 h")
    end: str = Field(pattern=TIME_PATTERN, description="HH:MM, 24 h; may be past midnight")

    @staticmethod
    def minutes(t: str) -> int:
        h, m = t.split(":")
        return int(h) * MINUTES_PER_HOUR + int(m)

    @property
    def hours(self) -> float:
        """Length in hours; an end at or before the start runs past midnight."""
        span = (self.minutes(self.end) - self.minutes(self.start)) % (
            HOURS_PER_DAY * MINUTES_PER_HOUR)
        return span / MINUTES_PER_HOUR


class FieldValue[T](_Strict):
    value: T | None = None
    source: Source = "default"
    confidence: float = Field(default=0.0, ge=0, le=1)
    needs_verification: bool = False
    confirmed: bool = False
    method: Method = "default"
    note: str | None = None   # e.g. "please confirm: the number did not match what you said"

    @property
    def filled(self) -> bool:
        return self.value is not None

    @property
    def from_answer(self) -> bool:
        return self.source in ANSWER_SOURCES


class Geo(_Strict):
    """Where the location text was found (LocationIQ geocoding); a hint for the owner, never a
    confirmed fact."""
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    display_name: str = Field(max_length=300)
    source: Literal["locationiq"] = "locationiq"
    confidence: float = Field(default=0.0, ge=0, le=1)
    query: str | None = Field(default=None, max_length=200)   # the text that was geocoded


class LocationValue(FieldValue[str]):
    """The location field plus an optional geocoding result (older drafts have no `geo`)."""
    geo: Geo | None = None


class HotelProfile(_Strict):
    hotel_name: FieldValue[str] = Field(default_factory=FieldValue[str])
    hotel_type: FieldValue[HotelType] = Field(default_factory=FieldValue[HotelType])
    rooms: FieldValue[int] = Field(default_factory=FieldValue[int])
    location: LocationValue = Field(default_factory=LocationValue)
    peak_months: FieldValue[list[int]] = Field(default_factory=FieldValue[list[int]])
    departments: FieldValue[dict[str, int]] = Field(default_factory=FieldValue[dict[str, int]])
    head_roles: FieldValue[dict[str, str]] = Field(default_factory=FieldValue[dict[str, str]])
    shifts: FieldValue[list[Shift]] = Field(default_factory=FieldValue[list[Shift]])
    standard_weekly_hours: FieldValue[int] = Field(default_factory=FieldValue[int])
    weekly_off_days: FieldValue[int] = Field(default_factory=FieldValue[int])
    min_rest_hours: FieldValue[float] = Field(default_factory=FieldValue[float])
    max_consecutive_days: FieldValue[int] = Field(default_factory=FieldValue[int])
    overtime_rate_multiplier: FieldValue[float] = Field(default_factory=FieldValue[float])
    incentive_monthly_budget_cap: FieldValue[int] = Field(default_factory=FieldValue[int])

    @model_validator(mode="after")
    def _legal_fields_need_verification(self) -> HotelProfile:
        for name in LEGAL_FIELDS:
            getattr(self, name).needs_verification = True
        return self

    def field(self, name: str) -> FieldValue:
        if name not in FIELD_NAMES:
            raise KeyError(f"unknown profile field {name!r}")
        return getattr(self, name)

    def with_field(self, name: str, fv: FieldValue | dict[str, Any]) -> HotelProfile:
        """A validated copy with one field replaced (type-checked against the field's type)."""
        data = self.model_dump()
        data[name] = fv.model_dump() if isinstance(fv, BaseModel) else fv
        return HotelProfile.model_validate(data)


FIELD_NAMES: tuple[str, ...] = tuple(HotelProfile.model_fields)
OPTIONAL_FIELDS: tuple[str, ...] = ("hotel_name", "head_roles", "incentive_monthly_budget_cap")
REQUIRED_FIELDS: tuple[str, ...] = tuple(f for f in FIELD_NAMES if f not in OPTIONAL_FIELDS)
