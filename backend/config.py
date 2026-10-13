"""Backend settings: config.yaml (validated) plus environment overrides."""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

BACKEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_ROOT.parent
ML_ROOT = REPO_ROOT / "ml"
ML_DATA = ML_ROOT / "data"
ML_ARTIFACTS = ML_ROOT / "artifacts"
MOCKS_DIR = ML_DATA / "mocks"
CONFIG_PATH = BACKEND_ROOT / "config.yaml"
MONGODB_URI_ENV, DATABASE_ENV = "MONGODB_URI", "HOI_OPS_DB"
MONGOMOCK_URI = "mongomock://"


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
    required_skill: dict[str, str]
    min_rest_hours: int = Field(ge=0)
    max_consecutive_days: int = Field(ge=1, le=7)
    min_days_off: int = Field(ge=0, le=7)
    weekend_days: list[int]
    overtime_premium: float = Field(ge=1)
    weights: RosterWeights

    @model_validator(mode="after")
    def _consistent(self) -> RosterConfig:
        for dept, shifts in self.department_shifts.items():
            if set(shifts) - set(self.shifts):
                raise ValueError(f"roster: {dept} uses unknown shifts")
            share = self.demand_share.get(dept, {})
            if set(share) != set(shifts) or abs(sum(share.values()) - 1) > 1e-9:
                raise ValueError(f"roster: demand_share for {dept} must cover its shifts, sum 1")
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


class Settings(BaseModel):
    """Runtime settings: the config plus which MongoDB to use and whether MOCK mode is on.

    mongodb_uri is a secret (never printed: excluded from repr); "mongomock://" means the
    in-memory mongomock client (development and tests only)."""

    config: BackendConfig
    mongodb_uri: str = Field(repr=False)
    database_name: str
    mock: bool


def load_backend_config(path: Path = CONFIG_PATH) -> BackendConfig:
    return BackendConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def make_settings(database_name: str | None = None, mock: bool | None = None,
                  mongodb_uri: str | None = None) -> Settings:
    """Arguments win over the environment (MONGODB_URI, HOI_OPS_DB, MOCK), which wins over
    config.yaml. No MONGODB_URI = mongomock."""
    cfg = load_backend_config()
    uri = mongodb_uri if mongodb_uri is not None else os.environ.get(MONGODB_URI_ENV, "")
    name = database_name or os.environ.get(DATABASE_ENV) or cfg.database_name
    is_mock = mock if mock is not None else os.environ.get(cfg.mock_env_var, "0") == "1"
    return Settings(config=cfg, mongodb_uri=uri.strip() or MONGOMOCK_URI, database_name=name,
                    mock=is_mock)


@lru_cache(maxsize=1)
def default_settings() -> Settings:
    return make_settings()
