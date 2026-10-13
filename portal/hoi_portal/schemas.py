"""Request bodies (pydantic). Unknown fields are rejected; strings are length-capped."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginIn(In):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class RegisterIn(In):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=10, max_length=200)


class RefreshIn(In):
    refresh_token: str = Field(min_length=10, max_length=200)


class GrievanceIn(In):
    category: str = Field(max_length=30)
    district: str = Field(max_length=40)
    business_reg_no: str | None = Field(default=None, max_length=30)
    description: str = Field(min_length=10, max_length=2000)
    contact: str | None = Field(default=None, max_length=120, description="Optional; visible to officers only.")


class TrackIn(In):
    ticket_id: str = Field(min_length=5, max_length=20)
    tracking_code: str = Field(pattern=r"^\d{6}$")


class ApplicationIn(In):
    business_name: str = Field(min_length=3, max_length=120)
    type: str = Field(max_length=30)
    district: str = Field(max_length=40)
    destination_id: str | None = Field(default=None, max_length=60)
    capacity: int = Field(ge=1, le=5000)
    beds: int | None = Field(default=None, ge=0, le=20000)
    languages: list[str] = Field(default_factory=list, max_length=10)
    documents: dict[str, bool] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=1000)


class ApplicationUpdateIn(In):
    business_name: str | None = Field(default=None, min_length=3, max_length=120)
    type: str | None = Field(default=None, max_length=30)
    district: str | None = Field(default=None, max_length=40)
    destination_id: str | None = Field(default=None, max_length=60)
    capacity: int | None = Field(default=None, ge=1, le=5000)
    beds: int | None = Field(default=None, ge=0, le=20000)
    languages: list[str] | None = Field(default=None, max_length=10)
    documents: dict[str, bool] | None = None
    notes: str | None = Field(default=None, max_length=1000)


class DecisionIn(In):
    action: str = Field(pattern=r"^(approve|request_changes|reject)$")
    reason: str | None = Field(default=None, max_length=1000)


class MonthlyOccupancyIn(In):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    rooms_available: int = Field(ge=0, le=5000)
    occupied_room_nights: int = Field(ge=0, le=200000)


class IngestIn(In):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    rooms_available: int = Field(ge=0, le=5000)
    rooms_occupied: int = Field(ge=0, le=5000)
    staff_count: int | None = Field(default=None, ge=0, le=5000)
    staff_flagged: int | None = Field(default=None, ge=0, le=5000)


class ApiKeyIn(In):
    label: str | None = Field(default=None, max_length=60)


class AdvisoryIn(In):
    kind: str = Field(default="road", pattern=r"^(road|weather|general)$")
    status: str | None = Field(default=None, pattern=r"^(open|caution|closed)$")
    title: str = Field(min_length=3, max_length=140)
    segment: str | None = Field(default=None, max_length=140)
    reason: str | None = Field(default=None, max_length=500)
    destination_id: str | None = Field(default=None, max_length=60)
    district: str | None = Field(default=None, max_length=40, description="State admin only; officers always post for their own district.")
    expires_at: datetime | None = None


class AdvisoryUpdateIn(In):
    kind: str | None = Field(default=None, pattern=r"^(road|weather|general)$")
    status: str | None = Field(default=None, pattern=r"^(open|caution|closed)$")
    title: str | None = Field(default=None, min_length=3, max_length=140)
    segment: str | None = Field(default=None, max_length=140)
    reason: str | None = Field(default=None, max_length=500)
    destination_id: str | None = Field(default=None, max_length=60)
    expires_at: datetime | None = None


class EventIn(In):
    name: str = Field(min_length=3, max_length=140)
    description: str | None = Field(default=None, max_length=1000)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    destination_ids: list[str] = Field(default_factory=list, max_length=10)
    crowd_impact: str = Field(default="low", pattern=r"^(low|medium|high)$")
    district: str | None = Field(default=None, max_length=40, description="State admin only.")


class EventUpdateIn(In):
    name: str | None = Field(default=None, min_length=3, max_length=140)
    description: str | None = Field(default=None, max_length=1000)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    destination_ids: list[str] | None = Field(default=None, max_length=10)
    crowd_impact: str | None = Field(default=None, pattern=r"^(low|medium|high)$")


class GrievanceUpdateIn(In):
    status: str | None = Field(default=None, pattern=r"^(received|assigned|in_progress|resolved|closed)$")
    note: str | None = Field(default=None, max_length=1000)
    public: bool = True
    assign_to: str | None = Field(default=None, max_length=60)


class BusinessStatusIn(In):
    status: str = Field(pattern=r"^(active|suspended)$")
    reason: str = Field(min_length=3, max_length=500)


class OfficerIn(In):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=10, max_length=200)
    district: str = Field(max_length=40)
    label: str | None = Field(default=None, max_length=80)


class UserActiveIn(In):
    active: bool
