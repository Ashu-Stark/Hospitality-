"""Unauthenticated endpoints for the guest QR page (docs/HOSPITALITY_SUITE.md section 2).

Scoped by the room's random token; rate-limited per IP and per room. Responses never include other rooms' data or staff
ids. The chat proposes actions only; /actions runs one after the guest taps Confirm. Chat text is not stored or logged.
"""

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from .. import config, ratelimit
from ..schemas import ExpressCheckoutIn, FeedbackIn, GuestActionIn, GuestChatIn, GuestRequestIn, LateCheckoutIn, TtsIn
from ..services import concierge, guest, rooms, tts
from . import audio

router = APIRouter(prefix="/public", tags=["public"])


def _limit(request: Request, token: str, bucket: str, per_room: int, per_ip: int | None = None) -> None:
    ratelimit.hit(f"guest-{bucket}:ip:{ratelimit.client_ip(request)}", per_ip or per_room * 3)
    ratelimit.hit(f"guest-{bucket}:room:{token[:40]}", per_room)


def _view_limit(request: Request) -> None:
    ratelimit.hit(f"guest-view:{ratelimit.client_ip(request)}", 60)


@router.get("/guest/{token}")
def guest_view(token: str, request: Request) -> dict:
    _view_limit(request)
    return rooms.guest_view(token)


@router.get("/guest/{token}/requests")
def guest_requests(token: str, request: Request) -> dict:
    _view_limit(request)
    return rooms.guest_requests(token)


@router.post("/guest/{token}/requests", status_code=201)
def guest_request(token: str, body: GuestRequestIn, request: Request) -> dict:
    ratelimit.hit(f"guest-req:{ratelimit.client_ip(request)}", 10)
    return rooms.guest_request(token, body.key, body.note)


@router.post("/guest/{token}/transcribe")
async def transcribe(
    token: str,
    request: Request,
    audio_file: UploadFile = File(..., alias="audio"),
    consent: str = Form("false"),
    lang: str = Form(""),
    seconds: float | None = Form(None),
) -> dict:
    """Speech to text (Groq Whisper). 422 without consent; 503 'type instead' when cloud AI is off or fails."""
    try:
        _limit(request, token, "stt", config.settings.guest_stt_rate_per_minute)
        rooms.by_token(token)
    except Exception:
        await audio_file.close()
        raise
    return await audio.transcribe(audio_file, consent, lang, seconds)


@router.post("/guest/{token}/tts", response_class=Response)
def speak(token: str, body: TtsIn, request: Request) -> Response:
    """Server voice (Sarvam Bulbul) for a reply: audio/wav, or 204 = speak it in the browser (no key, provider 'browser', error)."""
    _limit(request, token, "tts", config.settings.tts_rate_per_minute)
    rooms.by_token(token)
    audio = tts.synth(body.text, body.lang)
    if not audio:
        return Response(status_code=204)
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/guest/{token}/chat")
def chat(token: str, body: GuestChatIn, request: Request) -> dict:
    _limit(request, token, "chat", config.settings.guest_chat_rate_per_minute)
    return concierge.chat(token, body.message, body.lang, [h.model_dump() for h in body.history])


@router.post("/guest/{token}/actions")
def actions(token: str, body: GuestActionIn, request: Request) -> dict:
    """Runs one proposed action. Only the guest's Confirm tap calls this; the chat never does."""
    _limit(request, token, "act", config.settings.guest_action_rate_per_minute)
    return concierge.execute(token, body.action, body.params)


@router.post("/guest/{token}/checkout", status_code=201)
def checkout(token: str, body: ExpressCheckoutIn, request: Request) -> dict:
    _limit(request, token, "act", config.settings.guest_action_rate_per_minute)
    return guest.express_checkout(token, body.time, body.luggage_help)


@router.post("/guest/{token}/late-checkout", status_code=201)
def late_checkout(token: str, body: LateCheckoutIn, request: Request) -> dict:
    _limit(request, token, "act", config.settings.guest_action_rate_per_minute)
    return guest.request_late(token, body.until, body.reason)


@router.get("/guest/{token}/late-checkout")
def late_status(token: str, request: Request) -> dict:
    _view_limit(request)
    return guest.late_status(token)


@router.post("/guest/{token}/feedback", status_code=201)
def feedback(token: str, body: FeedbackIn, request: Request) -> dict:
    _limit(request, token, "act", config.settings.guest_action_rate_per_minute)
    return guest.give_feedback(token, body.rating, body.comment, body.lang)


@router.get("/guest/{token}/bill")
def bill(token: str, request: Request) -> dict:
    _view_limit(request)
    return guest.bill(token)
