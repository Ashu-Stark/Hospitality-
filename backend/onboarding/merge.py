"""Merge extracted values into the draft, owner edits, and validators (Part C).

Merge rules:
- voice / typed answers overwrite template and default values;
- an owner edit always wins: a later answer never overwrites it (a warning says so);
- a confident earlier answer is not replaced by a low-confidence reading;
- a value below accept_threshold is stored but NOT confirmed and carries "please confirm", so it
  is never silently accepted (Confirm is blocked until the owner edits or re-confirms it);
- legal fields (schema.LEGAL_FIELDS) are never confirmed here: only an explicit acknowledgement
  at Confirm time does that.
Validators return per-field errors (out of range, bad months / shift times: block Confirm) and
warnings (staff-to-room ratio, hotel type vs size band, departments kept from the template).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.onboarding.config import OnboardingConfig
from backend.onboarding.extract import ExtractionResult, load_lexicon
from backend.onboarding.schema import LEGAL_FIELDS, HotelProfile, Shift

PLEASE_CONFIRM = "please confirm"
RANGED = ("standard_weekly_hours", "weekly_off_days", "min_rest_hours", "max_consecutive_days",
          "overtime_rate_multiplier", "incentive_monthly_budget_cap")


class Issues(BaseModel):
    errors: dict[str, list[str]] = Field(default_factory=dict)     # block Confirm
    warnings: dict[str, list[str]] = Field(default_factory=dict)   # shown, never block

    def add(self, kind: str, field: str, msg: str) -> None:
        getattr(self, kind).setdefault(field, []).append(msg)

    def merged_with(self, other: Issues) -> Issues:
        out = Issues(errors={k: list(v) for k, v in self.errors.items()},
                     warnings={k: list(v) for k, v in self.warnings.items()})
        for kind in ("errors", "warnings"):
            for f, msgs in getattr(other, kind).items():
                for m in msgs:
                    out.add(kind, f, m)
        return out


def _field_value(name: str, value: Any, source: str, method: str, confidence: float,
                 accept: float, note: str | None) -> dict:
    legal = name in LEGAL_FIELDS
    accepted = confidence >= accept and not legal
    if note is None and confidence < accept:
        note = PLEASE_CONFIRM
    return {"value": value, "source": source, "method": method, "confidence": confidence,
            "needs_verification": legal, "confirmed": accepted, "note": note}


def merge(profile: HotelProfile, result: ExtractionResult, source: str,
          cfg: OnboardingConfig) -> tuple[HotelProfile, list[str], Issues]:
    """Apply an extraction to the draft: (new draft, fields filled, merge warnings)."""
    accept = cfg.confidence.accept_threshold
    issues = Issues()
    filled = []
    for name, guess in result.fields.items():
        old = profile.field(name)
        if old.method == "edit":
            issues.add("warnings", name, f"kept your edit ({old.value}); the answer said "
                                         f"{guess.value}")
            continue
        if old.from_answer and old.confidence >= accept > guess.confidence:
            issues.add("warnings", name, f"kept the earlier answer ({old.value}); the new "
                                         f"reading {guess.value} was uncertain")
            continue
        value = guess.value
        if name == "departments" and old.source == "template" and old.value:
            kept = sorted(set(old.value) - set(value))
            if kept:
                issues.add("warnings", name, "kept from the template (not mentioned): "
                                             + ", ".join(kept) + "; edit to remove")
                value = {**{d: old.value[d] for d in kept}, **value}
        fv = _field_value(name, value, source, result.method, guess.confidence, accept,
                          guess.note)
        try:
            profile = profile.with_field(name, fv)
        except ValidationError:
            issues.add("warnings", name, f"could not use {guess.value!r} for {name}")
            continue
        filled.append(name)
    return profile, filled, issues


def edit_field(profile: HotelProfile, name: str, value: Any, cfg: OnboardingConfig
               ) -> HotelProfile:
    """The owner typed a value into the draft table: it always wins (confidence 1.0).

    Raises KeyError for an unknown field and ValidationError for a value of the wrong type."""
    profile.field(name)
    fv = _field_value(name, value, "typed", "edit", cfg.confidence.edit, 0.0, None)
    return profile.with_field(name, fv)


def _range(issues: Issues, field: str, value: float, band, label: str | None = None) -> None:  # noqa: ANN001
    if not band.contains(value):
        hi = "no limit" if band.max is None else f"{band.max:g}"
        issues.add("errors", field, f"{label or field} {value:g} is outside the allowed range "
                                    f"{band.min:g}-{hi}")


def validate(profile: HotelProfile, cfg: OnboardingConfig) -> Issues:
    r = cfg.ranges
    issues = Issues()
    known = set(load_lexicon().departments)
    rooms = profile.rooms.value
    if rooms is not None:
        _range(issues, "rooms", rooms, r.rooms)
        band = cfg.hotel_type_for(rooms)
        t = profile.hotel_type.value
        if t and band and band != t:
            issues.add("warnings", "hotel_type", f"{rooms} rooms is in the {band} size band, "
                                                 f"not {t}")
    depts = profile.departments.value
    if depts is not None:
        for d, n in depts.items():
            if d not in known:
                issues.add("errors", "departments", f"unknown department {d!r}")
            _range(issues, "departments", n, r.headcount_per_department, f"{d} headcount")
        if rooms:
            ratio = sum(depts.values()) / rooms
            band = cfg.staff_to_room_ratio
            if not band.contains(ratio):
                issues.add("warnings", "departments",
                           f"{sum(depts.values())} staff for {rooms} rooms is {ratio:.2f} per "
                           f"room, outside the usual {band.min:g}-{band.max:g}: please check")
    months = profile.peak_months.value
    if months is not None:
        bad = [m for m in months if not 1 <= m <= 12]
        if bad:
            issues.add("errors", "peak_months", f"not valid months: {bad}")
    shifts = profile.shifts.value
    if shifts is not None:
        if not shifts:
            issues.add("errors", "shifts", "at least one shift is needed")
        for s in shifts:
            sh = s if isinstance(s, Shift) else Shift.model_validate(s)
            _range(issues, "shifts", sh.hours, r.shift_hours,
                   f"{sh.name} shift ({sh.start}-{sh.end}) length in hours")
    for name in RANGED:
        v = profile.field(name).value
        if v is not None:
            _range(issues, name, v, getattr(r, name))
    return issues
