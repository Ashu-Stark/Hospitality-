"""Shared-secret check for the ops / ML API (staff ids, chance-of-leaving scores, retention
talking points).

HOI_OPS_API_KEY (env, a secret: never print, log or commit it):
  * unset or empty  -> every request is allowed (local runs and tests, as before);
  * set             -> every request except the open paths below must send the same value in
                       the X-HOI-Key header, otherwise 401.
The key is read per request. Callers: the dashboard (dashboard/lib/api_client.py, same env var
name) and scripts/scenario_report.py --live.
"""

from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

KEY_ENV = "HOI_OPS_API_KEY"
HEADER = "X-HOI-Key"
OPEN_PATHS = frozenset({"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


def configured_key() -> str:
    return os.environ.get(KEY_ENV, "").strip()


def allowed(path: str, method: str, sent: str | None) -> bool:
    key = configured_key()
    # CORS preflights (OPTIONS) never carry custom headers
    if not key or method == "OPTIONS" or path in OPEN_PATHS:
        return True
    return bool(sent) and hmac.compare_digest(sent.strip().encode(), key.encode())


def install(app: FastAPI) -> None:
    """Add the check as an inner middleware. Call it BEFORE adding CORS, so CORS wraps it and a
    401 still carries the CORS headers."""

    @app.middleware("http")
    async def require_key(request: Request, call_next):  # noqa: ANN001, ANN202
        if allowed(request.url.path, request.method, request.headers.get(HEADER)):
            return await call_next(request)
        return JSONResponse({"detail": f"Missing or wrong {HEADER} header."}, status_code=401)
