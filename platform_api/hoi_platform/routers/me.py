"""Employee self-service: my shifts and my department (used by the worker portal)."""

from fastapi import APIRouter, Depends, Query

from ..deps import HOTEL_MANAGERS, Principal, roles, tenant_of
from ..schemas import RosterPublishIn
from ..services import dispatch, performance

router = APIRouter(tags=["me"])


@router.get("/me/shifts")
def my_shifts(p: Principal = Depends(roles("worker"))) -> dict:
    tid = tenant_of(p)
    out = dispatch.shifts_for(tid, p.employee_id or p.username)
    ctx = dispatch.get_context(tid)
    out["department"] = ctx["working"].get(p.employee_id or "") or next(
        (s["department"] for s in dispatch.tenants.staff(tid) if s["employee_id"] == p.employee_id), None
    )
    out["on_shift_now"] = (p.employee_id or "") in ctx["working"]
    out["current_shift"] = {"day": ctx.get("day"), "shift": ctx.get("shift")}
    return out


@router.get("/me/performance")
def my_performance(days: int = Query(default=14, ge=1, le=90), p: Principal = Depends(roles("worker"))) -> dict:
    """The signed-in worker's own score and reasons only (never colleagues', never risk bands)."""
    out = performance.compute(tenant_of(p), days, worker=p.employee_id or p.username)
    me = out.pop("workers")[0]
    return {**out, **me}


@router.put("/dispatch/roster")
def publish_roster(body: RosterPublishIn, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    """Managers publish the week's roster so employees can see their own shifts."""
    return dispatch.publish_roster(tenant_of(p), body.week_start, body.assignments)
