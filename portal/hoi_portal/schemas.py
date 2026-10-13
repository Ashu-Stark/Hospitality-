"""Request bodies (pydantic). Unknown fields are rejected; strings are length-capped."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginIn(In):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class RegisterIn(In):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=10, max_length=200)
    role: str = Field(default="business", pattern=r"^(business|job_seeker)$", description="business (default) or job_seeker")


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


# ------------------------------------------------------------------ hiring board
DATE = r"^\d{4}-\d{2}-\d{2}$"
# Never collected (privacy by design). Sending any of these is rejected with a clear message, not silently dropped.
PROTECTED_FIELDS = frozenset(
    {
        "gender", "sex", "age", "dob", "date_of_birth", "birth_date", "birthdate", "birth_year", "religion", "caste",
        "category_caste", "community", "marital_status", "married", "spouse", "children", "family", "family_status",
        "photo", "photo_url", "picture", "image", "avatar", "address", "home_address", "pincode", "aadhaar", "father_name",
        "mother_name", "height", "weight", "disability", "health", "nationality",
    }
)  # fmt: skip
PROTECTED_MESSAGE = (
    "This portal does not collect gender, age or date of birth, religion, caste, marital or family status, photos, "
    "addresses or ID numbers. Remove: "
)


class NoProtected(In):
    @model_validator(mode="before")
    @classmethod
    def _reject_protected(cls, data):
        if isinstance(data, dict):
            bad = sorted(k for k in data if str(k).strip().lower() in PROTECTED_FIELDS)
            if bad:
                raise ValueError(PROTECTED_MESSAGE + ", ".join(bad) + ".")
        return data


class SeekerSkillIn(In):
    key: str = Field(max_length=40)
    years: int = Field(default=0, ge=0, le=40)


class SeekerProfileIn(NoProtected):
    display_name: str = Field(min_length=2, max_length=40, description="Free text; first name only is recommended.")
    headline: str = Field(min_length=5, max_length=120)
    skills: list[SeekerSkillIn] = Field(min_length=1, max_length=8)
    certifications: list[str] = Field(default_factory=list, max_length=8)
    languages: list[str] = Field(min_length=1, max_length=8)
    districts: list[str] = Field(default_factory=list, max_length=13, description="Empty = any district.")
    availability: str = Field(pattern=r"^(seasonal|permanent|part_time)$")
    available_from: str | None = Field(default=None, pattern=DATE)
    available_to: str | None = Field(default=None, pattern=DATE)
    pay_min: int | None = Field(default=None, ge=0, le=500000)
    pay_max: int | None = Field(default=None, ge=0, le=500000)
    bio: str | None = Field(default=None, max_length=500)
    visibility: str = Field(default="public", pattern=r"^(public|hidden)$")
    phone: str | None = Field(default=None, max_length=20, pattern=r"^\+?[0-9][0-9 -]{7,18}$")
    email: str | None = Field(default=None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    consent: bool = Field(description="Must be true: the seeker read the privacy notice.")


class SeekerProfileUpdateIn(NoProtected):
    display_name: str | None = Field(default=None, min_length=2, max_length=40)
    headline: str | None = Field(default=None, min_length=5, max_length=120)
    skills: list[SeekerSkillIn] | None = Field(default=None, min_length=1, max_length=8)
    certifications: list[str] | None = Field(default=None, max_length=8)
    languages: list[str] | None = Field(default=None, min_length=1, max_length=8)
    districts: list[str] | None = Field(default=None, max_length=13)
    availability: str | None = Field(default=None, pattern=r"^(seasonal|permanent|part_time)$")
    available_from: str | None = Field(default=None, pattern=DATE)
    available_to: str | None = Field(default=None, pattern=DATE)
    pay_min: int | None = Field(default=None, ge=0, le=500000)
    pay_max: int | None = Field(default=None, ge=0, le=500000)
    bio: str | None = Field(default=None, max_length=500)
    visibility: str | None = Field(default=None, pattern=r"^(public|hidden)$")
    phone: str | None = Field(default=None, max_length=20, pattern=r"^\+?[0-9][0-9 -]{7,18}$")
    email: str | None = Field(default=None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class JobIn(In):
    business_id: str = Field(max_length=40, description="One of your businesses with an ACTIVE registration.")
    title: str = Field(min_length=3, max_length=80)
    skills: list[str] = Field(min_length=1, max_length=4)
    district: str | None = Field(default=None, max_length=40, description="Default: the business's district.")
    destination_id: str | None = Field(default=None, max_length=60)
    job_type: str = Field(pattern=r"^(seasonal|permanent|part_time)$")
    season_from: str | None = Field(default=None, pattern=DATE)
    season_to: str | None = Field(default=None, pattern=DATE)
    pay_min: int | None = Field(default=None, ge=0, le=500000)
    pay_max: int | None = Field(default=None, ge=0, le=500000)
    accommodation: bool = False
    food: bool = False
    openings: int = Field(default=1, ge=1, le=50)
    languages: list[str] = Field(default_factory=list, max_length=4)
    description: str = Field(min_length=20, max_length=1000)
    closes_on: str = Field(pattern=DATE)


class JobUpdateIn(In):
    status: str | None = Field(default=None, pattern=r"^(open|closed)$")
    closed_reason: str | None = Field(default=None, pattern=r"^(filled|withdrawn)$")
    closes_on: str | None = Field(default=None, pattern=DATE)
    openings: int | None = Field(default=None, ge=1, le=50)
    description: str | None = Field(default=None, min_length=20, max_length=1000)


class JobApplyIn(In):
    note: str | None = Field(default=None, max_length=500)


class JobApplicationStatusIn(In):
    status: str = Field(pattern=r"^(viewed|shortlisted|contacted|not_selected)$")


class InterestIn(In):
    job_id: str | None = Field(default=None, max_length=20)
    business_id: str | None = Field(default=None, max_length=40, description="Default: the job's business, else your first active one.")
    message: str | None = Field(default=None, max_length=500)


class InterestDecisionIn(In):
    action: str = Field(pattern=r"^(accept|decline)$")


class MessageIn(In):
    text: str = Field(min_length=1, max_length=1000)


# ------------------------------------------------------------------ local (community) experiences
class LocalExperienceIn(In):
    business_id: str = Field(max_length=40, description="Your guide, homestay or adventure-operator business (ACTIVE registration).")
    title: str = Field(min_length=5, max_length=90)
    type: str = Field(max_length=30, description="One of meta.local_experience_types")
    destination_id: str | None = Field(
        default=None, max_length=60, description="Default: the business's destination; must be in its district."
    )
    description: str = Field(min_length=20, max_length=1200)
    duration_hours: float = Field(ge=0.5, le=12)
    group_min: int = Field(default=1, ge=1, le=50)
    group_max: int = Field(ge=1, le=50)
    price_min: int | None = Field(default=None, ge=0, le=50000, description="Per person, INR, indicative")
    price_max: int | None = Field(default=None, ge=0, le=50000)
    languages: list[str] = Field(default_factory=list, max_length=6)
    months: list[int] = Field(min_length=1, max_length=12)
    stay_business_ids: list[str] = Field(default_factory=list, max_length=3, description="1-3 registered homestays nearby (same district)")
    community_share: str | None = Field(default=None, max_length=200, description="How the fee is shared locally")
    what_to_bring: list[str] = Field(default_factory=list, max_length=6)


class LocalExperienceUpdateIn(In):
    title: str | None = Field(default=None, min_length=5, max_length=90)
    type: str | None = Field(default=None, max_length=30)
    destination_id: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, min_length=20, max_length=1200)
    duration_hours: float | None = Field(default=None, ge=0.5, le=12)
    group_min: int | None = Field(default=None, ge=1, le=50)
    group_max: int | None = Field(default=None, ge=1, le=50)
    price_min: int | None = Field(default=None, ge=0, le=50000)
    price_max: int | None = Field(default=None, ge=0, le=50000)
    languages: list[str] | None = Field(default=None, max_length=6)
    months: list[int] | None = Field(default=None, min_length=1, max_length=12)
    stay_business_ids: list[str] | None = Field(default=None, max_length=3)
    community_share: str | None = Field(default=None, max_length=200)
    what_to_bring: list[str] | None = Field(default=None, max_length=6)
    status: str | None = Field(default=None, pattern=r"^(listed|paused)$")


class JoinRequestIn(In):
    name: str = Field(min_length=2, max_length=60, description="First name is enough")
    group_size: int = Field(ge=1, le=50)
    date: str = Field(pattern=DATE)
    contact: str = Field(min_length=5, max_length=120, description="Phone or email; shared with this host only")
    note: str | None = Field(default=None, max_length=500)


class JoinDecisionIn(In):
    action: str = Field(pattern=r"^(accept|decline)$")


# ------------------------------------------------------------------ staffing agencies + HOI staffing requests
class StaffingRequestIn(In):
    """Two accepted shapes (unknown fields are still rejected):

    * HOI platform client: `{external_id, department, skill, date_from, date_to, openings, note}`;
    * long form: `{skill, district, from, to, openings, shift_note, source, source_id}`.
    `external_id` / `source_id` is the idempotency key; `source` defaults to `hoi_roster_shortage`."""

    skill: str | None = Field(
        default=None, max_length=40, description="Skill key from GET /api/v1/jobs/meta (HOI role names like food_beverage are mapped)"
    )
    department: str | None = Field(
        default=None, max_length=40, description="HOI department; used as the skill when `skill` is not a known key"
    )
    district: str | None = Field(default=None, max_length=40, description="District id or name; must be the hotel's own district (default)")
    date_from: str | None = Field(default=None, pattern=DATE)
    date_to: str | None = Field(default=None, pattern=DATE)
    from_: str | None = Field(default=None, alias="from", pattern=DATE)
    to: str | None = Field(default=None, pattern=DATE)
    openings: int = Field(ge=1, le=50)
    note: str | None = Field(default=None, max_length=300, description="Shift note (alias of shift_note)")
    shift_note: str | None = Field(default=None, max_length=300)
    source: str = Field(default="hoi_roster_shortage", pattern=r"^hoi_roster_shortage$")
    external_id: str | None = Field(default=None, max_length=80, description="Idempotency key from the HOI platform")
    source_id: str | None = Field(
        default=None, max_length=80, description="Idempotency key (alias of external_id). Default: skill:district:from:to"
    )

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)

    @model_validator(mode="after")
    def _shape(self):
        if not (self.skill or self.department):
            raise ValueError("skill or department is required")
        if not (self.date_from or self.from_) or not (self.date_to or self.to):
            raise ValueError("date_from and date_to (or from and to) are required")
        return self

    def normalized(self) -> dict:
        return {
            "skill": self.skill or self.department,
            "department": self.department,
            "district": self.district,
            "from": self.date_from or self.from_,
            "to": self.date_to or self.to,
            "openings": self.openings,
            "shift_note": self.shift_note or self.note,
            "source": self.source,
            "source_id": self.external_id or self.source_id,
        }


class AgencyProfileIn(In):
    agency_skills: list[str] | None = Field(default=None, max_length=15)
    districts_served: list[str] | None = Field(default=None, max_length=13)


class StaffingOfferIn(In):
    business_id: str = Field(max_length=40, description="Your staffing agency (ACTIVE registration)")
    skill: str = Field(max_length=40)
    district: str | None = Field(default=None, max_length=40, description="Default: the agency's district")
    destination_id: str | None = Field(default=None, max_length=60)
    workers: int = Field(ge=1, le=200)
    available_from: str = Field(pattern=DATE)
    available_to: str = Field(pattern=DATE)
    note: str | None = Field(default=None, max_length=300)


class StaffingOfferUpdateIn(In):
    workers: int | None = Field(default=None, ge=1, le=200)
    available_from: str | None = Field(default=None, pattern=DATE)
    available_to: str | None = Field(default=None, pattern=DATE)
    note: str | None = Field(default=None, max_length=300)
    status: str | None = Field(default=None, pattern=r"^(open|withdrawn)$")


class AgencyResponseIn(In):
    business_id: str = Field(max_length=40, description="Your staffing agency")
    workers: int = Field(ge=1, le=200, description="How many pooled workers you can supply")
    note: str | None = Field(default=None, max_length=300)
