"""Sign-in, business self-registration, one-click demo accounts, token refresh (rotating) and sign-out."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config, mongo, ratelimit, security
from ..deps import Principal, principal
from ..schemas import LoginIn, RefreshIn, RegisterIn
from ..services import users

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _limit(request: Request, bucket: str, extra: str = "") -> None:
    ratelimit.hit(f"{bucket}:{ratelimit.client_ip(request)}", config.settings.login_rate_per_minute)
    if extra:
        ratelimit.hit(f"{bucket}:user:{extra.lower()}", config.settings.login_rate_per_minute)


def _session(u: dict, refresh_token: str | None = None) -> dict:
    return {
        "access_token": security.issue_token(u),
        "token_type": "bearer",
        "expires_in": config.settings.access_ttl_minutes * 60,
        "refresh_token": refresh_token or users.issue_refresh(u["id"]),
        "user": users.public(u),
    }


@router.post("/login")
def login(body: LoginIn, request: Request) -> dict:
    _limit(request, "login", body.username)
    return _session(users.authenticate(body.username, body.password))


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request) -> dict:
    """Business owners create their own account; officers are created by the state admin."""
    _limit(request, "register")
    u = users.create(body.username, body.password, "business")
    return _session(u)


@router.post("/refresh")
def refresh(body: RefreshIn, request: Request) -> dict:
    """Exchange a refresh token for a new access token. The refresh token is rotated: the old one stops working."""
    _limit(request, "refresh")
    uid, new_raw = users.rotate_refresh(body.refresh_token)
    u = users.get(uid)
    if not u["active"]:
        users.revoke_all(uid)
        raise HTTPException(401, "This account is disabled.")
    return _session(u, refresh_token=new_raw)


@router.post("/logout", status_code=204)
def logout(body: RefreshIn) -> None:
    users.revoke_refresh(body.refresh_token)


@router.get("/demo-accounts")
def demo_accounts() -> list[dict]:
    if not config.settings.demo_login:
        return []
    return [{"username": u, "role": r, "district": d, "label": lbl, "description": desc} for u, r, d, lbl, desc in users.DEMO_ACCOUNTS]


@router.post("/demo/{username}")
def demo_login(username: str, request: Request) -> dict:
    """One-click demo sign-in. Disabled unless PORTAL_DEMO_LOGIN is true (always refused in production)."""
    s = config.settings
    allowed = {u for u, *_ in users.DEMO_ACCOUNTS}
    if not s.demo_login or s.is_production or username not in allowed:
        raise HTTPException(404, "Not found")
    _limit(request, "demo")
    u = users.by_username(username)
    if not u or not u.get("active"):
        raise HTTPException(404, "Not found")
    mongo.audit(username, "login.demo", u["id"], "", u.get("district"))
    return _session(u)


@router.get("/me")
def me(p: Principal = Depends(principal)) -> dict:
    return {"user": users.public(users.get(p.user_id))}
