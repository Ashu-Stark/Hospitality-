"""Sign-in, invite sign-up, demo accounts, token refresh/sign-out, impersonation."""

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config, ratelimit, security
from ..deps import Principal, platform_only, principal
from ..schemas import LoginIn, PrefsIn, RefreshIn, RegisterIn
from ..services import sessions, tenants, users

router = APIRouter(prefix="/auth", tags=["auth"])


def _limit(request: Request, bucket: str, extra: str = "") -> None:
    ratelimit.hit(f"{bucket}:{ratelimit.client_ip(request)}", config.settings.login_rate_per_minute)
    if extra:
        ratelimit.hit(f"{bucket}:user:{extra.lower()}", config.settings.login_rate_per_minute)


def _session(u: dict, *, refresh: bool = True, **kw) -> dict:
    tid = kw.get("tenant_override") or u["tenant_id"]
    out = {
        "token": security.issue_token(u, **kw),
        "expires_in": config.settings.access_ttl_minutes * 60,
        "user": users.public(u),
        "tenant": tenants.get_tenant(tid) if tid else None,
    }
    if refresh:
        out["refresh_token"] = sessions.issue(u["id"])
    return out


@router.post("/login")
def login(body: LoginIn, request: Request) -> dict:
    _limit(request, "login", body.username)
    return _session(users.authenticate(body.username, body.password))


@router.post("/register")
def register(body: RegisterIn, request: Request) -> dict:
    _limit(request, "register")
    return _session(users.redeem_invite(body.code, body.username, body.password, body.employee_id))


@router.post("/refresh")
def refresh(body: RefreshIn, request: Request) -> dict:
    """Exchange a refresh token for a new access token; the refresh token is rotated (old one stops working)."""
    _limit(request, "refresh")
    uid, new_raw = sessions.rotate(body.refresh_token)
    u = users.get(uid)
    if not u["active"]:
        sessions.revoke_all(uid)
        raise HTTPException(401, "This account is disabled.")
    users.check_tenant_active(u)
    out = _session(u, refresh=False)
    out["refresh_token"] = new_raw
    return out


@router.post("/logout", status_code=204)
def logout(body: RefreshIn) -> None:
    sessions.revoke(body.refresh_token)


@router.get("/demo-accounts")
def demo_accounts() -> list[dict]:
    if not config.settings.demo_login:
        return []
    out = [{"username": "platform", "label": "Platform admin", "description": "Onboard and manage hotel groups"}]
    return out + [{"username": u, "label": lbl, "description": d} for u, _r, _e, lbl, d in users.DEMO_ACCOUNTS]


@router.post("/demo/{username}")
def demo_login(username: str, request: Request) -> dict:
    """One-click demo sign-in. Disabled unless HOI_DEMO_LOGIN is true; only the seeded demo accounts qualify."""
    allowed = {"platform"} | {u for u, *_ in users.DEMO_ACCOUNTS}
    if not config.settings.demo_login or username not in allowed:
        raise HTTPException(404, "Not found")
    _limit(request, "demo")
    u = users.by_username(username)
    if not u:
        raise HTTPException(404, "Not found")
    users.check_tenant_active(u)
    tenants.audit(u["tenant_id"], username, "login.demo")
    return _session(u)


@router.get("/me")
def me(p: Principal = Depends(principal)) -> dict:
    return {
        "user": users.public(users.get(p.user_id)),
        "tenant_id": p.tenant_id,
        "impersonated_by": p.impersonated_by,
        "tenant": tenants.get_tenant(p.tenant_id) if p.tenant_id else None,
    }


@router.patch("/me/prefs")
def prefs(body: PrefsIn, p: Principal = Depends(principal)) -> dict:
    return users.set_prefs(p.user_id, body.prefs)


@router.post("/impersonate/{tid}")
def impersonate(tid: str, p: Principal = Depends(platform_only)) -> dict:
    """Platform admin opens a hotel workspace. The new token is scoped to that tenant and the action is audited."""
    t = tenants.get_tenant(tid)
    tenants.audit(tid, p.username, "platform.open_workspace", t["name"])
    return _session(users.get(p.user_id), refresh=False, tenant_override=tid, impersonated_by=p.username)
