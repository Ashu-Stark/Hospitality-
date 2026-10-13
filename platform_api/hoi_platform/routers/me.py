"""Employee self-service: my shifts and my department (used by the worker portal)."""

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile

from .. import config, ratelimit
from ..deps import HOTEL_MANAGERS, Principal, roles, tenant_of
from ..schemas import RosterPublishIn, TtsIn, VoiceActIn, VoiceCommandIn
from ..services import dispatch, performance, recognition, tts, voice
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
    out["current_shift"] = {"day": ctx.get("day"), "shift": ctx.get("shift")}
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
