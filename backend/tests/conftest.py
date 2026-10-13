import os

# Tests run offline on in-memory mongomock, never on Atlas: set before the app is imported.
os.environ["MONGODB_URI"] = "mongomock://"
os.environ.pop("HOI_ENV", None)

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
        yield c
    get_database(settings).client.drop_database(settings.database_name)


@pytest.fixture()
def client() -> TestClient:
    yield from _client(mock=False)


@pytest.fixture()
def mock_client() -> TestClient:
    yield from _client(mock=True)
