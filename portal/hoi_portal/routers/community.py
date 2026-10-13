"""Community linkages: local experiences (public list/detail/join request + host management from the business
dashboard), staffing agencies (public block offers, agency dashboard, responses to HOI staffing requests) and
in-portal notifications for business accounts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from .. import ratelimit
from ..deps import Principal, business_only
from ..schemas import (
    AgencyProfileIn,
    AgencyResponseIn,
    JoinDecisionIn,
    JoinRequestIn,
    LocalExperienceIn,
    LocalExperienceUpdateIn,
    StaffingOfferIn,
    StaffingOfferUpdateIn,
)
from ..services import local_experiences as lx
from ..services import staffing

public_router = APIRouter(prefix="/api/v1", tags=["public: community"])
host_router = APIRouter(prefix="/api/v1/business", tags=["business: local experiences + notifications"])
staffing_router = APIRouter(prefix="/api/v1/staffing", tags=["staffing agencies"])
JOIN_RATE_PER_HOUR = 20


# ------------------------------------------------------------------ public
@public_router.get("/local-experiences")
def local_list(
    type: str | None = Query(None, max_length=30),
    destination: str | None = Query(None, max_length=60),
    district: str | None = Query(None, max_length=40),
    month: int | None = Query(None, ge=1, le=12),
    q: str | None = Query(None, max_length=80),
    host: str | None = Query(None, max_length=40, description="Host business id"),
    page: int = Query(1, ge=1, le=100),
    page_size: int = Query(lx.PAGE_SIZE, ge=1, le=50),
) -> dict:
    """Community-hosted local experiences (sample data), filterable. Only hosts with an active registration are listed."""
    return lx.list_public(
        type=type, destination=destination, district=district, month=month, q=q, host=host, page=page, page_size=page_size
    )


@public_router.get("/local-experiences/{exp_id}")
def local_detail(exp_id: str) -> dict:
    return lx.get_public(exp_id)


@public_router.post("/local-experiences/{exp_id}/join", status_code=201)
def local_join(exp_id: str, body: JoinRequestIn, request: Request) -> dict:
    """Request to join (no payment). Only the host business sees the request and the contact given."""
    ratelimit.hit(f"join:{ratelimit.client_ip(request)}", JOIN_RATE_PER_HOUR, window_s=3600)
    return lx.request_join(exp_id, body.model_dump())


@public_router.get("/staffing/offers")
def staffing_offers(
    skill: str | None = Query(None, max_length=40),
    district: str | None = Query(None, max_length=40),
    month: int | None = Query(None, ge=1, le=12),
) -> dict:
    """Block offers of pooled workers from registered staffing agencies (counts only, never individual workers)."""
    return staffing.list_offers(skill, district, month)


# ------------------------------------------------------------------ business: host side
@host_router.get("/experiences")
def my_experiences(p: Principal = Depends(business_only)) -> dict:
    return lx.mine(p.user_id)


@host_router.post("/experiences", status_code=201)
def list_experience(body: LocalExperienceIn, p: Principal = Depends(business_only)) -> dict:
    return lx.create(p.user_id, p.username, body.model_dump())


@host_router.patch("/experiences/{exp_id}")
def edit_experience(exp_id: str, body: LocalExperienceUpdateIn, p: Principal = Depends(business_only)) -> dict:
    return lx.update(p.user_id, exp_id, p.username, body.model_dump(exclude_unset=True))


@host_router.delete("/experiences/{exp_id}")
def remove_experience(exp_id: str, p: Principal = Depends(business_only)) -> dict:
    return lx.delete(p.user_id, exp_id, p.username)


@host_router.get("/experience-requests")
def join_requests(status: str | None = Query(None, max_length=20), p: Principal = Depends(business_only)) -> dict:
    return lx.host_requests(p.user_id, status)


@host_router.post("/experience-requests/{req_id}")
def decide_join_request(req_id: str, body: JoinDecisionIn, p: Principal = Depends(business_only)) -> dict:
    return lx.decide(p.user_id, req_id, body.action, p.username)


@host_router.get("/notifications")
def my_notifications(p: Principal = Depends(business_only)) -> dict:
    return staffing.notifications(p.user_id)


@host_router.post("/notifications/{note_id}/read")
def read_notification(note_id: str, p: Principal = Depends(business_only)) -> dict:
    return staffing.mark_read(p.user_id, note_id)


# ------------------------------------------------------------------ staffing agencies (business accounts of type staffing_agency)
@staffing_router.get("/mine")
def agency_dashboard(p: Principal = Depends(business_only)) -> dict:
    """Own agencies, block offers, notifications and open HOI staffing requests that match the agency."""
    return staffing.agency_dashboard(p.user_id)


@staffing_router.patch("/agencies/{business_id}")
def agency_profile(business_id: str, body: AgencyProfileIn, p: Principal = Depends(business_only)) -> dict:
    return staffing.update_agency(p.user_id, business_id, body.model_dump(exclude_unset=True), p.username)


@staffing_router.post("/offers", status_code=201)
def post_offer(body: StaffingOfferIn, p: Principal = Depends(business_only)) -> dict:
    return staffing.create_offer(p.user_id, p.username, body.model_dump())


@staffing_router.patch("/offers/{offer_id}")
def edit_offer(offer_id: str, body: StaffingOfferUpdateIn, p: Principal = Depends(business_only)) -> dict:
    return staffing.update_offer(p.user_id, offer_id, body.model_dump(exclude_unset=True), p.username)


@staffing_router.post("/requests/{job_id}/respond", status_code=201)
def respond(job_id: str, body: AgencyResponseIn, p: Principal = Depends(business_only)) -> dict:
    """An agency says how many pooled workers it can supply for an HOI staffing request (repeat = update)."""
    return staffing.respond(p.user_id, job_id, body.model_dump(), p.username)
