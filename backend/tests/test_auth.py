"""Shared-secret check (backend/auth.py): open when HOI_OPS_API_KEY is unset, X-HOI-Key
required when set. The key below is a test value, not a real one."""

from backend.auth import HEADER, KEY_ENV

TEST_KEY = "test-only-key-not-a-secret"


def test_open_when_key_unset(client) -> None:
    assert client.get("/retention/plan").status_code == 200
    assert client.get("/health").status_code == 200


def test_key_required_when_configured(client, monkeypatch) -> None:
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    for method, path in [("GET", "/retention/plan"), ("GET", "/interventions"),
                         ("POST", "/attrition/score"), ("GET", "/tasks"),
                         ("GET", "/metrics/overview"), ("POST", "/demo/reset")]:
        r = client.request(method, path, json={} if method == "POST" else None)
        assert r.status_code == 401, (method, path, r.status_code)
        assert HEADER in r.json()["detail"]
    assert client.get("/retention/plan", headers={HEADER: "wrong"}).status_code == 401
    assert client.get("/retention/plan", headers={HEADER: TEST_KEY}).status_code == 200
    assert client.post("/attrition/score", json={}, headers={HEADER: TEST_KEY}).status_code == 200


def test_health_and_preflight_stay_open(client, monkeypatch) -> None:
    monkeypatch.setenv(KEY_ENV, TEST_KEY)
    assert client.get("/health").status_code == 200
    r = client.options("/retention/plan", headers={"Origin": "https://example.org",
                                                    "Access-Control-Request-Method": "GET",
                                                    "Access-Control-Request-Headers": HEADER})
    assert r.status_code == 200
    # a 401 still carries the CORS header, so a browser caller sees the real reason
    r = client.get("/retention/plan", headers={"Origin": "https://example.org"})
    assert r.status_code == 401 and r.headers.get("access-control-allow-origin") == "*"
