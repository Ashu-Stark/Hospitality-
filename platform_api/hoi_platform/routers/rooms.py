"""Room status board (housekeeping) and per-room guest QR codes."""

import io

import segno
from fastapi import APIRouter, Depends, Query, Request, Response

from .. import config
from ..deps import HOTEL_MANAGERS, Principal, roles, tenant_of
from ..schemas import InspectIn, OutOfOrderIn, RoomIn, RoomsBulkIn
from ..services import rooms

router = APIRouter(prefix="/rooms", tags=["rooms"])
VIEW = (*HOTEL_MANAGERS, "storekeeper")


@router.get("")
def list_rooms(property_id: str | None = Query(default=None, max_length=64), p: Principal = Depends(roles(*VIEW))) -> dict:
    tid = tenant_of(p)
    rows = rooms.list_rooms(tid, property_id)
    if p.role not in ("owner", "platform_admin"):
        rows = [{k: v for k, v in r.items() if k != "guest_token"} for r in rows]
    return {"rooms": rows, "summary": rooms.summary(tid, property_id)}


@router.post("", status_code=201)
def add_room(body: RoomIn, p: Principal = Depends(roles("owner"))) -> dict:
    return rooms.add_room(tenant_of(p), body.number, body.floor, body.room_type)


@router.post("/bulk", status_code=201)
def bulk(body: RoomsBulkIn, p: Principal = Depends(roles("owner"))) -> dict:
    return {"added": rooms.bulk_add(tenant_of(p), body.floors, body.per_floor)}


@router.post("/{rid}/checkout")
def checkout(rid: str, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    return rooms.checkout(tenant_of(p), rid, p.username)


@router.post("/{rid}/check-in")
def check_in(rid: str, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    return rooms.check_in(tenant_of(p), rid, p.username)


@router.post("/{rid}/inspect")
def inspect(rid: str, body: InspectIn, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    return rooms.inspect(tenant_of(p), rid, body.passed, p.username, body.note)


@router.post("/{rid}/out-of-order")
def out_of_order(rid: str, body: OutOfOrderIn, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    return rooms.out_of_order(tenant_of(p), rid, body.reason, p.username, body.create_job)


@router.post("/{rid}/back-in-service")
def back(rid: str, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    return rooms.back_in_service(tenant_of(p), rid, p.username)


@router.get("/{rid}/qr.svg")
def qr(rid: str, request: Request, p: Principal = Depends(roles("owner"))) -> Response:
    """QR code for the room's guest request page. Print and place it in the room."""
    tid = tenant_of(p)
    r = next((x for x in rooms.list_rooms(tid) if x["id"] == rid), None)
    if not r:
        return Response(status_code=404)
    base = config.settings.public_base_url or str(request.base_url).rstrip("/")
    buf = io.BytesIO()
    segno.make(f"{base}/guest/?t={r['guest_token']}", error="m").save(buf, kind="svg", scale=6, border=2, dark="#0b0b0b")
    return Response(buf.getvalue(), media_type="image/svg+xml")
