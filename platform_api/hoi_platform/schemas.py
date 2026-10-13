"""Request bodies (validated by FastAPI/Pydantic). Responses are plain dicts from the services."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


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
    mode: str | None = Field(default=None, pattern="^(hotel|homestay)$")  # None: homestay up to 10 rooms (ASSUMED)


class RecognitionConfigIn(BaseModel):
    """Recognition points settings (positive only). Unset fields keep the ASSUMED defaults in services/recognition.py."""

    model_config = ConfigDict(extra="forbid")
    weights: dict[str, Annotated[int, Field(ge=0, le=1000)]] | None = None
    max_points_per_worker: int | None = Field(default=None, ge=1, le=100_000)
    min_jobs: int | None = Field(default=None, ge=0, le=1000)
    max_share: float | None = Field(default=None, gt=0, le=1)


class PropertySettingsIn(BaseModel):
    """Owner settings per property. portal_api_key is write-only ("" removes it); it is never returned or logged."""

    model_config = ConfigDict(extra="forbid")
    mode: str | None = Field(default=None, pattern="^(hotel|homestay)$")
    incentive_monthly_budget_cap: int | None = Field(default=None, ge=0, le=10_000_000)
    recognition_leaderboard_opt_in: bool | None = None
    recognition: RecognitionConfigIn | None = None
    portal_api_key: str | None = Field(default=None, max_length=200)


class StaffingRequestIn(BaseModel):
    """Ask the tourism portal's staffing partners for extra hands (no personal data: department/skill, dates, count)."""

    model_config = ConfigDict(extra="forbid")
    property_id: str | None = Field(default=None, max_length=64)
    department: str = Field(min_length=2, max_length=40, pattern=r"^[a-z_]+$")
    skill: str = Field(default="", max_length=60)
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    openings: int = Field(ge=1, le=50)
    note: str = Field(default="", max_length=500)
    source: str = Field(default="manual", pattern="^(manual|roster_shortage)$")


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
    property_id: str | None = Field(default=None, max_length=64)


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


# ------------------------------------------------------------------ hotel profile + guest concierge (docs/HOSPITALITY_SUITE.md)
HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_MOBILE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")


def _no_personal(v: str) -> str:
    """Profile text is shown to every guest: no e-mail addresses or mobile numbers (use contacts with an extension)."""
    v = v.strip()
    if _EMAIL.search(v) or _MOBILE.search(v.replace(" ", "")):
        raise ValueError("no e-mail addresses or mobile numbers in profile text; use a contact with a desk extension")
    return v


Short = Annotated[str, Field(max_length=80), AfterValidator(_no_personal)]
Medium = Annotated[str, Field(max_length=200), AfterValidator(_no_personal)]
Long = Annotated[str, Field(max_length=600), AfterValidator(_no_personal)]
Hours = Annotated[str, Field(max_length=40), AfterValidator(_no_personal)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LateCheckoutPolicy(_Strict):
    allowed: bool = True
    latest: str = Field(default="14:00", pattern=HHMM)
    note: Medium = "Subject to availability; manager approves"


class Wifi(_Strict):
    network: Short = ""
    password_hint: Short = ""


class Contact(_Strict):
    label: Short
    extension: str = Field(max_length=16, pattern=r"^[0-9+ \-]*$")


class Amenity(_Strict):
    name: Short
    hours: Hours = ""
    where: Short = ""
    note: Medium = ""


class DiningItem(_Strict):
    item: Short
    price_inr: float | None = Field(default=None, ge=0, le=100000)
    veg: bool | None = None
    hours: Hours = ""


class Policy(_Strict):
    title: Short
    text: Long


class Nearby(_Strict):
    name: Short
    distance_note: Short = ""
    tip: Medium = ""


class Faq(_Strict):
    q: Medium
    a: Long


class HotelProfileIn(_Strict):
    display_name: Short = Field(min_length=1)
    logo_url: str | None = Field(default=None, max_length=200, pattern=r"^(/|https://)[A-Za-z0-9._~/-]+$")
    # cover photo for the guest page and the admin header: a same-origin path or https URL, with its licence credit line
    cover_photo_url: str | None = Field(default=None, max_length=200, pattern=r"^(/|https://)[A-Za-z0-9._~/-]+$")
    cover_photo_credit: str = Field(default="", max_length=240)
    welcome: Long = ""
    checkin_time: str = Field(default="12:00", pattern=HHMM)
    checkout_time: str = Field(default="11:00", pattern=HHMM)
    late_checkout: LateCheckoutPolicy = LateCheckoutPolicy()
    wifi: Wifi = Wifi()
    contacts: list[Contact] = Field(default_factory=list, max_length=20)
    amenities: list[Amenity] = Field(default_factory=list, max_length=40)
    dining: list[DiningItem] = Field(default_factory=list, max_length=120)
    policies: list[Policy] = Field(default_factory=list, max_length=30)
    nearby: list[Nearby] = Field(default_factory=list, max_length=30)
    faq: list[Faq] = Field(default_factory=list, max_length=40)
    languages: list[Literal["en", "hi"]] = Field(default_factory=lambda: ["en", "hi"], min_length=1, max_length=2)
    synthetic: bool = False
    property_id: str | None = Field(default=None, max_length=40)  # ignored: always the token's tenant + first property
    updated_at: str | None = None  # ignored (server time)

    @model_validator(mode="after")
    def _late_after_checkout(self) -> HotelProfileIn:
        if self.late_checkout.allowed and self.late_checkout.latest <= self.checkout_time:
            raise ValueError("late_checkout.latest must be later than checkout_time")
        return self


class ChatTurn(BaseModel):
    role: Literal["user", "guest", "assistant"]
    text: str = Field(max_length=600)


class GuestChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    lang: str | None = Field(default=None, max_length=10)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class GuestActionIn(BaseModel):
    action: Literal["request", "checkout", "late_checkout", "feedback"]
    params: dict = Field(default_factory=dict)


class ExpressCheckoutIn(BaseModel):
    time: str = Field(pattern=HHMM)
    luggage_help: bool = False


class LateCheckoutIn(BaseModel):
    until: str = Field(pattern=HHMM)
    reason: str = Field(default="", max_length=200)


class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)
    lang: str = Field(default="en", max_length=10)


class DecideIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=200)


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    lang: str = Field(default="en", max_length=10)


class VoiceCommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    lang: str = Field(default="en", max_length=10)


class VoiceActIn(BaseModel):
    action: Literal["accept", "decline", "start", "report_issue"]
    params: dict = Field(default_factory=dict)
