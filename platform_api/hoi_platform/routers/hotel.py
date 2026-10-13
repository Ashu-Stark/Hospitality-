"""Hotel profile (feeds the guest concierge) and the guest-services views (docs/HOSPITALITY_SUITE.md sections 1 and 4)."""

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import Principal, roles, tenant_of
from ..schemas import DecideIn, HotelProfileIn
from ..services import guest, profiles, users

router = APIRouter(tags=["hotel"])
READ = ("owner", "dept_head", "hr", "storekeeper")
GUEST_VIEW = ("owner", "dept_head", "hr")
LATE_DEPTS = ("front_office", "housekeeping")


@router.get("/hotel/profile")
def get_profile(p: Principal = Depends(roles(*READ))) -> dict:
    return profiles.get(tenant_of(p))


@router.put("/hotel/profile")
def put_profile(body: HotelProfileIn, p: Principal = Depends(roles("owner", "dept_head"))) -> dict:
    return profiles.put(tenant_of(p), body.model_dump(), p.username)


@router.get("/guest-services/summary")
def summary(p: Principal = Depends(roles(*GUEST_VIEW))) -> dict:
    return guest.summary(tenant_of(p))


@router.get("/guest-services/late-checkouts")
def late_checkouts(
    status: str | None = Query(default=None, pattern=r"^[a-z,]{1,40}$"), p: Principal = Depends(roles(*GUEST_VIEW))
) -> list[dict]:
    return guest.late_checkouts(tenant_of(p), status)


@router.post("/guest-services/late-checkouts/{lid}/decide")
def decide(lid: str, body: DecideIn, p: Principal = Depends(roles("owner", "dept_head"))) -> dict:
    """Owner, or a department head of front office / housekeeping (platform admins via impersonation)."""
    tid = tenant_of(p)
    if p.role == "dept_head" and users.department_of(p.user_id) not in LATE_DEPTS:
        raise HTTPException(403, "Only front office or housekeeping heads (or the owner) can decide late checkouts.")
    return guest.decide_late(tid, lid, body.approve, body.note, p.username)


@router.get("/guest-services/feedback")
def feedback(days: int = Query(default=30, ge=1, le=365), p: Principal = Depends(roles(*GUEST_VIEW))) -> dict:
    return guest.feedback(tenant_of(p), days)


@router.get("/guest-services/checkouts")
def checkouts(date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"), p: Principal = Depends(roles(*GUEST_VIEW))) -> dict:
    return guest.checkouts(tenant_of(p), date)
