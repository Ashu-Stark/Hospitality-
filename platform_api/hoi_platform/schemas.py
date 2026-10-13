"""Request bodies (validated by FastAPI/Pydantic). Responses are plain dicts from the services."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class RegisterIn(BaseModel):
    code: str = Field(min_length=4, max_length=40)
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=6, max_length=200)
    employee_id: str | None = Field(default=None, max_length=40)


class PrefsIn(BaseModel):
    prefs: dict


class TenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    plan: str = "starter"
    brand_color: str = Field(default="#1f6fe5", pattern=r"^#[0-9a-fA-F]{6}$")
    api_base_url: str | None = None
    use_mocks: bool = True
    first_property: str | None = None
    rooms: int = Field(default=40, ge=1, le=5000)


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    plan: str | None = None
    brand_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    api_base_url: str | None = None
    use_mocks: bool | None = None
    status: str | None = None
    onboarding_step: int | None = Field(default=None, ge=0, le=10)
    onboarded: bool | None = None
    settings: dict | None = None


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    brand_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    api_base_url: str | None = None
    use_mocks: bool | None = None
    onboarding_step: int | None = Field(default=None, ge=0, le=10)
    onboarded: bool | None = None
    assign_mode: str | None = Field(default=None, pattern="^(auto|manual)$")
    offer_seconds: int | None = Field(default=None, ge=10, le=600)


class PropertyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    region: str = ""
    rooms: int = Field(ge=1, le=5000)
    floors: int = Field(default=3, ge=1, le=200)


class StaffImportIn(BaseModel):
    rows: list[dict]


class InviteIn(BaseModel):
    role: str


class ActiveIn(BaseModel):
    active: bool


class ContextIn(BaseModel):
    day: str | None = None
    shift: str | None = None
    working: dict[str, str]
    bands: dict[str, str] = {}
    floors: int = Field(default=4, ge=1, le=200)


class JobIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    department: str | None = None
    room: str | None = Field(default=None, max_length=12)
    urgency: str = "medium"
    source: str = "manual"


class ActAs(BaseModel):
    employee_id: str | None = None


class LinkTaskIn(BaseModel):
    task_id: str


class LinesIn(BaseModel):
    lines: dict[str, float]


class RequestIn(BaseModel):
    department: str
    lines: dict[str, float]
    location_id: str | None = None
    room: str | None = None
    note: str = ""
    job_id: str | None = None


class FulfilIn(BaseModel):
    issued: dict[str, float]
    from_location: str


class RejectIn(BaseModel):
    note: str = ""


class POIn(BaseModel):
    supplier_id: str
    lines: dict[str, float]
    note: str = ""


class POStatusIn(BaseModel):
    status: str


class ReceiveIn(BaseModel):
    received: dict[str, float]
    location_id: str


class MoveIn(BaseModel):
    item_id: str
    location_id: str
    qty: float = Field(gt=0)
    reason: str = ""
    ref: str = ""
    department: str | None = None
    room: str | None = None


class TransferIn(BaseModel):
    item_id: str
    from_location: str
    to_location: str
    qty: float = Field(gt=0)


class CountStartIn(BaseModel):
    location_id: str


class CountPostIn(BaseModel):
    counted: dict[str, float]


class ItemIn(BaseModel):
    sku: str
    name: str
    category: str
    unit: str = "pc"
    unit_cost: float = Field(ge=0)
    par: float = Field(ge=0)
    reorder_point: float = Field(ge=0)
    supplier_id: str | None = None
    per_occ_room: float = Field(default=0, ge=0)
    department: str | None = None
    hsn: str | None = Field(default=None, max_length=8, pattern=r"^[0-9]{4,8}$")
    gst_rate: float = 0


class LocationIn(BaseModel):
    name: str
    kind: str = "store"


class SupplierIn(BaseModel):
    name: str
    lead_days: int = Field(default=3, ge=0, le=120)
    gstin: str | None = None
    interstate: bool = False


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class RoomIn(BaseModel):
    number: str = Field(min_length=1, max_length=8)
    floor: int | None = Field(default=None, ge=0, le=200)
    room_type: str = "standard"


class RoomsBulkIn(BaseModel):
    floors: int = Field(ge=1, le=60)
    per_floor: int = Field(ge=1, le=60)


class InspectIn(BaseModel):
    passed: bool
    note: str = Field(default="", max_length=140)


class OutOfOrderIn(BaseModel):
    reason: str = Field(min_length=2, max_length=140)
    create_job: bool = True


class GuestRequestIn(BaseModel):
    key: str = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=140)


class RosterPublishIn(BaseModel):
    week_start: str | None = None
    assignments: list[dict]
