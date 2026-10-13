"""Size-based templates (Part A): fill every field the owner has not answered.

The work standards are read by reference ("ml:<path>" / "backend:<path>" in templates.yaml) from
ml/generator/config.yaml and backend/config.yaml, never copied. apply_template() fills every
field that is still unfilled or only template / default filled (so a template refresh after the
owner gives the number of rooms re-sizes the departments), with source="template" and the
template confidence; answers and owner edits are never touched.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from backend.config import load_backend_config
from backend.onboarding.config import OnboardingConfig, Templates, load_config, load_templates
from backend.onboarding.schema import FIELD_NAMES, HOURS_PER_DAY, HotelProfile, Shift
from ml.generator.config import load_config as load_ml_config

DAYS_PER_WEEK = 7
HALF = 0.5


@lru_cache(maxsize=1)
def _sources() -> dict[str, BaseModel]:
    return {"ml": load_ml_config(), "backend": load_backend_config()}


def resolve(ref: str) -> Any:
    """'ml:staff.standard_weekly_hours' -> the value in ml/generator/config.yaml."""
    root, _, path = ref.partition(":")
    sources = _sources()
    if root not in sources or not path:
        raise ValueError(f"bad template reference {ref!r} (use ml:<path> or backend:<path>)")
    value: Any = sources[root]
    for part in path.split("."):
        value = value[part] if isinstance(value, dict) else getattr(value, part)
    return value


def round_half_up(x: float) -> int:
    return math.floor(x + HALF)


def mean_occupancy(templates: Templates) -> float:
    occ = resolve(templates.references["monthly_occupancy"])
    return sum(occ.values()) / len(occ)


def template_headcounts(hotel_type: str, rooms: int, templates: Templates) -> dict[str, int]:
    t = templates.hotel_types[hotel_type]
    workload = resolve(templates.references["workload"])
    weekly = resolve(templates.common.standard_weekly_hours)
    occ = mean_occupancy(templates)
    out = {}
    for dept in t.departments:
        std = workload[dept]
        hours = (std.base_hours * t.base_hours_scale
                 + std.per_occupied_room_night_hours * rooms * occ * DAYS_PER_WEEK)
        out[dept] = max(t.min_headcount, round_half_up(hours / weekly))
    return out


def template_shifts(hotel_type: str, templates: Templates) -> list[Shift]:
    specs = resolve(templates.references["roster_shifts"])
    out = []
    for name in templates.hotel_types[hotel_type].shifts:
        s = specs[name]
        end = (s.start + s.hours) % HOURS_PER_DAY
        out.append(Shift(name=name, start=f"{s.start:02d}:00", end=f"{end:02d}:00"))
    return out


def peak_months(templates: Templates) -> list[int]:
    occ = resolve(templates.references["monthly_occupancy"])
    return sorted(m for m, v in occ.items() if v >= templates.common.peak_occupancy_threshold)


def template_values(hotel_type: str, rooms: int | None,
                    templates: Templates | None = None) -> dict[str, Any]:
    """Every template value for a hotel type (rooms: the owner's number, else typical_rooms)."""
    templates = templates or load_templates()
    t = templates.hotel_types[hotel_type]
    c = templates.common
    n = rooms if rooms is not None else t.typical_rooms
    heads = resolve(templates.references["department_heads"])
    return {
        "hotel_type": hotel_type,
        "rooms": t.typical_rooms,
        "peak_months": peak_months(templates),
        "departments": template_headcounts(hotel_type, n, templates),
        "head_roles": {d: t.head_role or heads.get(d, d) for d in t.departments},
        "shifts": [s.model_dump() for s in template_shifts(hotel_type, templates)],
        "standard_weekly_hours": int(resolve(c.standard_weekly_hours)),
        "weekly_off_days": int(resolve(c.weekly_off_days)),
        "min_rest_hours": float(resolve(c.min_rest_hours)),
        "max_consecutive_days": int(resolve(c.max_consecutive_days)),
        "overtime_rate_multiplier": float(resolve(c.overtime_rate_multiplier)),
        "incentive_monthly_budget_cap": c.incentive_monthly_budget_cap,
    }


def refillable(profile: HotelProfile, name: str) -> bool:
    """Unfilled, or filled only by a template / default (never an answer or an owner edit)."""
    fv = profile.field(name)
    return not fv.filled or fv.source in ("template", "default")


def apply_template(profile: HotelProfile, hotel_type: str, templates: Templates | None = None,
                   cfg: OnboardingConfig | None = None) -> HotelProfile:
    """A copy with every refillable field set from the template (source template, confidence
    from onboarding.yaml: 0.5).

    hotel_type is only template-filled when the owner has not given it; rooms from an answer
    sizes the departments."""
    rooms = profile.rooms.value if not refillable(profile, "rooms") else None
    values = template_values(hotel_type, rooms, templates)
    confidence = (cfg or load_config()).confidence.template
    data = profile.model_dump()
    for name in FIELD_NAMES:
        if name in values and values[name] is not None and refillable(profile, name):
            data[name] = {**data[name], "value": values[name], "source": "template",
                          "method": "template", "confidence": confidence,
                          "confirmed": False, "note": None}
    return HotelProfile.model_validate(data)
