"""API request / response models. Responses ARE the ml result types (re-exported, not copied),
so the API and the frontend mocks share one schema. All data is SYNTHETIC."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from ml.attrition.api import Action, AttritionScore, Driver, HeroInfo, RescoreResult
from ml.forecast.api import ForecastDay, ForecastResult
from ml.voice.api import VoiceResult

__all__ = [
    "Action", "AttritionScore", "Driver", "ForecastDay", "ForecastResult", "HeroInfo",
    "RescoreResult", "VoiceResult", "ScoreRequest", "RescoreRequest", "Health", "ModelVersion",
]


class ScoreRequest(BaseModel):
    week_start: date | None = None  # default: the latest scoring week
    employee_ids: list[str] | None = None  # default: everyone active that week


class RescoreRequest(BaseModel):
    employee_id: str
    feature_overrides: dict[str, float | str] = Field(default_factory=dict)
    week_start: date | None = None
    protected_weekends_off: int | None = None  # convenience: build the overrides for N weekends


class ModelVersion(BaseModel):
    name: str
    version: str
    dataset_sha256: str


class Health(BaseModel):
    status: str
    mock: bool
    models: list[ModelVersion]
    database: str  # "mongodb" or "mongomock" (never the URI)
    synthetic: bool = True
