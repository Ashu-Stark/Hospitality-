import io
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Offline tests: in-memory mongomock and a fresh database per test session (never the real cluster from the root .env).
os.environ["MONGODB_URI"] = "mongomock://"
os.environ["HOI_PLATFORM_DB"] = f"hoi_platform_test_{uuid.uuid4().hex[:8]}"
os.environ["HOI_DEMO_LOGIN"] = "true"
os.environ["HOI_ADMIN_PASSWORD"] = "admin-test-pw"
os.environ["HOI_LOGIN_RATE_PER_MINUTE"] = "100000"

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from hoi_platform import config  # noqa: E402

config.reload()
from hoi_platform.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())


def auth(client: TestClient, username: str) -> dict:
    r = client.post(f"/auth/demo/{username}")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def jpeg(color=(200, 80, 80)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(b, "JPEG")
    return b.getvalue()


@pytest.fixture
def owner(client):
    return auth(client, "demo.owner")


@pytest.fixture
def platform(client):
    return auth(client, "platform")


@pytest.fixture
def worker(client):
    return auth(client, "HS05")


@pytest.fixture
def hr(client):
    return auth(client, "demo.hr")


@pytest.fixture
def store(client):
    return auth(client, "demo.store")
