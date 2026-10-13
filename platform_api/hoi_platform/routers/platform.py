"""Platform console (HOI staff): onboard, configure and suspend hotel groups."""

from fastapi import APIRouter, Depends

from ..deps import Principal, platform_only
from ..schemas import InviteIn, TenantIn, TenantPatch
from ..services import tenants

router = APIRouter(prefix="/platform", tags=["platform"])


@router.get("/tenants")
def list_tenants(p: Principal = Depends(platform_only)) -> list[dict]:
    return tenants.list_tenants()


@router.post("/tenants", status_code=201)
def create_tenant(body: TenantIn, p: Principal = Depends(platform_only)) -> dict:
    t = tenants.create_tenant(
        body.name, plan=body.plan, brand_color=body.brand_color, api_base_url=body.api_base_url, use_mocks=body.use_mocks
    )
    if body.first_property:
        tenants.add_property(t["id"], body.first_property, "", body.rooms, 4)
    tenants.update_tenant(t["id"], onboarding_step=2 if body.first_property else 1)
    inv = tenants.create_invite(t["id"], "owner")
    tenants.audit(t["id"], p.username, "platform.tenant_created", f"plan={body.plan}")
    return {"tenant": tenants.get_tenant(t["id"]), "owner_invite": inv}


@router.patch("/tenants/{tid}")
def update_tenant(tid: str, body: TenantPatch, p: Principal = Depends(platform_only)) -> dict:
    fields = body.model_dump(exclude_none=True)
    if "plan" in fields and "settings" not in fields:  # plan change resets modules to the plan default
        s = tenants.get_tenant(tid)["settings"]
        s.pop("modules", None)
        fields["settings"] = s
    t = tenants.update_tenant(tid, **fields)
    tenants.audit(tid, p.username, "platform.tenant_updated", ",".join(sorted(fields)))
    return t


@router.delete("/tenants/{tid}", status_code=204)
def delete_tenant(tid: str, p: Principal = Depends(platform_only)) -> None:
    tenants.delete_tenant(tid)
    tenants.audit(None, p.username, "platform.tenant_deleted", tid)


@router.post("/tenants/{tid}/invites", status_code=201)
def owner_invite(tid: str, body: InviteIn, p: Principal = Depends(platform_only)) -> dict:
    inv = tenants.create_invite(tid, body.role)
    tenants.audit(tid, p.username, "platform.invite", body.role)
    return inv


@router.get("/audit")
def audit(tenant_id: str | None = None, limit: int = 300, p: Principal = Depends(platform_only)) -> list[dict]:
    return tenants.audit_log(tenant_id, min(limit, 2000))
