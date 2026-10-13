"""Authentication and authorization.

Every signed-in request carries `Authorization: Bearer <jwt>`. A district officer's district comes only from the
database user record (re-read on every request), never from the client. `district_scope()` is the single place
that turns a requested district into the district every officer query must filter on.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException

from . import mongo, security
from .seed.districts import BY_ID as DISTRICTS

OFFICIALS = ("district_officer", "state_admin")


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: str
    district: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == "state_admin"


def principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required.")
    try:
        c = security.decode_token(authorization.split(" ", 1)[1].strip())
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired. Sign in again.") from None
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid session.") from None
    u = mongo.db().users.find_one({"id": c.get("sub")}, {"active": 1, "role": 1, "district": 1, "username": 1})
    if not u or not u.get("active"):
        raise HTTPException(401, "This account is disabled.")
    return Principal(c["sub"], u["username"], u["role"], u.get("district"))


def roles(*allowed: str):
    def check(p: Principal = Depends(principal)) -> Principal:
        if p.role not in allowed:
            raise HTTPException(403, "Your role cannot do this.")
        return p

    return check


def optional_principal(authorization: str | None = Header(default=None)) -> Principal | None:
    """Signed-in principal when a valid bearer token is sent, else None (public endpoints with extras for members)."""
    if not authorization:
        return None
    try:
        return principal(authorization)
    except HTTPException:
        return None


business_only = roles("business")
seeker_only = roles("job_seeker")
official = roles(*OFFICIALS)
admin_only = roles("state_admin")


def district_scope(p: Principal, requested: str | None) -> str | None:
    """District every query must filter on. None = all districts (state admin only)."""
    if requested is not None and requested not in DISTRICTS:
        raise HTTPException(422, "Unknown district.")
    if p.role == "state_admin":
        return requested
    if p.role == "district_officer":
        if not p.district:
            raise HTTPException(403, "Your account has no district.")
        if requested and requested != p.district:
            raise HTTPException(403, "You can only see your own district.")
        return p.district
    raise HTTPException(403, "Officials only.")


def write_district(p: Principal, requested: str | None) -> str:
    """District for a new advisory/event: the officer's own; a state admin must name one."""
    d = district_scope(p, requested)
    if not d:
        raise HTTPException(422, "Choose a district.")
    return d
