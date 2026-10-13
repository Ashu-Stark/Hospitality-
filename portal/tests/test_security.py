"""Security: headers, production guard, demo login switch, sessions, rate limits, error format."""

import dataclasses

import pytest
from fastapi import HTTPException
from hoi_portal import config, ratelimit, security
from hoi_portal.main import create_app


def test_security_headers_and_request_id(client):
    for path in ("/", "/api/v1/meta"):
        r = client.get(path)
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "fonts.googleapis.com" in csp and "unsafe-inline" not in csp
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "no-referrer" and r.headers["x-request-id"]
    assert "concept" in client.get("/").text.lower()
    assert client.get("/api/v1/meta").headers["cache-control"] == "no-store"
    assert client.get("/api/v1/meta", headers={"X-Request-ID": "abc123"}).headers["x-request-id"] == "abc123"
    assert client.get("/ready").json()["status"] == "ready"


def _settings(**kw):
    base = dict(
        env="production",
        mongodb_uri="mongodb+srv://example.invalid/x",
        db_name="hoi_portal",
        jwt_secret="x" * 40,
        jwt_secret_from_env=True,
        access_ttl_minutes=30,
        refresh_ttl_days=14,
        demo_login=False,
        admin_password="a-strong-admin-pass",
        seed_demo=False,
        cors_origins=["https://portal.example.com"],
    )
    base.update(kw)
    return config.Settings(**base)


def test_production_guard_refuses_unsafe_settings():
    assert config.validate(_settings()) == []
    assert any("MONGODB_URI" in p for p in config.validate(_settings(mongodb_uri="mongomock://")))
    assert any("MONGODB_URI" in p for p in config.validate(_settings(mongodb_uri="")))
    assert any("JWT" in p for p in config.validate(_settings(jwt_secret="short")))
    assert any("JWT" in p for p in config.validate(_settings(jwt_secret_from_env=False)))
    assert any("DEMO" in p for p in config.validate(_settings(demo_login=True)))
    assert any("CORS" in p for p in config.validate(_settings(cors_origins=["*"])))
    assert any("ADMIN" in p for p in config.validate(_settings(admin_password="short")))
    assert (
        len(config.validate(_settings(mongodb_uri="mongomock://", jwt_secret="s", demo_login=True, cors_origins=[], admin_password=None)))
        == 5
    )
    assert config.validate(_settings(env="development", mongodb_uri="mongomock://", demo_login=True)) == []


def test_create_app_refuses_to_start_unsafe(monkeypatch):
    monkeypatch.setattr(config, "settings", _settings(mongodb_uri="mongomock://", demo_login=True))
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        create_app()


def test_demo_login_can_be_disabled(client, monkeypatch):
    assert len(client.get("/api/v1/auth/demo-accounts").json()) == 3
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, demo_login=False))
    assert client.get("/api/v1/auth/demo-accounts").json() == []
    assert client.post("/api/v1/auth/demo/demo.admin").status_code == 404
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, demo_login=True, env="production"))
    assert client.post("/api/v1/auth/demo/demo.admin").status_code == 404  # refused in production even if switched on
    monkeypatch.undo()
    assert client.post("/api/v1/auth/demo/not.a.demo.user").status_code == 404


def test_register_login_refresh_rotation_and_logout(client):
    r = client.post("/api/v1/auth/register", json={"username": "sec.test.owner", "password": "another-long-password"})
    assert r.status_code == 201
    assert client.post("/api/v1/auth/register", json={"username": "SEC.test.owner", "password": "another-long-password"}).status_code == 409
    assert client.post("/api/v1/auth/login", json={"username": "sec.test.owner", "password": "wrong-password"}).status_code == 401
    s = client.post("/api/v1/auth/login", json={"username": "sec.test.owner", "password": "another-long-password"}).json()
    assert s["token_type"] == "bearer" and s["expires_in"] == 1800 and s["user"]["role"] == "business"
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {s['access_token']}"}).json()["user"]["username"]
        == "sec.test.owner"
    )
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": s["refresh_token"]})
    assert r1.status_code == 200 and r1.json()["refresh_token"] != s["refresh_token"]
    # Reusing the rotated token revokes the whole family.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": s["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}).status_code == 401
    s2 = client.post("/api/v1/auth/login", json={"username": "sec.test.owner", "password": "another-long-password"}).json()
    assert client.post("/api/v1/auth/logout", json={"refresh_token": s2["refresh_token"]}).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": s2["refresh_token"]}).status_code == 401


def test_lockout_after_failed_logins(client):
    client.post("/api/v1/auth/register", json={"username": "lock.test", "password": "correct-horse-battery"})
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "lock.test", "password": "bad-password"})
    r = client.post("/api/v1/auth/login", json={"username": "lock.test", "password": "correct-horse-battery"})
    assert r.status_code == 401 and "Too many" in r.json()["detail"]


def test_disabled_user_token_stops_working(client, admin):
    r = client.post(
        "/api/v1/admin/officers",
        json={"username": "officer.test.chamoli", "password": "officer-pass-123", "district": "chamoli"},
        headers=admin,
    )
    assert r.status_code == 201 and r.json()["district"] == "chamoli"
    s = client.post("/api/v1/auth/login", json={"username": "officer.test.chamoli", "password": "officer-pass-123"}).json()
    h = {"Authorization": f"Bearer {s['access_token']}"}
    assert client.get("/api/v1/officer/grievances", headers=h).status_code == 200
    client.patch(f"/api/v1/admin/users/{r.json()['id']}", json={"active": False}, headers=admin)
    assert client.get("/api/v1/officer/grievances", headers=h).status_code == 401


def test_rate_limits(client, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, grievance_rate_per_hour=2, login_rate_per_minute=3))
    body = {"category": "other", "district": "almora", "description": "Rate limit test grievance."}
    codes = [client.post("/api/v1/grievances", json=body).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    r = client.post("/api/v1/grievances", json=body)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0 and "detail" in r.json()
    logins = [client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"}).status_code for _ in range(4)]
    assert logins[-1] == 429
    ratelimit.reset()
    with pytest.raises(HTTPException) as e:
        for _ in range(4):
            ratelimit.hit("unit", 3)
    assert e.value.status_code == 429
    ratelimit.reset()


def test_error_format_and_unknown_api_paths(client):
    r = client.post("/api/v1/business/applications", json={})
    assert r.status_code == 401 and r.json() == {"detail": "Sign in required."}
    v = client.post("/api/v1/grievances", json={"category": "other"})
    assert v.status_code == 422 and v.json()["detail"] and isinstance(v.json()["errors"], list)
    assert (
        client.post("/api/v1/grievances", json={"category": "other", "district": "almora", "description": "x" * 20, "evil": 1}).status_code
        == 422
    )
    assert client.get("/api/v1/does-not-exist").json() == {"detail": "Not found"}


def test_passwords_and_tokens_are_hashed(client):
    from hoi_portal import mongo

    u = mongo.db().users.find_one({"username": "sec.test.owner"}) or mongo.db().users.find_one({})
    assert len(u["pw_hash"]) == 64 and "password" not in str(u).lower().replace("pw_hash", "")
    assert security.ITERATIONS == 200_000
    assert all(len(t["token_hash"]) == 64 for t in mongo.db().refresh_tokens.find({}))
