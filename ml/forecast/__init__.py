"""Occupancy forecasting (SYNTHETIC data). Public interface: predict."""

from ml.forecast.api import ForecastDay, ForecastResult, predict

__all__ = ["ForecastDay", "ForecastResult", "predict"]
