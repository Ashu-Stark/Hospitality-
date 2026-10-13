"""Offline test setup: mongomock (fresh database per test module), fake weather, no network."""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Force mongomock before anything imports the app (the root .env is never read by the portal).
os.environ["MONGODB_URI"] = "mongomock://"
os.environ["HOI_PORTAL_DB"] = "hoi_portal_test"
os.environ["HOI_ENV"] = "development"
os.environ["PORTAL_DEMO_LOGIN"] = "true"
os.environ["PORTAL_SEED_DEMO"] = "true"
os.environ["PORTAL_WEATHER_ENABLED"] = "true"
os.environ["PORTAL_LOGIN_RATE_PER_MINUTE"] = "100000"
os.environ["PORTAL_GRIEVANCE_RATE_PER_HOUR"] = "100000"
os.environ["PORTAL_TRACK_RATE_PER_MINUTE"] = "100000"
os.environ["PORTAL_INGEST_RATE_PER_MINUTE"] = "100000"
os.environ.pop("PORTAL_ADMIN_PASSWORD", None)
os.environ.pop("PORTAL_JWT_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402
from hoi_portal import config, mongo, ratelimit  # noqa: E402

config.reload()
from hoi_portal.main import create_app  # noqa: E402
from hoi_portal.services import crowd, weather  # noqa: E402

CALLS = {"n": 0}


def fake_forecast(lat: float, lon: float) -> dict:
    """Open-Meteo-shaped payload with heavy rain on day 2 and snow on day 4."""
    CALLS["n"] += 1
    days = [(date.today() + timedelta(days=i)).isoformat() for i in range(7)]
    return {
        "current": {"time": days[0] + "T10:00", "temperature_2m": 8.4, "weather_code": 3, "wind_speed_10m": 11.2},
        "daily": {
            "time": days,
            "temperature_2m_max": [12, 11, 9, 7, 6, 10, 12],
            "temperature_2m_min": [2, 1, 0, -2, -3, 0, 1],
            "precipitation_probability_max": [10, 90, 60, 40, 30, 20, 10],
            "precipitation_sum": [0, 64.0, 12.0, 3.0, 1.0, 0, 0],
            "snowfall_sum": [0, 0, 0, 7.5, 0, 0, 0],
            "weather_code": [3, 65, 61, 73, 71, 2, 1],
        },
    }


def _no_network(*a, **k):
    raise AssertionError("tests must not call the network")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr("httpx.get", _no_network)
    weather.set_fetcher(fake_forecast)
    yield
    weather.set_fetcher(fake_forecast)


@pytest.fixture(scope="module")
def client():
    mongo.reset()
    ratelimit.reset()
    crowd.invalidate()
    weather.set_fetcher(fake_forecast)
    with TestClient(create_app()) as c:
        yield c
    mongo.reset()


def login(client: TestClient, username: str) -> dict:
    r = client.post(f"/api/v1/auth/demo/{username}")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin(client):
    return login(client, "demo.admin")


@pytest.fixture
def officer(client):
    return login(client, "demo.officer.rudraprayag")


@pytest.fixture
def owner(client):
    return login(client, "demo.business")
