"""Employee self-service: my shifts and my department (used by the worker portal)."""

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile

from .. import config, ratelimit
from ..deps import HOTEL_MANAGERS, Principal, roles, tenant_of
from ..schemas import PulseConsentIn, PulseIn, RosterPublishIn, TtsIn, VoiceActIn, VoiceCommandIn
from ..services import dispatch, performance, recognition, staff_signals, tts, voice, worklog
from . import audio

router = APIRouter(tags=["me"])


@router.get("/me/shifts")
def my_shifts(p: Principal = Depends(roles("worker"))) -> dict:
    tid = tenant_of(p)
    out = dispatch.shifts_for(tid, p.employee_id or p.username)
    ctx = dispatch.get_context(tid)
    out["department"] = ctx["working"].get(p.employee_id or "") or next(
        (s["department"] for s in dispatch.tenants.staff(tid) if s["employee_id"] == p.employee_id), None
    )
    prop = dispatch.tenants.property_of_staff(tid, p.employee_id)
    out["property"] = {"id": prop["id"], "name": prop["name"], "mode": prop["mode"]} if prop else None
    out["mode"] = prop["mode"] if prop else "hotel"
    # homestay teams have no roster: everyone of the property counts as available
    out["on_shift_now"] = (p.employee_id or "") in ctx["working"] or out["mode"] == "homestay"
    # the same live context the dispatcher offers jobs from (live roster + clock, or the owner's manual override)
    out["current_shift"] = {
        "day": ctx.get("day"),
        "shift": ctx.get("shift"),
        "window": ctx.get("shift_window"),
        "roster_week_mapped": bool(ctx.get("roster_week_mapped")),
        "local_date": ctx.get("local_date"),  # the real calendar date of that shift (hotel time); `day` is the roster's
        "source": ctx.get("source"),
    }
    # API times without an offset (mongo.iso) are this server's clock: UTC on the host, IST on a laptop. The app needs
    # the offset to show them in hotel time.
    out["server_utc_offset_minutes"] = int(datetime.now().astimezone().utcoffset().total_seconds() // 60)
    return out


@router.get("/me/recognition")
def my_recognition(month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"), p: Principal = Depends(roles("worker"))) -> dict:
    """The signed-in worker's own recognition points and reward estimate, plus team totals (never colleagues' points)."""
    return recognition.for_worker(tenant_of(p), p.employee_id or p.username, month)


@router.get("/me/performance")
def my_performance(days: int = Query(default=14, ge=1, le=90), p: Principal = Depends(roles("worker"))) -> dict:
    """The signed-in worker's own score and reasons only (never colleagues', never risk bands)."""
    out = performance.compute(tenant_of(p), days, worker=p.employee_id or p.username)
    me = out.pop("workers")[0]
    return {**out, **me}


@router.get("/me/pulse")
def my_pulse(p: Principal = Depends(roles("worker"))) -> dict:
    """The optional weekly "How was your week?": consent given?, this week's answer."""
    return staff_signals.pulse_status(tenant_of(p), p.employee_id or p.username)


@router.put("/me/pulse/consent")
def my_pulse_consent(body: PulseConsentIn, p: Principal = Depends(roles("worker"))) -> dict:
    """Yes / no to the weekly question. No deletes the answers already given."""
    return staff_signals.set_pulse_consent(tenant_of(p), p.employee_id or p.username, body.consent)


@router.post("/me/pulse")
def my_pulse_answer(body: PulseIn, p: Principal = Depends(roles("worker"))) -> dict:
    """One tap: good / ok / hard for this week (needs consent; a second tap the same week replaces the first)."""
    ratelimit.hit(f"pulse:{p.user_id}", 20)
    return staff_signals.answer_pulse(tenant_of(p), p.employee_id or p.username, body.answer)


@router.get("/me/worklog")
def my_worklog(
    day: str | None = Query(default=None, alias="date", pattern=r"^\d{4}-\d{2}-\d{2}$"), p: Principal = Depends(roles("worker"))
) -> dict:
    """The signed-in worker's own jobs for one day (default today, hotel local time) with minutes and photo ids."""
    try:
        return worklog.compute(tenant_of(p), day, employee_id=p.employee_id or p.username)
    except ValueError:
        raise HTTPException(422, "date must be a real day, YYYY-MM-DD.") from None


@router.post("/me/voice/transcribe")
async def voice_transcribe(
    request: Request,
    audio_file: UploadFile = File(..., alias="audio"),
    consent: str = Form("false"),
    lang: str = Form(""),
    seconds: float | None = Form(None),
    p: Principal = Depends(roles("worker")),
) -> dict:
    """The worker's own voice -> text (same Groq Whisper path as guests; consent remembered per device by the app)."""
    try:
        tenant_of(p)
        ratelimit.hit(f"voice-stt:{p.user_id}", 12)
    except Exception:
        await audio_file.close()
        raise
    return await audio.transcribe(audio_file, consent, lang, seconds)


@router.post("/me/voice/command")
def voice_command(body: VoiceCommandIn, p: Principal = Depends(roles("worker"))) -> dict:
    """Text -> intent + reply + proposed action. Nothing is executed here."""
    ratelimit.hit(f"voice-cmd:{p.user_id}", 30)
    return voice.command(tenant_of(p), p.employee_id or p.username, body.text, body.lang)


@router.post("/me/voice/tts", response_class=Response)
def voice_tts(body: TtsIn, p: Principal = Depends(roles("worker"))) -> Response:
    """Server voice for a reply: audio/wav, or 204 = speak it in the browser."""
    tenant_of(p)
    ratelimit.hit(f"voice-tts:{p.user_id}", config.settings.tts_rate_per_minute)
    audio = tts.synth(body.text, body.lang)
    if not audio:
        return Response(status_code=204)
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/me/voice/act")
def voice_act(body: VoiceActIn, p: Principal = Depends(roles("worker"))) -> dict:
    """Executes a confirmed voice action as the signed-in worker (accept / decline / start / complete / report_issue)."""
    ratelimit.hit(f"voice-act:{p.user_id}", 20)
    return voice.act(tenant_of(p), p.employee_id or p.username, p.username, body.action, body.params)


@router.put("/dispatch/roster")
def publish_roster(body: RosterPublishIn, p: Principal = Depends(roles(*HOTEL_MANAGERS))) -> dict:
    """Managers publish the week's roster so employees can see their own shifts."""
    return dispatch.publish_roster(tenant_of(p), body.week_start, body.assignments)
