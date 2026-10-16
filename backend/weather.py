"""Live daily weather forecast for the hotel's location (Open-Meteo, no API key).

Open-Meteo's free API is for non-commercial use (its terms; data under CC BY 4.0, attribution
"Weather data by Open-Meteo.com"). Only the configured coordinates are sent: no guest, staff
or hotel data. Results are cached in-process for cache_minutes. Tests use a fake fetcher and
never call the network. Weather days are REAL calendar days (today onwards), unlike the
SYNTHETIC demo calendar the other alerts use; the alert text says so.
"""

from __future__ import annotations

import time
from datetime import date

import httpx
from pydantic import BaseModel

from backend.config import WeatherConfig

DAILY = "precipitation_sum,snowfall_sum,precipitation_probability_max,weather_code"


class WeatherDay(BaseModel):
    date: date
    rain_mm: float
    snow_cm: float
    rain_chance_pct: float | None = None
    weather_code: int | None = None


class WeatherUnavailable(RuntimeError):
    pass


class OpenMeteo:
    """Callable: () -> list[WeatherDay] for the configured location (next 7 days)."""

    def __init__(self, cfg: WeatherConfig) -> None:
        self.cfg = cfg
        self._cache: tuple[float, list[WeatherDay]] | None = None

    def __call__(self) -> list[WeatherDay]:
        if not self.cfg.enabled:
            raise WeatherUnavailable("weather alerts are switched off (alerts.weather.enabled)")
        now = time.monotonic()
        if self._cache and now - self._cache[0] < self.cfg.cache_minutes * 60:
            return self._cache[1]
        params = {"latitude": self.cfg.latitude, "longitude": self.cfg.longitude,
                  "daily": DAILY, "timezone": "Asia/Kolkata", "forecast_days": 7}
        try:
            r = httpx.get(self.cfg.url, params=params, timeout=self.cfg.timeout_seconds)
            r.raise_for_status()
            days = parse(r.json())
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            raise WeatherUnavailable(f"weather forecast not available ({type(e).__name__})") from e
        self._cache = (now, days)
        return days


def parse(payload: dict) -> list[WeatherDay]:
    d = payload["daily"]
    n = len(d["time"])

    def col(name: str) -> list:
        return d.get(name) or [None] * n

    return [WeatherDay(date=date.fromisoformat(t), rain_mm=float(r or 0), snow_cm=float(s or 0),
                       rain_chance_pct=p, weather_code=c)
            for t, r, s, p, c in zip(d["time"], col("precipitation_sum"), col("snowfall_sum"),
                                     col("precipitation_probability_max"), col("weather_code"),
                                     strict=True)]
