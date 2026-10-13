"""District officer and state admin endpoints: applications, grievances, advisories, events, businesses, analytics.

Every handler resolves `district_scope()` first and passes the result into the service, so a district officer's
queries always filter on their own district (requests for another district get 403, items in another district 404).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..deps import Principal, district_scope, official, write_district
from ..schemas import AdvisoryIn, AdvisoryUpdateIn, BusinessStatusIn, DecisionIn, EventIn, EventUpdateIn, GrievanceUpdateIn
from ..services import advisories, analytics, applications, businesses, events, grievances

router = APIRouter(prefix="/api/v1/officer", tags=["officer"])
analytics_router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


# ------------------------------------------------------------------ applications
@router.get("/applications")
def list_applications(
    district: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    p: Principal = Depends(official),
) -> dict:
    return applications.officer_list(district_scope(p, district), status, kind, page, page_size)


@router.get("/applications/{app_id}")
def get_application(app_id: str, p: Principal = Depends(official)) -> dict:
    return applications.officer_get(app_id, district_scope(p, None))


@router.post("/applications/{app_id}/decision")
def decide(app_id: str, body: DecisionIn, p: Principal = Depends(official)) -> dict:
    return applications.decide(app_id, body.action, body.reason, district_scope(p, None), p.username)


# ------------------------------------------------------------------ grievances
@router.get("/grievances")
def list_grievances(
    district: str | None = None,
    status: str | None = None,
    overdue: bool | None = None,
    category: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    p: Principal = Depends(official),
) -> dict:
    return grievances.officer_list(district_scope(p, district), status, overdue, category, page, page_size)


@router.get("/grievances/{ticket_id}")
def get_grievance(ticket_id: str, p: Principal = Depends(official)) -> dict:
    return grievances.public(grievances.officer_get(ticket_id, district_scope(p, None)), officer=True)


@router.post("/grievances/{ticket_id}")
def update_grievance(ticket_id: str, body: GrievanceUpdateIn, p: Principal = Depends(official)) -> dict:
    return grievances.update(ticket_id, body.model_dump(), district_scope(p, None), p.username)


# ------------------------------------------------------------------ advisories
@router.get("/advisories")
def list_advisories(district: str | None = None, p: Principal = Depends(official)) -> dict:
    return advisories.list_scoped(district_scope(p, district))


@router.post("/advisories", status_code=201)
def create_advisory(body: AdvisoryIn, p: Principal = Depends(official)) -> dict:
    data = body.model_dump()
    district = write_district(p, data.pop("district"))
    return advisories.create(data, district, p.username, p.role)


@router.patch("/advisories/{adv_id}")
def update_advisory(adv_id: str, body: AdvisoryUpdateIn, p: Principal = Depends(official)) -> dict:
    return advisories.update(adv_id, body.model_dump(exclude_unset=True), district_scope(p, None), p.username)


@router.delete("/advisories/{adv_id}")
def withdraw_advisory(adv_id: str, p: Principal = Depends(official)) -> dict:
    """Withdraw (expire now). The record is kept."""
    return advisories.expire(adv_id, district_scope(p, None), p.username)


# ------------------------------------------------------------------ events
@router.get("/events")
def list_events(district: str | None = None, p: Principal = Depends(official)) -> dict:
    return events.list_scoped(district_scope(p, district))


@router.post("/events", status_code=201)
def create_event(body: EventIn, p: Principal = Depends(official)) -> dict:
    data = body.model_dump()
    district = write_district(p, data.pop("district"))
    return events.create(data, district, p.username)


@router.patch("/events/{event_id}")
def update_event(event_id: str, body: EventUpdateIn, p: Principal = Depends(official)) -> dict:
    return events.update(event_id, body.model_dump(exclude_unset=True), district_scope(p, None), p.username)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str, p: Principal = Depends(official)) -> None:
    events.delete(event_id, district_scope(p, None), p.username)


# ------------------------------------------------------------------ businesses
@router.get("/businesses")
def list_businesses(
    district: str | None = None,
    status: str | None = None,
    type: str | None = None,
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    p: Principal = Depends(official),
) -> dict:
    return businesses.officer_list(district_scope(p, district), status, type, q, page, page_size)


@router.post("/businesses/{business_id}/status")
def set_business_status(business_id: str, body: BusinessStatusIn, p: Principal = Depends(official)) -> dict:
    return businesses.set_status(business_id, body.status, body.reason, district_scope(p, None), p.username)


# ------------------------------------------------------------------ analytics (chart-ready, synthetic)
@analytics_router.get("/kpis")
def kpis(district: str | None = None, p: Principal = Depends(official)) -> dict:
    return analytics.kpis(district_scope(p, district))


@analytics_router.get("/rush")
def rush(district: str | None = None, top: int = Query(10, ge=1, le=24), p: Principal = Depends(official)) -> dict:
    return analytics.rush(district_scope(p, district), top)


@analytics_router.get("/occupancy")
def occupancy(
    district: str | None = None,
    type: str | None = Query(None, pattern="^(hotel|homestay)$"),
    days: int = Query(365, ge=7, le=730),
    granularity: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    p: Principal = Depends(official),
) -> dict:
    return analytics.occupancy_trend(district_scope(p, district), type, days, granularity)


@analytics_router.get("/market")
def market(district: str | None = None, p: Principal = Depends(official)) -> dict:
    return analytics.market(district_scope(p, district))


@analytics_router.get("/registrations")
def registrations(district: str | None = None, months: int = Query(24, ge=1, le=60), p: Principal = Depends(official)) -> dict:
    return analytics.registrations_monthly(district_scope(p, district), months)


@analytics_router.get("/grievances")
def grievance_stats(district: str | None = None, p: Principal = Depends(official)) -> dict:
    return analytics.grievance_stats(district_scope(p, district))


@analytics_router.get("/workforce")
def workforce(
    district: str | None = None, group_by: str = Query("district", pattern="^(district|type)$"), p: Principal = Depends(official)
) -> dict:
    return analytics.workforce(district_scope(p, district), group_by)
