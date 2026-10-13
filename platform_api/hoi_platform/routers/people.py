"""People: recognition points (positive-only incentives) and staffing requests to the tourism portal."""

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import Principal, roles, tenant_of
from ..schemas import StaffingRequestIn
from ..services import recognition, staffing, tenants, users

router = APIRouter(tags=["people"])
MONTH = Query(default=None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM (default: this month, hotel local time)")
PID = Query(default=None, max_length=64, description="Property id (default: the first property)")


@router.get("/recognition/summary")
def recognition_summary(
    month: str | None = MONTH, property_id: str | None = PID, p: Principal = Depends(roles("owner", "dept_head", "hr"))
) -> dict:
    """Team totals and per-person points / reward estimates (listed by id, not ranked). Department heads: own department rows."""
    tid = tenant_of(p)
    out = recognition.compute(tid, property_id, month)
    if p.role == "dept_head":
        dept = users.department_of(p.user_id)
        if not dept:
            raise HTTPException(403, "Your account has no department.")
        out["workers"] = [w for w in out["workers"] if w["department"] == dept]
        out["department"] = dept
    return out


@router.post("/staffing/requests", status_code=201)
def create_staffing_request(body: StaffingRequestIn, p: Principal = Depends(roles("owner", "dept_head", "hr"))) -> dict:
    """Store the request, then forward it to the tourism portal. Portal failure -> status pending_send (retry later)."""
    return staffing.create(tenant_of(p), p.username, **body.model_dump())


@router.get("/staffing/requests")
def list_staffing_requests(property_id: str | None = PID, p: Principal = Depends(roles("owner", "dept_head", "hr"))) -> list[dict]:
    tid = tenant_of(p)
    if property_id:
        tenants.get_property(tid, property_id)
    return staffing.list_requests(tid, property_id)


@router.post("/staffing/requests/{rid}/send")
def resend_staffing_request(rid: str, p: Principal = Depends(roles("owner", "dept_head", "hr"))) -> dict:
    """Retry sending a pending request."""
    return staffing.send(tenant_of(p), rid, p.username)
