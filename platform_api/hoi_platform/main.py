"""HOI platform API.

    uvicorn hoi_platform.main:app --port 8100            (from platform_api/)

Owns tenants, accounts, dispatch, photo proof, rooms, inventory and the audit log, and serves two web apps:
    /worker/   employee portal (installable PWA, live camera)
    /guest/    guest request page reached by a room's QR code
The ML/forecast/roster service is separate (the team's FastAPI backend); the dashboard talks to both.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, mongo, seed
from .routers import auth, dispatch, inventory, me, platform, public, rooms, workspace
from .services.errors import DomainError

STATIC = Path(__file__).resolve().parent / "static"
log = logging.getLogger("hoi.platform")
CSP = (
    "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; style-src 'self'; "
    "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def create_app() -> FastAPI:
    s = config.settings
    problems = config.validate(s)
    if problems:
        raise RuntimeError("Unsafe production configuration:\n- " + "\n- ".join(problems))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = FastAPI(
        title="HOI platform API",
        version="1.1.0",
        description="Tenants, accounts, dispatch, photo proof, rooms, inventory and audit for Hospitality Operations Intelligence.",
        docs_url=None if s.is_production else "/docs",
        redoc_url=None,
    )
    if s.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=s.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials="*" not in s.cors_origins,
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - log and return a generic 500 without leaking internals
            log.exception("unhandled error rid=%s %s %s", rid, request.method, request.url.path)
            response = JSONResponse({"detail": "Internal error. Reference: " + rid}, status_code=500)
        ms = (time.perf_counter() - t0) * 1000
        log.info("rid=%s %s %s -> %s %.0fms", rid, request.method, request.url.path, response.status_code, ms)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if request.url.path.startswith(("/worker", "/guest")):
            response.headers["Content-Security-Policy"] = CSP
            response.headers["X-Frame-Options"] = "DENY"
        if s.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, e: DomainError) -> JSONResponse:
        return JSONResponse({"detail": e.message}, status_code=e.status)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {
            "status": "ok",
            "service": "hoi-platform",
            "version": app.version,
            "env": s.env,
            "demo_login": s.demo_login,
            "database": mongo.backend(),
        }

    @app.get("/ready", tags=["meta"])
    def ready() -> JSONResponse:
        try:
            mongo.ping()
            return JSONResponse({"status": "ready"})
        except Exception:  # noqa: BLE001 - never echo driver errors (they can contain the host name)
            log.warning("readiness check failed: database ping did not succeed")
            return JSONResponse({"status": "not ready"}, status_code=503)

    for r in (auth.router, platform.router, workspace.router, dispatch.router, inventory.router, rooms.router, public.router, me.router):
        app.include_router(r)

    for name in ("worker", "guest"):
        if (STATIC / name).exists():
            app.mount(f"/{name}", StaticFiles(directory=STATIC / name, html=True), name=name)
    if (STATIC / "shared").exists():
        app.mount("/shared", StaticFiles(directory=STATIC / "shared"), name="shared")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/worker/")

    mongo.db()  # connect and create indexes (idempotent) before serving
    seed.ensure_demo()
    return app


app = create_app()
