"""People: recognition points (positive-only incentives), staffing requests to the tourism portal, and the staff signals
behind the staff-leaving estimate (HR record, leave marks, weekly facts; services/staff_signals.py)."""

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ..deps import Principal, roles, tenant_of
from ..schemas import HrRecordIn, LeaveMarkIn, StaffingRequestIn
from ..services import recognition, staff_signals, staffing, tenants, users

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


# ------------------------------------------------------------------ retention cover (high chance of leaving)
EMP = Path(max_length=20, pattern=r"^[A-Za-z0-9_-]+$")


def _cover_scope(p: Principal, employee_id: str) -> str:
    """Department heads only for their own department."""
    tid = tenant_of(p)
    if p.role == "dept_head" and staffing.staff_member(tid, employee_id)["department"] != users.department_of(p.user_id):
        raise HTTPException(403, "Only for your own department.")
    return tid


@router.get("/staffing/cover/{employee_id}")
def find_cover(employee_id: str = EMP, property_id: str | None = PID, p: Principal = Depends(roles("owner", "dept_head", "hr"))) -> dict:
    """High chance of leaving: how many job seekers on the tourism portal could fit this person's role (anonymised)."""
    return staffing.find_cover(_cover_scope(p, employee_id), p.username, employee_id, property_id)


@router.post("/staffing/cover/{employee_id}/post")
def post_cover_job(
    employee_id: str = EMP, property_id: str | None = PID, p: Principal = Depends(roles("owner", "dept_head", "hr"))
) -> dict:
    """The owner's one click when nobody fits: post one job for this role on the portal. Idempotent while that post is open."""
    return staffing.post_cover_job(_cover_scope(p, employee_id), p.username, employee_id, property_id)


# ------------------------------------------------------------------ staff signals (staff-leaving estimate)
DAY = r"^\d{4}-\d{2}-\d{2}$"


def _own_department(p: Principal) -> str | None:
    """Department heads: their own department only (403 without one). Owner / HR: the whole hotel (None)."""
    if p.role != "dept_head":
        return None
    dept = users.department_of(p.user_id)
    if not dept:
        raise HTTPException(403, "Your account has no department.")
    return dept


@router.get("/people/signals")
def staff_signals_feed(
    weeks: int = Query(default=staff_signals.DEFAULT_WEEKS, ge=1, le=staff_signals.MAX_WEEKS),
    include_current: bool = False,
    property_id: str | None = PID,
    p: Principal = Depends(roles("owner", "hr", "dept_head")),
) -> dict:
    """Weekly facts per person for the staff-leaving estimate (the ops API's POST /attrition/score `live_signals`).
    Department heads: own department; pay and the weekly answers are withheld (owner / HR only)."""
    dept = _own_department(p)
    return staff_signals.weekly_signals(
        tenant_of(p), weeks, include_current, department=dept, include_pay=dept is None, property_id=property_id
    )


@router.get("/people/hr")
def list_hr_records(p: Principal = Depends(roles("owner", "hr"))) -> list[dict]:
    """Owner / HR only: joining date, contract end, pay band / pay, last raise, left on, role code."""
    return [{k: v for k, v in r.items() if k != "tenant_id"} for r in staff_signals.hr_records(tenant_of(p))]


@router.get("/people/hr/{employee_id}")
def get_hr_record(employee_id: str = EMP, p: Principal = Depends(roles("owner", "hr"))) -> dict:
    return {k: v for k, v in staff_signals.hr_record(tenant_of(p), employee_id).items() if k != "tenant_id"}


@router.put("/people/hr/{employee_id}")
def put_hr_record(body: HrRecordIn, employee_id: str = EMP, p: Principal = Depends(roles("owner", "hr"))) -> dict:
    """Save the fields sent (null clears one). Pay values are never written to the audit log."""
    out = staff_signals.set_hr_record(tenant_of(p), p.username, employee_id, body.model_dump(exclude_unset=True))
    return {k: v for k, v in out.items() if k != "tenant_id"}


@router.get("/people/leave")
def list_leave(
    date_from: str = Query(pattern=DAY), date_to: str = Query(pattern=DAY), p: Principal = Depends(roles("owner", "hr", "dept_head"))
) -> list[dict]:
    """Leave / absence marks between two dates (no reasons). Department heads: own department."""
    return staff_signals.leave_marks(tenant_of(p), date_from, date_to, _own_department(p))


@router.post("/people/leave", status_code=201)
def mark_leave(body: LeaveMarkIn, p: Principal = Depends(roles("owner", "hr", "dept_head"))) -> dict:
    tid = _cover_scope(p, body.employee_id)
    return staff_signals.mark_leave(tid, p.username, body.employee_id, body.date, body.kind)


@router.delete("/people/leave/{employee_id}/{day}")
def unmark_leave(employee_id: str = EMP, day: str = Path(pattern=DAY), p: Principal = Depends(roles("owner", "hr", "dept_head"))) -> dict:
    return staff_signals.unmark_leave(_cover_scope(p, employee_id), p.username, employee_id, day)
