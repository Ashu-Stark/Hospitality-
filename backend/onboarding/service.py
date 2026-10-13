"""Onboarding service (Part D): start, answer, edit, summary, confirm. No FastAPI here.

Nothing is saved as a property before Confirm: the draft lives in the onboarding_session
document only. Confirm writes `property` and `property_settings` only if every required field is
filled, no field has an error, no answer is waiting for "please confirm", and every legal field
(min rest, overtime multiplier, weekly off) is in acknowledged_legal_fields. It is idempotent
without transactions: property_id is reserved at start and unique in `property`, so a double
submit hits the unique index and returns the same property (created=False). Every state change
writes audit_log. Every query filters by session_id or property_id.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from backend.db import NO_ID, PROPERTIES, PROPERTY_SETTINGS, audit, stamped, utcnow
from backend.onboarding import geocode, llm
from backend.onboarding.config import OnboardingConfig
from backend.onboarding.flow import (
    FlowState,
    Question,
    advance,
    is_skip,
    load_questions,
    record_answer,
    render,
)
from backend.onboarding.merge import Issues, edit_field, merge, validate
from backend.onboarding.schema import (
    FIELD_NAMES,
    LEGAL_FIELDS,
    REQUIRED_FIELDS,
    HotelProfile,
    HotelType,
)
from backend.onboarding.store import (
    NotFound,
    create_session,
    draft_of,
    flow_of,
    get_session,
    save_session,
)
from backend.onboarding.templates import apply_template

InputKind = Literal["typed", "voice"]
IN_PROGRESS, READY, CONFIRMED = "in_progress", "ready_for_summary", "confirmed"
RETEMPLATE_FIELDS = ("rooms", "hotel_type")


class Conflict(RuntimeError):
    """The session is already confirmed (HTTP 409)."""


class Blocked(ValueError):
    """Confirm refused; detail says exactly what is missing (HTTP 422)."""

    def __init__(self, detail: dict) -> None:
        super().__init__("confirm blocked")
        self.detail = detail


class StartRequest(BaseModel):
    hotel_type: HotelType | None = None
    language: Literal["en", "hi"] = "en"
    hotel_name: str | None = Field(default=None, max_length=120)


class AnswerRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=2000)
    consent: bool = False   # owner agreed that a cloud AI may process this answer


class FieldEdit(BaseModel):
    session_id: str
    field: str
    value: Any


class ConfirmRequest(BaseModel):
    session: str
    acknowledged_legal_fields: list[str] = Field(default_factory=list)


class SummaryOut(BaseModel):
    session_id: str
    property_id: str
    status: str
    language: str
    banner: str
    fields: dict[str, dict]
    confidence: dict[str, float]
    errors: dict[str, list[str]]
    warnings: dict[str, list[str]]
    missing_required: list[str]
    needs_confirmation: list[str]      # answers below the accept threshold ("please confirm")
    legal_fields: list[str]            # need an explicit acknowledgement at Confirm
    ready_to_confirm: bool             # everything except the legal acknowledgements is fine
    question: Question | None
    answers: int


class AnswerOut(SummaryOut):
    transcript: str | None
    input: str | None
    extractor: str | None              # "rules" | "llm" | None (skip / no transcript)
    fallback_reason: str | None
    mismatches: list[str]
    filled: list[str]
    message: str | None
    stt_error: str | None = None       # set when audio could not be transcribed
    input_fallback: str | None = None  # "text" when the owner should type instead


class ConfirmOut(BaseModel):
    property_id: str
    created: bool                      # False = this session was already confirmed
    status: str
    acknowledged_legal_fields: list[str]


def _retemplate(draft: HotelProfile, cfg: OnboardingConfig) -> HotelProfile:
    """Refresh template fields for the hotel type (the owner's, else the rooms' size band)."""
    t = draft.hotel_type.value if draft.hotel_type.from_answer else None
    if t is None and draft.rooms.value is not None:
        t = cfg.hotel_type_for(draft.rooms.value)
    return apply_template(draft, t or draft.hotel_type.value or cfg.default_hotel_type, cfg=cfg)


def _issues(draft: HotelProfile, cfg: OnboardingConfig, extra: Issues | None = None) -> Issues:
    v = validate(draft, cfg)
    return extra.merged_with(v) if extra else v


def _summary(session: dict, cfg: OnboardingConfig, extra: Issues | None = None) -> dict:
    draft, flow = draft_of(session), flow_of(session)
    issues = _issues(draft, cfg, extra)
    accept = cfg.confidence.accept_threshold
    missing = [f for f in REQUIRED_FIELDS if not draft.field(f).filled]
    unsure = [f for f in FIELD_NAMES if draft.field(f).filled and draft.field(f).from_answer
              and draft.field(f).confidence < accept]
    lang = session["language"]
    q = render(flow.current, lang, flow, cfg) if flow.current else None
    return {"session_id": session["session_id"], "property_id": session["property_id"],
            "status": session["status"], "language": lang,
            "banner": load_questions().message("draft_banner", lang),
            "fields": draft.model_dump(mode="json"),
            "confidence": {f: draft.field(f).confidence for f in FIELD_NAMES},
            "errors": issues.errors, "warnings": issues.warnings, "missing_required": missing,
            "needs_confirmation": unsure, "legal_fields": list(LEGAL_FIELDS),
            "ready_to_confirm": not (missing or issues.errors or unsure), "question": q,
            "answers": len(session.get("answers", []))}


def start(db: Database, req: StartRequest, cfg: OnboardingConfig, source: str) -> SummaryOut:
    draft = HotelProfile()
    if req.hotel_type:
        draft = edit_field(draft, "hotel_type", req.hotel_type, cfg)
    if req.hotel_name:
        draft = edit_field(draft, "hotel_name", req.hotel_name, cfg)
    draft = apply_template(draft, req.hotel_type or cfg.default_hotel_type, cfg=cfg)
    flow = advance(FlowState(), cfg)
    session = create_session(db, req.language, draft, flow, source, req.hotel_type is not None)
    session = save_session(db, session, status=IN_PROGRESS if flow.current else READY)
    audit(db, "onboarding.start", {"session_id": session["session_id"],
                                   "property_id": session["property_id"],
                                   "language": req.language, "hotel_type": req.hotel_type},
          source)
    return SummaryOut(**_summary(session, cfg))


def _open(db: Database, session_id: str) -> dict:
    session = get_session(db, session_id)
    if session["status"] == CONFIRMED:
        raise Conflict(f"session {session_id} is already confirmed as "
                       f"{session['property_id']}; start a new session to change it")
    return session


def answer(db: Database, session_id: str, text: str, kind: InputKind, cfg: OnboardingConfig,
           adapter: llm.ChatAdapter | None, source: str,
           geocoder: geocode.Geocoder | None = None) -> AnswerOut:
    """Apply one answer (typed text or a transcript) and move to the next question."""
    session = _open(db, session_id)
    draft, flow = draft_of(session), flow_of(session)
    asked = flow.current
    qs = load_questions()
    lang = session["language"]
    result = None
    issues = Issues()
    filled: list[str] = []
    message = None
    if is_skip(text, qs):
        flow = record_answer(flow, [], skipped=True)
    else:
        result = llm.extract(text, asked, adapter, cfg)
        draft, filled, issues = merge(draft, result, kind, cfg)
        if set(filled) & set(RETEMPLATE_FIELDS):
            draft = _retemplate(draft, cfg)
        if "location" in filled:
            draft = geocode.attach(draft, geocoder)   # a hint only; silently skipped on failure
        flow = record_answer(flow, filled, skipped=False)
        if asked and asked not in filled:
            message = qs.message("not_understood", lang)
    flow = advance(flow, cfg)
    status = IN_PROGRESS if flow.current else READY
    if status == READY:
        message = qs.message("ready", lang)
    record = {"n": len(session.get("answers", [])) + 1, "field": asked, "input": kind,
              "transcript": text, "extractor": result.method if result else None,
              "fallback_reason": result.fallback_reason if result else None,
              "mismatches": result.mismatches if result else [], "filled": filled,
              "at": utcnow()}
    session = save_session(db, session, draft=draft.model_dump(mode="json"),
                           flow=flow.model_dump(), status=status,
                           answers=[*session.get("answers", []), record])
    audit(db, "onboarding.answer",
          {"session_id": session_id, "property_id": session["property_id"], "field": asked,
           "input": kind, "extractor": record["extractor"], "filled": filled,
           "mismatches": record["mismatches"], "skipped": result is None}, source)
    return AnswerOut(**_summary(session, cfg, issues), transcript=text, input=kind,
                     extractor=record["extractor"], fallback_reason=record["fallback_reason"],
                     mismatches=record["mismatches"], filled=filled, message=message)


def stt_failed(db: Database, session_id: str, cfg: OnboardingConfig, message: str
               ) -> AnswerOut:
    """Audio could not be used: same question again, with the text-input fallback."""
    session = _open(db, session_id)
    return AnswerOut(**_summary(session, cfg), transcript=None, input="voice", extractor=None,
                     fallback_reason=None, mismatches=[], filled=[], message=message,
                     stt_error=message, input_fallback="text")


def edit(db: Database, body: FieldEdit, cfg: OnboardingConfig, source: str,
         geocoder: geocode.Geocoder | None = None) -> SummaryOut:
    """The owner edits one field directly (always wins). KeyError / ValidationError -> 422."""
    session = _open(db, body.session_id)
    draft = edit_field(draft_of(session), body.field, body.value, cfg)
    if body.field in RETEMPLATE_FIELDS:
        draft = _retemplate(draft, cfg)
    if body.field == "location":
        draft = geocode.attach(draft, geocoder)
    flow = record_answer(flow_of(session), [body.field], skipped=False)
    if flow.current == body.field:
        flow = advance(flow.model_copy(update={"current": None}), cfg)
    session = save_session(db, session, draft=draft.model_dump(mode="json"),
                           flow=flow.model_dump(), status=IN_PROGRESS if flow.current else READY)
    audit(db, "onboarding.field_edit", {"session_id": body.session_id, "field": body.field,
                                        "property_id": session["property_id"]}, source)
    return SummaryOut(**_summary(session, cfg))


def summary(db: Database, session_id: str, cfg: OnboardingConfig) -> SummaryOut:
    return SummaryOut(**_summary(get_session(db, session_id), cfg))


def confirm(db: Database, body: ConfirmRequest, cfg: OnboardingConfig, source: str,
            demo: bool = False) -> ConfirmOut:
    session = get_session(db, body.session)
    pid = session["property_id"]
    existing = db[PROPERTIES].find_one({"property_id": pid}, NO_ID)
    if session["status"] == CONFIRMED and existing:
        audit(db, "onboarding.confirm", {"session_id": session["session_id"],
                                         "property_id": pid, "created": False,
                                         "repeat": True}, source)
        return ConfirmOut(property_id=pid, created=False, status=CONFIRMED,
                          acknowledged_legal_fields=existing["acknowledged_legal_fields"])
    s = _summary(session, cfg)
    acked = sorted(set(body.acknowledged_legal_fields) & set(LEGAL_FIELDS))
    unacked = [f for f in LEGAL_FIELDS if f not in acked]
    if s["missing_required"] or s["errors"] or s["needs_confirmation"] or unacked:
        raise Blocked({"message": "Confirm blocked: nothing was saved.",
                       "missing_required": s["missing_required"], "errors": s["errors"],
                       "needs_confirmation": s["needs_confirmation"],
                       "unacknowledged_legal_fields": unacked})
    data = draft_of(session).model_dump(mode="json")
    for name in FIELD_NAMES:  # shown at confirm and accepted; legal ones acknowledged
        if data[name]["value"] is not None:
            data[name]["confirmed"] = True
    profile = HotelProfile.model_validate(data)
    now = utcnow()
    prop = {"property_id": pid, "onboarding_session_id": session["session_id"],
            "hotel_name": profile.hotel_name.value, "hotel_type": profile.hotel_type.value,
            "rooms": profile.rooms.value, "location": profile.location.value,
            "acknowledged_legal_fields": acked, "confirmed_at": now, "demo": demo,
            "synthetic": demo}
    created = True
    try:
        db[PROPERTIES].insert_one(stamped(db, PROPERTIES, prop, source))
    except DuplicateKeyError:
        created = False  # a concurrent / repeated confirm already saved this property
    if created:
        settings = {"property_id": pid, "profile": profile.model_dump(mode="json"),
                    "acknowledged_legal_fields": acked, "acknowledged_at": now,
                    "legal_note": load_questions().message("verify_legal", "en")}
        try:
            db[PROPERTY_SETTINGS].insert_one(stamped(db, PROPERTY_SETTINGS, settings, source))
        except DuplicateKeyError:
            pass
        audit(db, "property.create", {"property_id": pid, "rooms": profile.rooms.value,
                                      "hotel_type": profile.hotel_type.value}, source)
        audit(db, "property_settings.create", {"property_id": pid, "acknowledged": acked},
              source)
    save_session(db, session, status=CONFIRMED, draft=profile.model_dump(mode="json"))
    audit(db, "onboarding.confirm", {"session_id": session["session_id"], "property_id": pid,
                                     "created": created, "acknowledged": acked}, source)
    return ConfirmOut(property_id=pid, created=created, status=CONFIRMED,
                      acknowledged_legal_fields=acked)


def get_property(db: Database, property_id: str) -> dict:
    doc = db[PROPERTIES].find_one({"property_id": property_id}, NO_ID)
    if doc is None:
        raise NotFound(f"no property {property_id!r}")
    return doc


def get_settings(db: Database, property_id: str) -> dict:
    doc = db[PROPERTY_SETTINGS].find_one({"property_id": property_id}, NO_ID)
    if doc is None:
        raise NotFound(f"no settings for property {property_id!r}")
    return doc


def edit_errors(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                         for err in e.errors())
    return str(e)
