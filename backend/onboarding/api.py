"""Onboarding endpoints (Part D) on the existing FastAPI app.

POST  /onboarding/start      {hotel_type?, language, hotel_name?} -> first question + draft
POST  /onboarding/answer     JSON {session_id, text, consent} OR multipart form
                             (session_id, text | file=<audio>, consent) -> draft, confidence,
                             warnings, next question or "ready_for_summary"
PATCH /onboarding/field      {session_id, field, value}: the owner edits a field (always wins)
GET   /onboarding/summary?session=   the draft with source / confidence / needs_verification
POST  /onboarding/confirm    {session, acknowledged_legal_fields}: saves property + settings
GET   /onboarding/demo-transcript   the cached SYNTHETIC Hindi / Hinglish demo answers
GET   /properties/{property_id}            one property (filtered by property_id)
GET   /properties/{property_id}/settings   its confirmed settings (filtered by property_id)

The LLM extractor runs only with consent=true AND llm.allow_cloud_llm_for_owner_text; audio
only with consent=true AND audio.allow_cloud_stt_for_owner_audio (see stt.py). Without them
everything works offline: typed text + the rule-based extractor.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from pymongo.database import Database
from starlette.concurrency import run_in_threadpool

from backend.onboarding import service
from backend.onboarding.demo import load_fixture
from backend.onboarding.flow import load_questions
from backend.onboarding.store import NotFound, get_session
from backend.onboarding.stt import BYTES_PER_MB, AudioRejected, SttRefused, transcribe_upload

FORM_TYPES = ("multipart/form-data", "application/x-www-form-urlencoded")
TRUE_WORDS = ("1", "true", "yes", "on")


def _http(e: Exception) -> HTTPException:
    if isinstance(e, NotFound):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, service.Conflict):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, service.Blocked):
        return HTTPException(status_code=422, detail=e.detail)
    if isinstance(e, (KeyError, ValidationError, ValueError)):
        return HTTPException(status_code=422, detail=service.edit_errors(e))
    raise e


def _adapter(request: Request, consent: bool):  # noqa: ANN202
    cfg = request.app.state.onboarding_cfg
    if consent and cfg.llm.allow_cloud_llm_for_owner_text:
        return request.app.state.onboarding_llm
    return None


def router(get_db, source_of) -> APIRouter:  # noqa: ANN001
    r = APIRouter(prefix="", tags=["onboarding"])

    def cfg_of(request: Request):  # noqa: ANN202
        return request.app.state.onboarding_cfg

    @r.post("/onboarding/start", response_model=service.SummaryOut)
    def start(body: service.StartRequest, request: Request,
              db: Database = Depends(get_db)) -> service.SummaryOut:
        return service.start(db, body, cfg_of(request), source_of(request))

    @r.post("/onboarding/answer", response_model=service.AnswerOut)
    async def answer(request: Request, db: Database = Depends(get_db)) -> service.AnswerOut:
        cfg = cfg_of(request)
        ctype = request.headers.get("content-type", "")
        upload = None
        try:
            if ctype.startswith(FORM_TYPES):
                form = await request.form()
                consent = str(form.get("consent", "")).lower() in TRUE_WORDS
                raw = {"session_id": form.get("session_id"), "text": form.get("text") or None,
                       "consent": consent}
                f = form.get("file")
                upload = f if f is not None and hasattr(f, "read") else None
            else:
                raw = json.loads(await request.body() or b"{}")
            session_id = str(raw.get("session_id") or "")
            if not session_id:
                raise ValueError("session_id is required")
            consent = bool(raw.get("consent"))
            if upload is not None:
                session = await run_in_threadpool(get_session, db, session_id)
                lang = session["language"]
                data = await upload.read(int(cfg.audio.max_megabytes * BYTES_PER_MB) + 1)
                try:
                    text = await run_in_threadpool(
                        transcribe_upload, data, upload.filename or "", upload.content_type,
                        consent, cfg.audio, request.app.state.onboarding_stt)
                except SttRefused as e:
                    msg = load_questions().message(e.key, lang)
                    if e.detail:
                        msg = f"{msg} ({e.detail})"
                    return await run_in_threadpool(service.stt_failed, db, session_id, cfg, msg)
                kind = "voice"
            else:
                body = service.AnswerRequest.model_validate(raw)
                text, kind = body.text, "typed"
            return await run_in_threadpool(
                service.answer, db, session_id, text, kind, cfg, _adapter(request, consent),
                source_of(request))
        except AudioRejected as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except (NotFound, service.Conflict, ValidationError, ValueError, KeyError) as e:
            raise _http(e) from e

    @r.patch("/onboarding/field", response_model=service.SummaryOut)
    def field(body: service.FieldEdit, request: Request,
              db: Database = Depends(get_db)) -> service.SummaryOut:
        try:
            return service.edit(db, body, cfg_of(request), source_of(request))
        except (NotFound, service.Conflict, KeyError, ValidationError, ValueError) as e:
            raise _http(e) from e

    @r.get("/onboarding/summary", response_model=service.SummaryOut)
    def summary(session: str, request: Request,
                db: Database = Depends(get_db)) -> service.SummaryOut:
        try:
            return service.summary(db, session, cfg_of(request))
        except NotFound as e:
            raise _http(e) from e

    @r.post("/onboarding/confirm", response_model=service.ConfirmOut)
    def confirm(body: service.ConfirmRequest, request: Request,
                db: Database = Depends(get_db)) -> service.ConfirmOut:
        try:
            return service.confirm(db, body, cfg_of(request), source_of(request))
        except (NotFound, service.Blocked) as e:
            raise _http(e) from e

    @r.get("/onboarding/demo-transcript")
    def demo_transcript() -> dict:
        fx = load_fixture()
        return {"synthetic": fx.synthetic, "language": fx.language, "answers": fx.answers,
                "note": "SYNTHETIC: written by us, not recorded speech"}

    @r.get("/properties/{property_id}")
    def get_property(property_id: str, db: Database = Depends(get_db)) -> dict:
        try:
            return service.get_property(db, property_id)
        except NotFound as e:
            raise _http(e) from e

    @r.get("/properties/{property_id}/settings")
    def get_settings(property_id: str, db: Database = Depends(get_db)) -> dict:
        try:
            return service.get_settings(db, property_id)
        except NotFound as e:
            raise _http(e) from e

    return r
