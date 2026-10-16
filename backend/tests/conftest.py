import os

# Tests run offline on in-memory mongomock, never on Atlas: set before the app is imported.
os.environ["MONGODB_URI"] = "mongomock://"
os.environ.pop("HOI_ENV", None)
os.environ.pop("HOI_OPS_API_KEY", None)  # open API unless a test sets the key (test_auth.py)
os.environ.pop("LOCATIONIQ_API_KEY", None)  # geocoding: tests use a fake, never the network
# These tests were written for the original dataset (ml/data: 45 rooms, 55 staff, demo heroes);
# the fictional Himsagar hotel (the served default) is tested in test_hotel_himsagar.py.
os.environ["HOI_HOTEL_DATA"] = "original"

import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.config import make_settings  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.mongo import get_database  # noqa: E402


def fresh_settings(mock: bool = False):  # noqa: ANN201
    """A fresh, uniquely named mongomock database per test."""
    return make_settings(
        f"hoi_ops_test_{uuid.uuid4().hex[:12]}", mock=mock, mongodb_uri="mongomock://"
    )


def _client(mock: bool):  # noqa: ANN202
    settings = fresh_settings(mock)
    with TestClient(create_app(settings)) as c:
        c.app.state.weather = None  # alerts: tests never call the live weather API
        yield c
    get_database(settings).client.drop_database(settings.database_name)


@pytest.fixture()
def client() -> TestClient:
    yield from _client(mock=False)


@pytest.fixture()
def mock_client() -> TestClient:
    yield from _client(mock=True)
