"""Optional server text-to-speech with Sarvam "Bulbul" (realistic Indian voices). Default provider is the browser.

API (verified against docs.sarvam.ai, 13 Oct 2026): POST https://api.sarvam.ai/text-to-speech, header
`api-subscription-key`, JSON {text, language_code: hi-IN|en-IN, model, speaker, pace (0.5-2.0 for v3/v4-flash),
output_audio_codec: wav}; response {"request_id", "audios": [base64 WAV]}. pitch/loudness exist only for bulbul:v2.

- TTS_PROVIDER=browser (default) -> synth() returns None and the endpoint answers 204: the app speaks with speechSynthesis.
- TTS_PROVIDER=sarvam + SARVAM_API_KEY (env only, never logged) -> WAV bytes. Identical (text, lang, model, speaker, pace)
  audio is cached in MongoDB (`tts_cache`, TTL 24 h) to save credits. Any failure -> None (204, browser fallback).
- Text is normalised for speech first (services/speech_text.py) and capped at 500 characters.
- Defaults are ASSUMED (user preference: a woman's voice, soft, Indian accent, the same speaker for Hindi and English):
  model bulbul:v3 with speaker "priya" and pace 0.9. The docs do not label speaker gender; confirm by listening in the
  Sarvam dashboard. A v4-flash alternative from the voice catalog: SARVAM_MODEL=bulbul:v4-flash, SARVAM_SPEAKER=ritu_hi_customer_warm.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from bson import Binary

from .. import config, mongo
from .speech_text import for_speech

log = logging.getLogger("hoi.platform.tts")
URL = "https://api.sarvam.ai/text-to-speech"
KEY_ENV = "SARVAM_API_KEY"
CACHE_HOURS = 24
LANG_CODE = {"hi": "hi-IN", "hinglish": "hi-IN", "en": "en-IN"}


class TtsClient(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def synth(self, text: str, language_code: str, model: str, speaker: str, pace: float) -> bytes: ...


@dataclass
class SarvamTts:
    name: str = "sarvam"

    def available(self) -> tuple[bool, str]:
        ok = bool(os.environ.get(KEY_ENV))
        return ok, "ok" if ok else f"set {KEY_ENV}"

    def synth(self, text: str, language_code: str, model: str, speaker: str, pace: float) -> bytes:
        key = os.environ.get(KEY_ENV)
        if not key:
            raise RuntimeError(f"set {KEY_ENV}")
        body = {"text": text, "language_code": language_code, "model": model, "speaker": speaker, "pace": pace, "output_audio_codec": "wav"}
        req = urllib.request.Request(
            URL,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"api-subscription-key": key, "Content-Type": "application/json", "User-Agent": "hoi-platform/1"},
        )
        with urllib.request.urlopen(req, timeout=config.settings.ai_timeout_seconds) as resp:  # noqa: S310 - fixed https URL
            out = json.loads(resp.read().decode("utf-8"))
        return base64.b64decode(out["audios"][0])


_OVERRIDE: dict[str, TtsClient] = {}


def use(client: TtsClient | None = None) -> None:
    """Swap the client (tests). use() restores Sarvam."""
    _OVERRIDE.clear()
    if client is not None:
        _OVERRIDE["c"] = client


def client() -> TtsClient:
    return _OVERRIDE.get("c") or SarvamTts()


def synth(text: str, lang: str) -> bytes | None:
    """WAV bytes, or None when the browser should speak (provider 'browser', no key, error)."""
    s = config.settings
    if s.tts_provider != "sarvam" or not s.guest_ai_enabled:
        return None
    c = client()
    ok, _ = c.available()
    if not ok:
        return None
    spoken = for_speech(text, "hi" if lang in ("hi", "hinglish") else "en")[:500].strip()
    if not spoken:
        return None
    code = LANG_CODE.get(lang, "en-IN")
    key = hashlib.sha256(
        json.dumps([spoken, code, s.sarvam_model, s.sarvam_speaker, s.sarvam_pace], ensure_ascii=False).encode()
    ).hexdigest()
    hit = mongo.col("tts_cache").find_one({"key": key, "created_at": {"$gte": mongo.now() - timedelta(hours=CACHE_HOURS)}})
    if hit:
        return bytes(hit["audio"])
    try:
        audio = c.synth(spoken, code, s.sarvam_model, s.sarvam_speaker, s.sarvam_pace)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, binascii.Error, RuntimeError) as e:
        log.info("tts fallback to browser: %s", type(e).__name__)  # never the text, never the key
        return None
    if not audio:
        return None
    mongo.col("tts_cache").update_one(
        {"key": key}, {"$set": {"key": key, "audio": Binary(audio), "created_at": mongo.now(), "lang": code}}, upsert=True
    )
    return audio
