"""Business owner endpoints (role `business`) and the HOI ingest endpoint (X-API-Key)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from .. import config, ratelimit
from ..deps import Principal, business_only
from ..schemas import ApiKeyIn, ApplicationIn, ApplicationUpdateIn, IngestIn, MonthlyOccupancyIn
from ..services import applications, businesses, ingest

router = APIRouter(prefix="/api/v1/business", tags=["business"])
ingest_router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


@router.get("/dashboard")
def dashboard(p: Principal = Depends(business_only)) -> dict:
    return businesses.dashboard(p.user_id)


@router.get("/businesses")
def my_businesses(p: Principal = Depends(business_only)) -> dict:
    items = businesses.owned(p.user_id)
    return {"items": items, "total": len(items)}


@router.get("/businesses/{business_id}")
def my_business(business_id: str, p: Principal = Depends(business_only)) -> dict:
    return businesses.owned_detail(p.user_id, business_id)


@router.post("/businesses/{business_id}/renew", status_code=201)
def renew(business_id: str, p: Principal = Depends(business_only)) -> dict:
    return applications.renew(p.user_id, p.username, business_id)


@router.post("/businesses/{business_id}/occupancy")
def submit_occupancy(business_id: str, body: MonthlyOccupancyIn, p: Principal = Depends(business_only)) -> dict:
    b = businesses.get_owned(p.user_id, business_id)
    return ingest.submit_month(b, body.month, body.rooms_available, body.occupied_room_nights, p.username)


@router.get("/businesses/{business_id}/occupancy")
def occupancy_history(business_id: str, p: Principal = Depends(business_only)) -> dict:
    b = businesses.get_owned(p.user_id, business_id)
    return {"business_id": b["id"], "months": ingest.monthly_history(b["id"], 24)}


@router.get("/businesses/{business_id}/api-keys")
def list_keys(business_id: str, p: Principal = Depends(business_only)) -> dict:
    return businesses.list_keys(p.user_id, business_id)


@router.post("/businesses/{business_id}/api-keys", status_code=201)
def create_key(business_id: str, body: ApiKeyIn, p: Principal = Depends(business_only)) -> dict:
    return businesses.create_key(p.user_id, business_id, body.label, p.username)


@router.delete("/businesses/{business_id}/api-keys/{key_id}")
def revoke_key(business_id: str, key_id: str, p: Principal = Depends(business_only)) -> dict:
    return businesses.revoke_key(p.user_id, business_id, key_id, p.username)


@router.get("/applications")
def my_applications(p: Principal = Depends(business_only)) -> dict:
    return applications.list_own(p.user_id)


@router.post("/applications", status_code=201)
def apply(body: ApplicationIn, p: Principal = Depends(business_only)) -> dict:
    return applications.create(p.user_id, p.username, body.model_dump())


@router.get("/applications/{app_id}")
def my_application(app_id: str, p: Principal = Depends(business_only)) -> dict:
    return applications.public(applications.get_own(p.user_id, app_id))


@router.put("/applications/{app_id}")
def resubmit(app_id: str, body: ApplicationUpdateIn, p: Principal = Depends(business_only)) -> dict:
    return applications.resubmit(p.user_id, p.username, app_id, body.model_dump(exclude_unset=True))


@ingest_router.post("/occupancy")
def ingest_occupancy(body: IngestIn, request: Request, x_api_key: str | None = Header(default=None)) -> dict:
    """HOI-run hotels report daily occupancy. Idempotent per (business, date): repeating a date replaces it."""
    ratelimit.hit(f"ingest:{ratelimit.client_ip(request)}", config.settings.ingest_rate_per_minute)
    return ingest.ingest(x_api_key, body.model_dump())
