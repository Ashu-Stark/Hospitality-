"""Attrition model (SYNTHETIC data). Public interface: score, rescore."""

from ml.attrition.api import (
    AttritionScore,
    HeroInfo,
    RescoreResult,
    heroes,
    protected_weekends_off,
    rescore,
    score,
)

__all__ = ["AttritionScore", "HeroInfo", "RescoreResult", "heroes", "protected_weekends_off",
           "rescore", "score"]
