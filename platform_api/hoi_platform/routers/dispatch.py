"""Live dispatch: shift snapshot, jobs, offers, photo proof."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile

from ..deps import HOTEL_MANAGERS, Principal, acting_employee, principal, roles, tenant_of
from ..schemas import ActAs, ContextIn, JobIn, LinkTaskIn
from ..services import dispatch, performance, photos, tenants, users

router = APIRouter(prefix="/dispatch", tags=["dispatch"])


def _act(p: Principal, tid: str, body_emp: str | None, action: str, jid: str) -> str:
    emp = acting_employee(p, body_emp)
    if p.role != "worker":
        tenants.audit(tid, p.username, f"job.{action}.as_worker", f"{jid} as {emp}")
    return emp


@router.put("/context")
def set_context(body: ContextIn, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    """Publish who is on shift (from the roster) and risk bands for the retention guard."""
    return dispatch.set_context(tenant_of(p), body.day, body.shift, body.working, body.bands, body.floors)


@router.get("/context")
def get_context(p: Principal = Depends(roles(*HOTEL_MANAGERS, "worker"))) -> dict:
    c = dispatch.get_context(tenant_of(p))
    if p.role == "worker":  # workers never see colleagues' risk bands
        c = {**c, "bands": {}}
    return c


@router.post("/jobs", status_code=201)
def create_job(body: JobIn, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    tid = tenant_of(p)
    pid = tenants.get_property(tid, body.property_id)["id"] if body.property_id else None
    return dispatch.create_job(tid, body.title, body.department, body.room, body.urgency, body.source, p.username, property_id=pid)


@router.get("/jobs")
def list_jobs(
    status: str | None = None, mine: bool = False, worker: str | None = None, p: Principal = Depends(roles(*HOTEL_MANAGERS, "worker"))
) -> list[dict]:
    tid = tenant_of(p)
    statuses = status.split(",") if status else None
    if p.role == "worker":
        worker = p.employee_id
    elif mine:
        raise HTTPException(422, "mine=true is for employees.")
    rows = dispatch.list_jobs(tid, statuses, worker)
    if p.role == "worker":
        rows = [{**r, "ranking": []} for r in rows]  # ranking contains colleagues' bands
    return rows


@router.post("/jobs/{jid}/accept")
def accept(jid: str, body: ActAs, p: Principal = Depends(roles(*HOTEL_MANAGERS, "worker"))) -> dict:
    tid = tenant_of(p)
    return dispatch.accept(tid, jid, _act(p, tid, body.employee_id, "accept", jid))


@router.post("/jobs/{jid}/decline")
def decline(jid: str, body: ActAs, p: Principal = Depends(roles(*HOTEL_MANAGERS, "worker"))) -> dict:
    tid = tenant_of(p)
    return dispatch.decline(tid, jid, _act(p, tid, body.employee_id, "decline", jid))


@router.post("/jobs/{jid}/start")
def start(jid: str, body: ActAs, p: Principal = Depends(roles(*HOTEL_MANAGERS, "worker"))) -> dict:
    tid = tenant_of(p)
    return dispatch.start(tid, jid, _act(p, tid, body.employee_id, "start", jid))


@router.post("/jobs/{jid}/complete")
def complete(jid: str, body: ActAs, p: Principal = Depends(roles(*HOTEL_MANAGERS, "worker"))) -> dict:
    tid = tenant_of(p)
    return dispatch.complete(tid, jid, _act(p, tid, body.employee_id, "complete", jid))


@router.post("/jobs/{jid}/offer")
def manual_offer(jid: str, body: ActAs, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    if not body.employee_id:
        raise HTTPException(422, "employee_id is required.")
    return dispatch.offer_to(tenant_of(p), jid, body.employee_id, p.username)


@router.post("/jobs/{jid}/retry")
def retry(jid: str, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    return dispatch.retry(tenant_of(p), jid, p.username)


@router.post("/jobs/{jid}/link-task")
def link_task(jid: str, body: LinkTaskIn, p: Principal = Depends(roles(*HOTEL_MANAGERS, "worker"))) -> dict:
    return dispatch.link_task(tenant_of(p), jid, body.task_id)


@router.post("/jobs/{jid}/photos", status_code=201)
async def upload_photo(
    jid: str,
    kind: str = Form(...),
    employee_id: str | None = Form(default=None),
    file: UploadFile = File(...),
    p: Principal = Depends(roles(*HOTEL_MANAGERS, "worker")),
) -> dict:
    tid = tenant_of(p)
    emp = _act(p, tid, employee_id, f"photo_{kind}", jid)
    return photos.save(tid, jid, kind, await file.read(), emp)


@router.get("/jobs/{jid}/photos")
def job_photos(jid: str, p: Principal = Depends(principal)) -> dict:
    tid = tenant_of(p)
    dispatch.get_job(tid, jid)
    return photos.for_job(tid, jid)


@router.get("/photos/{pid}")
def photo_file(pid: str, p: Principal = Depends(principal)) -> Response:
    return Response(photos.file_bytes(tenant_of(p), pid), media_type="image/jpeg")


@router.get("/performance")
def team_performance(days: int = Query(default=14, ge=1, le=90), p: Principal = Depends(roles("owner", "dept_head", "hr"))) -> dict:
    """Performance score per worker vs their own previous period (coaching aid). Department heads see their department only."""
    tid = tenant_of(p)
    dept = None
    if p.role == "dept_head":
        dept = users.department_of(p.user_id)
        if not dept:
            raise HTTPException(403, "Your account is not linked to a department. Ask the owner to set it.")
    return performance.compute(tid, days, department=dept)


@router.post("/reset", status_code=204)
def reset(p: Principal = Depends(roles("owner"))) -> None:
    tid = tenant_of(p)
    dispatch.reset_ops(tid)
    tenants.audit(tid, p.username, "dispatch.reset")
