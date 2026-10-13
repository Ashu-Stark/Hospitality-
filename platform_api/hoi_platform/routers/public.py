"""Unauthenticated endpoints for the guest QR page. Scoped by the room's random token; rate-limited."""

from fastapi import APIRouter, Request

from .. import ratelimit
from ..schemas import GuestRequestIn
from ..services import rooms

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/guest/{token}")
def guest(token: str, request: Request) -> dict:
    ratelimit.hit(f"guest-view:{ratelimit.client_ip(request)}", 60)
    return rooms.guest_view(token)


@router.post("/guest/{token}/requests", status_code=201)
def guest_request(token: str, body: GuestRequestIn, request: Request) -> dict:
    ratelimit.hit(f"guest-req:{ratelimit.client_ip(request)}", 10)
    return rooms.guest_request(token, body.key, body.note)
