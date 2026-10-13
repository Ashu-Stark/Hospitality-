"""Uttarakhand Tourism & Hospitality Portal (concept) - API and web app host.

    uvicorn hoi_portal.main:app --port 8200            (from portal/)

Concept prototype for the AI-Tourism Hackathon 2026, not an official Government of Uttarakhand website.
JSON API under /api/v1 (see docs/PORTAL_API.md); the static web app is served from / .
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config, mongo, seed
from .errors import DomainError
from .routers import admin, auth, business, officer, public

STATIC = Path(__file__).resolve().parent / "static"
log = logging.getLogger("hoi.portal")
CSP = (
    "default-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
    "script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
NO_CSP_PATHS = ("/docs", "/openapi.json")  # Swagger UI (development only) loads its own assets


def create_app() -> FastAPI:
    s = config.settings
    problems = config.validate(s)
    if problems:
        raise RuntimeError("Unsafe production configuration:\n- " + "\n- ".join(problems))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        seed.ensure()
        yield

    app = FastAPI(
        title="Uttarakhand Tourism & Hospitality Portal (concept)",
        version=__version__,
        description="Concept prototype, not an official government website. Data is sample/synthetic unless marked otherwise.",
        docs_url=None if s.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if s.is_production else "/openapi.json",
        lifespan=lifespan,
    )
    if s.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=s.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
            allow_credentials="*" not in s.cors_origins,
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = (request.headers.get("x-request-id") or "")[:64] or uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - log and return a generic 500 without leaking internals
            log.exception("unhandled error rid=%s %s %s", rid, request.method, request.url.path)
            response = JSONResponse({"detail": "Internal error. Reference: " + rid}, status_code=500)
        ms = (time.perf_counter() - t0) * 1000
        log.info("rid=%s %s %s -> %s %.0fms", rid, request.method, request.url.path, response.status_code, ms)
        h = response.headers
        h["X-Request-ID"] = rid
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        h["X-Frame-Options"] = "DENY"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if not request.url.path.startswith(NO_CSP_PATHS):
            h["Content-Security-Policy"] = CSP
        if request.url.path.startswith("/api/") and not (request.url.path == "/api/v1/map/static" and response.status_code == 200):
            h["Cache-Control"] = "no-store"
        if s.is_production:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, e: DomainError) -> JSONResponse:
        return JSONResponse({"detail": e.message}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError) -> JSONResponse:
        errors = [{"field": ".".join(str(x) for x in err.get("loc", ())[1:]) or None, "message": err.get("msg")} for err in e.errors()]
        return JSONResponse({"detail": "Some fields are missing or invalid.", "errors": errors}, status_code=422)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "service": "hoi-portal", "version": app.version, "env": s.env, "demo_login": s.demo_login}

    @app.get("/ready", tags=["meta"])
    def ready() -> JSONResponse:
        try:
            mongo.db().command("ping")
            return JSONResponse({"status": "ready"})
        except Exception:  # noqa: BLE001
            return JSONResponse({"status": "not ready"}, status_code=503)

    for r in (public.router, auth.router, business.router, business.ingest_router, officer.router, officer.analytics_router, admin.router):
        app.include_router(r)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str) -> JSONResponse:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    if STATIC.exists():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")
    return app


app = create_app()
