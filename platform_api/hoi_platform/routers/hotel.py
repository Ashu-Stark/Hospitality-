"""Hotel profile (feeds the guest concierge) and the guest-services views (docs/HOSPITALITY_SUITE.md sections 1 and 4)."""

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import Principal, roles, tenant_of
from ..schemas import DecideIn, HotelProfileIn, PhotoProofIn
from ..services import guest, photo_proof, profiles, tenants, users

router = APIRouter(tags=["hotel"])
READ = ("owner", "dept_head", "hr", "storekeeper")
GUEST_VIEW = ("owner", "dept_head", "hr")
LATE_DEPTS = ("front_office", "housekeeping")


PID = Query(default=None, max_length=64, description="Property id (default: the first property)")


@router.get("/hotel/profile")
def get_profile(property_id: str | None = PID, p: Principal = Depends(roles(*READ))) -> dict:
    tid = tenant_of(p)
    if property_id:
        tenants.get_property(tid, property_id)  # 404 for another tenant's / unknown property
    return profiles.get(tid, property_id)


@router.put("/hotel/profile")
def put_profile(body: HotelProfileIn, property_id: str | None = PID, p: Principal = Depends(roles("owner", "dept_head"))) -> dict:
    tid = tenant_of(p)
    if property_id:
        tenants.get_property(tid, property_id)
    return profiles.put(tid, body.model_dump(), p.username, property_id)


@router.get("/hotel/settings/photo-proof")
def get_photo_proof(p: Principal = Depends(roles("owner", "dept_head"))) -> dict:
    """Which job kinds need a before / after photo in this hotel: {"kinds": [{kind, label, before, after}], "defaults": same}."""
    return photo_proof.get(tenant_of(p))


@router.put("/hotel/settings/photo-proof")
def put_photo_proof(body: PhotoProofIn, p: Principal = Depends(roles("owner"))) -> dict:
    """Owner only. Kinds left out keep their current rule; an unknown kind is a 422."""
    return photo_proof.put(tenant_of(p), [r.model_dump() for r in body.kinds], p.username)


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
