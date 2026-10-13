"""The signed-in user's hotel group: settings, properties, staff, team, invites, audit."""

from fastapi import APIRouter, Depends, HTTPException

from ..deps import Principal, principal, roles, tenant_of
from ..schemas import ActiveIn, InviteIn, PropertyIn, PropertySettingsIn, StaffImportIn, WorkspacePatch
from ..services import recognition, tenants, users

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("")
def get_workspace(p: Principal = Depends(principal)) -> dict:
    tid = tenant_of(p)
    return {**tenants.get_tenant(tid), "properties": tenants.properties(tid)}


@router.patch("")
def update_workspace(body: WorkspacePatch, p: Principal = Depends(roles("owner", "dept_head"))) -> dict:
    tid = tenant_of(p)
    fields = body.model_dump(exclude_none=True)
    if p.role == "dept_head" and set(fields) - {"assign_mode", "offer_seconds"}:
        raise HTTPException(403, "Department heads can only change dispatch settings.")
    settings = tenants.get_tenant(tid)["settings"]
    for k in ("assign_mode", "offer_seconds"):
        if k in fields:
            settings[k] = fields.pop(k)
    t = tenants.update_tenant(tid, settings=settings, **fields)
    tenants.audit(tid, p.username, "workspace.updated", ",".join(sorted(body.model_dump(exclude_none=True))))
    return t


@router.get("/properties")
def list_properties(p: Principal = Depends(principal)) -> list[dict]:
    return tenants.properties(tenant_of(p))


@router.post("/properties", status_code=201)
def add_property(body: PropertyIn, p: Principal = Depends(roles("owner"))) -> dict:
    tid = tenant_of(p)
    prop = tenants.add_property(tid, body.name, body.region, body.rooms, body.floors, body.mode)
    tenants.audit(tid, p.username, "property.added", f"{body.name} mode={prop['mode']}")
    return prop


@router.patch("/properties/{pid}")
def update_property(pid: str, body: PropertySettingsIn, p: Principal = Depends(roles("owner"))) -> dict:
    """Owner: homestay/hotel mode, incentive budget cap, leaderboard opt-in, tourism-portal API key (write-only)."""
    tid = tenant_of(p)
    fields = body.model_dump(exclude_none=True)
    if "recognition" in fields:
        current = tenants.get_property(tid, pid).get("recognition") or {}
        fields["recognition"] = {**current, **recognition.validate_config(fields["recognition"])}
    prop = tenants.update_property(tid, pid, **fields)
    # never log the key itself: only which settings changed
    tenants.audit(tid, p.username, "property.settings", f"{pid} " + ",".join(sorted(fields)))
    return prop


@router.get("/staff")
def list_staff(p: Principal = Depends(roles("owner", "hr", "dept_head", "storekeeper"))) -> list[dict]:
    return tenants.staff(tenant_of(p))


@router.post("/staff/import")
def import_staff(body: StaffImportIn, p: Principal = Depends(roles("owner"))) -> dict:
    tid = tenant_of(p)
    n = tenants.import_staff(tid, body.rows)
    tenants.audit(tid, p.username, "staff.imported", str(n))
    return {"imported": n, "total": len(tenants.staff(tid))}


@router.get("/users")
def list_users(p: Principal = Depends(roles("owner"))) -> list[dict]:
    return users.list_for_tenant(tenant_of(p))


@router.patch("/users/{uid}")
def set_user_active(uid: str, body: ActiveIn, p: Principal = Depends(roles("owner"))) -> dict:
    if uid == p.user_id:
        raise HTTPException(422, "You cannot disable your own account.")
    return users.set_active(tenant_of(p), uid, body.active, p.username)


@router.get("/invites")
def list_invites(p: Principal = Depends(roles("owner"))) -> list[dict]:
    return tenants.invites(tenant_of(p))


@router.post("/invites", status_code=201)
def create_invite(body: InviteIn, p: Principal = Depends(roles("owner"))) -> dict:
    tid = tenant_of(p)
    inv = tenants.create_invite(tid, body.role)
    tenants.audit(tid, p.username, "invite.created", body.role)
    return inv


@router.get("/audit")
def audit(limit: int = 300, p: Principal = Depends(roles("owner"))) -> list[dict]:
    return tenants.audit_log(tenant_of(p), min(limit, 2000))
