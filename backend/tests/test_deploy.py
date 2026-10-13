"""Deployment configuration: CORS and the PORT-reading entrypoint (no app logic)."""

from backend import serve
from backend.main import cors_origins


def test_cors_allows_any_origin_by_default(client) -> None:
    r = client.get("/health", headers={"Origin": "https://example-frontend.app"})
    assert r.headers.get("access-control-allow-origin") == "*"


def test_cors_origins_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.app, https://b.app")
    assert cors_origins() == ["https://a.app", "https://b.app"]
    monkeypatch.delenv("CORS_ORIGINS")
    assert cors_origins() == ["*"]


def test_serve_reads_port_and_host(monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.delenv("HOST", raising=False)
    serve.main()
    assert seen == {"app": "backend.main:create_app", "factory": True, "host": "0.0.0.0",
                    "port": 10000}
