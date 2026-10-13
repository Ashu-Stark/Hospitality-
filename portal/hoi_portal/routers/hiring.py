"""Hiring board endpoints.

/api/v1/jobs/*        public job board (+ match score for a signed-in job seeker), business job posts and applicants,
                      message threads (both parties)
/api/v1/candidates/*  candidate search, profiles, interest requests and shortlist (business with ACTIVE registration)
/api/v1/me/seeker/*   the job seeker's own profile, applications and interest requests
/api/v1/analytics/workforce-market  officials, aggregates only (k-anonymous)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from .. import config, ratelimit
from ..deps import Principal, business_only, district_scope, official, optional_principal, roles, seeker_only
from ..schemas import (
    InterestDecisionIn,
    InterestIn,
    JobApplicationStatusIn,
    JobApplyIn,
    JobIn,
    JobUpdateIn,
    MessageIn,
    SeekerProfileIn,
    SeekerProfileUpdateIn,
)
from ..services import hiring, hiring_analytics

jobs_router = APIRouter(prefix="/api/v1/jobs", tags=["hiring: jobs"])
candidates_router = APIRouter(prefix="/api/v1/candidates", tags=["hiring: candidates (business)"])
seeker_router = APIRouter(prefix="/api/v1/me/seeker", tags=["hiring: job seeker"])
market_router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
party = roles("job_seeker", "business")
HOUR, DAY = 3600, 86400
DATE = r"^\d{4}-\d{2}-\d{2}$"


def _seeker_id(p: Principal | None) -> str | None:
    return p.user_id if p and p.role == "job_seeker" else None


# ------------------------------------------------------------------ jobs (public + business)
@jobs_router.get("")
def list_jobs(
    skill: str | None = Query(None, max_length=40),
    district: str | None = Query(None, max_length=40),
    type: str | None = Query(None, pattern="^(seasonal|permanent|part_time)$"),
    month: int | None = Query(None, ge=1, le=12),
    q: str | None = Query(None, max_length=80),
    page: int = Query(1, ge=1),
    page_size: int = Query(hiring.PAGE_SIZE, ge=1, le=50),
    p: Principal | None = Depends(optional_principal),
) -> dict:
    return hiring.list_jobs(
        skill=skill, district=district, job_type=type, month=month, q=q, page=page, page_size=page_size, seeker_user_id=_seeker_id(p)
    )


@jobs_router.get("/meta")
def jobs_meta() -> dict:
    return hiring.vocab()


@jobs_router.get("/mine")
def my_jobs(p: Principal = Depends(business_only)) -> dict:
    return hiring.my_jobs(p.user_id)


@jobs_router.post("", status_code=201)
def post_job(body: JobIn, p: Principal = Depends(business_only)) -> dict:
    ratelimit.hit(f"jobpost:{p.user_id}", config.settings.job_post_rate_per_day, DAY)
    return hiring.create_job(p.user_id, p.username, body.model_dump())


@jobs_router.post("/applications/{app_id}/status")
def set_application_status(app_id: str, body: JobApplicationStatusIn, p: Principal = Depends(business_only)) -> dict:
    return hiring.set_application_status(p.user_id, app_id, body.status, p.username)


@jobs_router.get("/threads/{thread_id}")
def get_thread(thread_id: str, p: Principal = Depends(party)) -> dict:
    return hiring.thread(thread_id, p.user_id, p.role)


@jobs_router.post("/threads/{thread_id}", status_code=201)
def post_message(thread_id: str, body: MessageIn, p: Principal = Depends(party)) -> dict:
    ratelimit.hit(f"msg:{p.user_id}", config.settings.message_rate_per_hour, HOUR)
    return hiring.post_message(thread_id, p.user_id, p.role, body.text)


@jobs_router.get("/{job_id}")
def get_job(job_id: str, p: Principal | None = Depends(optional_principal)) -> dict:
    return hiring.get_job(job_id, seeker_user_id=_seeker_id(p), owner_user_id=p.user_id if p and p.role == "business" else None)


@jobs_router.patch("/{job_id}")
def update_job(job_id: str, body: JobUpdateIn, p: Principal = Depends(business_only)) -> dict:
    return hiring.update_job(p.user_id, job_id, body.model_dump(exclude_unset=True), p.username)


@jobs_router.get("/{job_id}/applications")
def job_applications(job_id: str, p: Principal = Depends(business_only)) -> dict:
    return hiring.job_applications(p.user_id, job_id)


@jobs_router.post("/{job_id}/apply", status_code=201)
def apply(job_id: str, body: JobApplyIn, p: Principal = Depends(seeker_only)) -> dict:
    ratelimit.hit(f"apply:{p.user_id}", config.settings.apply_rate_per_day, DAY)
    return hiring.apply(p.user_id, job_id, body.note)


# ------------------------------------------------------------------ candidates (business with an active registration)
@candidates_router.get("")
def search_candidates(
    skill: str | None = Query(None, max_length=40),
    district: str | None = Query(None, max_length=40),
    available_from: str | None = Query(None, pattern=DATE),
    available_to: str | None = Query(None, pattern=DATE),
    exp_min: int | None = Query(None, ge=0, le=40),
    language: str | None = Query(None, max_length=20),
    job_id: str | None = Query(None, max_length=20, description="Score against one of your job posts instead of the filters."),
    page: int = Query(1, ge=1),
    page_size: int = Query(hiring.PAGE_SIZE, ge=1, le=50),
    p: Principal = Depends(business_only),
) -> dict:
    return hiring.search_candidates(
        p.user_id,
        skill=skill,
        district=district,
        available_from=available_from,
        available_to=available_to,
        exp_min=exp_min,
        language=language,
        job_id=job_id,
        page=page,
        page_size=page_size,
    )


@candidates_router.get("/interests")
def sent_interests(p: Principal = Depends(business_only)) -> dict:
    return hiring.business_interests(p.user_id)


@candidates_router.get("/shortlist")
def get_shortlist(p: Principal = Depends(business_only)) -> dict:
    return hiring.shortlist(p.user_id)


@candidates_router.get("/{code}")
def candidate(code: str, job_id: str | None = Query(None, max_length=20), p: Principal = Depends(business_only)) -> dict:
    return hiring.candidate_detail(p.user_id, code, job_id)


@candidates_router.post("/{code}/interest", status_code=201)
def send_interest(code: str, body: InterestIn, p: Principal = Depends(business_only)) -> dict:
    ratelimit.hit(f"interest:{p.user_id}", config.settings.interest_rate_per_day, DAY)
    return hiring.send_interest(p.user_id, code, body.model_dump(), p.username)


@candidates_router.put("/{code}/shortlist")
def add_shortlist(code: str, p: Principal = Depends(business_only)) -> dict:
    return hiring.shortlist_add(p.user_id, code)


@candidates_router.delete("/{code}/shortlist")
def remove_shortlist(code: str, p: Principal = Depends(business_only)) -> dict:
    return hiring.shortlist_remove(p.user_id, code)


# ------------------------------------------------------------------ the job seeker's own data
@seeker_router.get("")
def seeker_dashboard(p: Principal = Depends(seeker_only)) -> dict:
    return hiring.seeker_dashboard(p.user_id)


@seeker_router.get("/profile")
def get_profile(p: Principal = Depends(seeker_only)) -> dict:
    return hiring.get_own(p.user_id)


@seeker_router.post("/profile", status_code=201)
def create_profile(body: SeekerProfileIn, request: Request, p: Principal = Depends(seeker_only)) -> dict:
    s = config.settings
    ratelimit.hit(f"profile:user:{p.user_id}", s.profile_rate_per_hour, HOUR)
    ratelimit.hit(f"profile:ip:{ratelimit.client_ip(request)}", s.profile_rate_per_hour * 4, HOUR)
    return hiring.create_profile(p.user_id, body.model_dump())


@seeker_router.patch("/profile")
def update_profile(body: SeekerProfileUpdateIn, p: Principal = Depends(seeker_only)) -> dict:
    return hiring.update_profile(p.user_id, body.model_dump(exclude_unset=True))


@seeker_router.delete("/profile")
def delete_profile(p: Principal = Depends(seeker_only)) -> dict:
    return hiring.delete_profile(p.user_id)


@seeker_router.get("/applications")
def my_applications(p: Principal = Depends(seeker_only)) -> dict:
    return hiring.my_applications(p.user_id)


@seeker_router.post("/applications/{app_id}/withdraw")
def withdraw(app_id: str, p: Principal = Depends(seeker_only)) -> dict:
    return hiring.withdraw(p.user_id, app_id)


@seeker_router.get("/interests")
def my_interests(p: Principal = Depends(seeker_only)) -> dict:
    return hiring.seeker_interests(p.user_id)


@seeker_router.post("/interests/{interest_id}")
def decide_interest(interest_id: str, body: InterestDecisionIn, p: Principal = Depends(seeker_only)) -> dict:
    return hiring.decide_interest(p.user_id, interest_id, body.action)


# ------------------------------------------------------------------ officials: aggregates only
@market_router.get("/workforce-market")
def workforce_market(district: str | None = None, p: Principal = Depends(official)) -> dict:
    return hiring_analytics.workforce_market(district_scope(p, district))
