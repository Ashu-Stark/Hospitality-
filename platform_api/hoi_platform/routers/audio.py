"""Shared upload handling for voice input (guest concierge and worker app). Not a router.

Privacy: the audio is read into memory (capped) and sent to the speech-to-text adapter; it is never stored. Starlette
spools uploads above 1 MB to a temporary file: `finally: await audio.close()` deletes it before the response returns.
Duration: the browser stops recording at stt_max_seconds and sends `seconds`; the size cap is the server's hard limit.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

from .. import config
from ..services import ai

TYPE_INSTEAD = "Voice input is not available right now. Please type instead."
MIN_BYTES = 800  # shorter than this is a tap, not speech


async def transcribe(audio: UploadFile, consent: str, lang: str, seconds: float | None) -> dict:
    try:
        if str(consent).strip().lower() not in ("true", "1", "yes", "on"):
            raise HTTPException(422, "Please tick the box to allow voice processing by the AI service, or type instead.")
        mime = (audio.content_type or "").split(";")[0].strip().lower()
        if not (mime.startswith("audio/") or mime in ("video/webm", "video/mp4")):
            raise HTTPException(415, "Unsupported audio format. Please type instead.")
        s = config.settings
        if seconds is not None and seconds > s.stt_max_seconds + 2:
            raise HTTPException(413, f"Recording is too long (max {s.stt_max_seconds} seconds).")
        limit = int(s.stt_max_mb * 1024 * 1024)
        data = await audio.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"Recording is too large (max {s.stt_max_mb:g} MB).")
        if len(data) < MIN_BYTES:
            raise HTTPException(422, "Didn't catch that. Try again or type.")
        try:
            return ai.transcribe(data, audio.content_type or mime, lang if lang in ("hi", "en") else None)
        except ai.AiUnavailable:
            raise HTTPException(503, TYPE_INSTEAD) from None
    finally:
        await audio.close()  # removes Starlette's spooled temp file, if any
