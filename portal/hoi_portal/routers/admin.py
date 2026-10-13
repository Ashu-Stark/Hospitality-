"""State admin: manage district officers and accounts, read the audit log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import mongo
from ..deps import Principal, admin_only
from ..schemas import OfficerIn, UserActiveIn
from ..services import users

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/users")
def list_users(
    role: str | None = Query(None, pattern="^(state_admin|district_officer|business|job_seeker)$"), p: Principal = Depends(admin_only)
) -> dict:
    items = users.list_users(role)
    return {"items": items, "total": len(items)}


@router.post("/officers", status_code=201)
def create_officer(body: OfficerIn, p: Principal = Depends(admin_only)) -> dict:
    u = users.create(body.username, body.password, "district_officer", body.district, body.label)
    return users.public(u)


@router.patch("/users/{user_id}")
def set_active(user_id: str, body: UserActiveIn, p: Principal = Depends(admin_only)) -> dict:
    if user_id == p.user_id and not body.active:
        raise HTTPException(409, "You cannot disable your own account.")
    return users.set_active(user_id, body.active, p.username)


@router.get("/audit")
def audit(limit: int = Query(100, ge=1, le=500), district: str | None = None, p: Principal = Depends(admin_only)) -> dict:
    f = {"district": district} if district else {}
    items = [{**mongo.clean(a), "ts": mongo.iso(a["ts"])} for a in mongo.db().audit_log.find(f).sort("ts", -1).limit(limit)]
    return {"items": items, "total": len(items)}
