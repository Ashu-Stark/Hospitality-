"""Backend settings: config.yaml (validated) plus environment overrides."""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ml.generator.config import GeneratorConfig

BACKEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_ROOT.parent
ML_ROOT = REPO_ROOT / "ml"
ML_DATA = ML_ROOT / "data"
ML_ARTIFACTS = ML_ROOT / "artifacts"
MOCKS_DIR = ML_DATA / "mocks"
CONFIG_PATH = BACKEND_ROOT / "config.yaml"
MONGODB_URI_ENV, DATABASE_ENV = "MONGODB_URI", "HOI_OPS_DB"
MONGOMOCK_URI = "mongomock://"
# Which SYNTHETIC hotel dataset the backend serves (seed, roster, forecast, scoring, loop). Default:
# the fictional Himsagar Ridge Resort (ml/data/hotels/himsagar: 24 rooms, 19 rostered staff).
# "original" (aliases "default", "ml/data") = the first dataset in ml/data (45 rooms, 55 staff,
# demo heroes).
HOTEL_ENV, DEFAULT_HOTEL, ORIGINAL_HOTEL = "HOI_HOTEL_DATA", "himsagar", "original"
HOTEL_ALIASES = {"original": ORIGINAL_HOTEL, "default": ORIGINAL_HOTEL, "ml/data": ORIGINAL_HOTEL}
HOTELS_DIR = BACKEND_ROOT / "hotels"  # per-hotel overrides (<key>.yaml), merged over config.yaml


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShiftSpec(_Strict):
    start: int = Field(ge=0, le=23)
    hours: int = Field(gt=0, le=12)


class RosterWeights(_Strict):
    understaffed_hour: int = Field(ge=0)
    overtime_hour: int = Field(ge=0)
    weekend_spread: int = Field(ge=0)
    night_spread: int = Field(ge=0)
    protected_weekend_bonus: int = Field(ge=0)
    # Rolling rosters: penalty per person short of the next Monday's morning minimum among staff who
    # are rested for it (did not work a Sunday shift that breaks the rest rule before a morning).
    # 0 = off (the original hotel); SOFT, so it never makes a week infeasible.
    next_monday_rested: int = Field(default=0, ge=0)


class DeterministicSolve(_Strict):
    num_workers: int = Field(ge=1)
    interleave_search: bool
    max_deterministic_time: float = Field(gt=0)
    safety_seconds: float = Field(gt=0)


class RosterConfig(_Strict):
    demo_week: date
    seed: int
    time_limit_seconds: float = Field(gt=0)
    num_workers: int = Field(ge=1)
    deterministic: DeterministicSolve
    shifts: dict[str, ShiftSpec]
    department_shifts: dict[str, list[str]]
    demand_share: dict[str, dict[str, float]]
    min_headcount: int = Field(ge=0)
    # Per department-shift override of min_headcount (a hotel with 2 maintenance staff keeps the
    # evening on call: {maintenance: {evening: 0}}). Missing = min_headcount.
    min_headcount_by_shift: dict[str, dict[str, int]] = Field(default_factory=dict)
    required_skill: dict[str, str]
    min_rest_hours: int = Field(ge=0)
    max_consecutive_days: int = Field(ge=1, le=7)
    min_days_off: int = Field(ge=0, le=7)
    weekend_days: list[int]
    overtime_premium: float = Field(ge=1)
    weights: RosterWeights
    hotel: str = "original"  # which hotel dataset this roster config belongs to (not a rule)

    def min_on(self, department: str, shift: str) -> int:
        """HARD minimum headcount of one department-shift-day."""
        return self.min_headcount_by_shift.get(department, {}).get(shift, self.min_headcount)

    def rules_dump(self) -> dict:
        """The settings that define a roster problem (cache fingerprint). Fields left at their
        default (the per-shift override, the hotel key) are omitted, so the original hotel's
        fingerprints, and therefore its cached rosters, are unchanged."""
        return self.model_dump(mode="json", exclude_defaults=True, exclude={"hotel"})

    @model_validator(mode="after")
    def _consistent(self) -> RosterConfig:
        for dept, shifts in self.department_shifts.items():
            if set(shifts) - set(self.shifts):
                raise ValueError(f"roster: {dept} uses unknown shifts")
            share = self.demand_share.get(dept, {})
            if set(share) != set(shifts) or abs(sum(share.values()) - 1) > 1e-9:
                raise ValueError(f"roster: demand_share for {dept} must cover its shifts, sum 1")
        for dept, by_shift in self.min_headcount_by_shift.items():
            if set(by_shift) - set(self.department_shifts.get(dept, [])):
                raise ValueError(f"roster: min_headcount_by_shift for {dept} names unknown shifts")
            if any(n < 0 for n in by_shift.values()):
                raise ValueError("roster: min_headcount_by_shift must be >= 0")
        return self


class TaskConfig(_Strict):
    reminder_fractions: list[float]
    escalate_at_fraction: float = Field(gt=0, le=1)
    tick_seconds: float = Field(gt=0)
    default_due_minutes: int = Field(gt=0)
    scheduler_enabled: bool

    @model_validator(mode="after")
    def _fractions(self) -> TaskConfig:
        if not all(0 < f < 1 for f in self.reminder_fractions):
            raise ValueError("tasks.reminder_fractions must be in (0, 1)")
        return self


class MetricsConfig(_Strict):
    replacement_cost_inr: float = Field(ge=0)


class VoiceConfig(_Strict):
    clips_dir: str
    urgency_due_minutes: dict[str, int]
    department_owner: dict[str, str]


class BackendConfig(_Strict):
    database_name: str
    mock_env_var: str
    data_source: str
    roster: RosterConfig
    tasks: TaskConfig
    metrics: MetricsConfig
    voice: VoiceConfig


class HotelData(BaseModel):
    """One SYNTHETIC hotel dataset: where its ml output tables are and its generator config
    (rooms, workload standards, weekly hours). Read-only; never ml/data/internal/."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    key: str
    display_name: str
    data_dir: Path
    ml: GeneratorConfig

    @property
    def rooms(self) -> int:
        return self.ml.property.rooms

    @property
    def data_source(self) -> str:
        return f"{self.data_dir.relative_to(REPO_ROOT).as_posix()} (SYNTHETIC)"


def hotel_key(value: str | None = None) -> str:
    """The hotel to serve: the argument, else HOI_HOTEL_DATA, else the default (himsagar)."""
    raw = (value if value is not None else os.environ.get(HOTEL_ENV, "")).strip() or DEFAULT_HOTEL
    return HOTEL_ALIASES.get(raw.lower(), raw.lower())


@lru_cache(maxsize=8)
def _hotel_data(key: str) -> HotelData:
    if key == ORIGINAL_HOTEL:
        from ml.generator.config import load_config

        return HotelData(key=key, display_name="Default synthetic hill hotel (ml/data)",
                         data_dir=ML_DATA, ml=load_config())
    from ml.generator.hotel_variant import data_dir, load_hotel

    cfg, spec = load_hotel(key)
    path = data_dir(key)
    if not (path / "employee_v2.csv").exists():
        raise FileNotFoundError(f"{path} has no data: in ml/ run python run.py generate-hotel "
                                f"{key}")
    return HotelData(key=key, display_name=spec.display_name, data_dir=path, ml=cfg)


def hotel_data(key: str | None = None) -> HotelData:
    """The hotel dataset for `key` (default: HOI_HOTEL_DATA, else himsagar)."""
    return _hotel_data(hotel_key(key))


class Settings(BaseModel):
    """Runtime settings: the config plus which MongoDB to use and whether MOCK mode is on.

    mongodb_uri is a secret (never printed: excluded from repr); "mongomock://" means the
    in-memory mongomock client (development and tests only)."""

    config: BackendConfig
    mongodb_uri: str = Field(repr=False)
    database_name: str
    mock: bool
    hotel: str = ORIGINAL_HOTEL


REPLACED_KEYS = frozenset({"department_shifts", "demand_share", "min_headcount_by_shift",
                           "required_skill"})


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in REPLACED_KEYS:
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_backend_config(path: Path = CONFIG_PATH, hotel: str | None = None) -> BackendConfig:
    """config.yaml with the hotel's overrides (backend/hotels/<key>.yaml, if any) merged in.
    hotel: as hotel_key() (default HOI_HOTEL_DATA, else himsagar)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    key = hotel_key(hotel)
    override = HOTELS_DIR / f"{key}.yaml"
    if key != ORIGINAL_HOTEL and override.exists():
        raw = _merge(raw, yaml.safe_load(override.read_text(encoding="utf-8")) or {})
    raw["roster"]["hotel"] = key
    if key != ORIGINAL_HOTEL:
        raw["data_source"] = hotel_data(key).data_source
    return BackendConfig.model_validate(raw)


def make_settings(database_name: str | None = None, mock: bool | None = None,
                  mongodb_uri: str | None = None, hotel: str | None = None) -> Settings:
    """Arguments win over the environment (MONGODB_URI, HOI_OPS_DB, MOCK, HOI_HOTEL_DATA), which
    wins over config.yaml. No MONGODB_URI = mongomock."""
    key = hotel_key(hotel)
    cfg = load_backend_config(hotel=key)
    uri = mongodb_uri if mongodb_uri is not None else os.environ.get(MONGODB_URI_ENV, "")
    name = database_name or os.environ.get(DATABASE_ENV) or cfg.database_name
    is_mock = mock if mock is not None else os.environ.get(cfg.mock_env_var, "0") == "1"
    return Settings(config=cfg, mongodb_uri=uri.strip() or MONGOMOCK_URI, database_name=name,
                    mock=is_mock, hotel=key)


@lru_cache(maxsize=1)
def default_settings() -> Settings:
    return make_settings()
