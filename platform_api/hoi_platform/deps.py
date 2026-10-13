"""Request authentication and authorization.

Every request carries `Authorization: Bearer <jwt>`. The token's `tid` is the only source of the tenant:
clients never pass a tenant id for hotel data. Platform admins get a tenant-scoped token via impersonation.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException

from . import mongo, security

HOTEL_MANAGERS = ("owner", "dept_head")
INVENTORY_MANAGERS = ("owner", "storekeeper")


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: str
    tenant_id: str | None
    employee_id: str | None
    impersonated_by: str | None = None

    @property
    def is_platform(self) -> bool:
        return self.role == "platform_admin"


def principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required.")
    try:
        c = security.decode_token(authorization.split(" ", 1)[1])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired. Sign in again.") from None
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid session.") from None
    u = mongo.col("users").find_one({"id": c["sub"]}, {"active": 1, "tenant_id": 1})
    if not u or not u["active"]:
        raise HTTPException(401, "This account is disabled.")
    return Principal(c["sub"], c["usr"], c["role"], c.get("tid"), c.get("emp"), c.get("imp"))


def roles(*allowed: str):
    """Allow the listed roles (platform admins are always allowed)."""

    def check(p: Principal = Depends(principal)) -> Principal:
        if not p.is_platform and p.role not in allowed:
            raise HTTPException(403, "Your role cannot do this.")
        return p

    return check


def platform_only(p: Principal = Depends(principal)) -> Principal:
    if not p.is_platform:
        raise HTTPException(403, "Platform admins only.")
    return p


def tenant_of(p: Principal) -> str:
    if not p.tenant_id:
        raise HTTPException(400, "Open a hotel workspace first.")
    t = mongo.col("tenants").find_one({"id": p.tenant_id}, {"status": 1})
    if not t:
        raise HTTPException(404, "Workspace not found.")
    if t["status"] == "suspended" and not p.is_platform:
        raise HTTPException(403, "This hotel's workspace is suspended.")
    return p.tenant_id


def acting_employee(p: Principal, requested: str | None) -> str:
    """Workers always act as themselves. Managers may act as a worker in the preview screen (audited by the caller)."""
    if p.role == "worker":
        if requested and requested != p.employee_id:
            raise HTTPException(403, "You can only act on your own jobs.")
        return p.employee_id or p.username
    if p.is_platform or p.role in HOTEL_MANAGERS:
        if not requested:
            raise HTTPException(422, "employee_id is required when acting as a worker.")
        return requested
    raise HTTPException(403, "Your role cannot act on jobs.")
