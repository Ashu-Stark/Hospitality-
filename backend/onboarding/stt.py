"""Owner audio -> transcript (Part D), with explicit consent and no audio kept.

ml/voice/providers.guard_external() is unchanged: it only lets cleared SYNTHETIC / HM-student
clips reach a cloud provider, which is right for staff voice notes. Onboarding audio is the
OWNER's own answer, so it takes a separate, explicit path: a cloud provider (the existing
ml/voice Groq Whisper / Sarvam adapters) is called only if
  (a) onboarding.yaml audio.allow_cloud_stt_for_owner_audio is true (default false), AND
  (b) the request carries consent=true from the checkbox (own voice, no staff names or salaries,
      free AI tiers give no privacy guarantee).
Otherwise SttRefused carries a clear message and the caller offers the text input instead.
The upload is checked (type, extension, size) before anything else, written to a temporary
file only for the provider call, and deleted in `finally` unless audio.store_audio is true.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Protocol

from backend.config import REPO_ROOT
from backend.onboarding.config import AudioConfig
from ml.voice.config import load_voice_config
from ml.voice.providers import build_providers

BYTES_PER_MB = 1024 * 1024


class AudioRejected(ValueError):
    """The upload is not an allowed audio type or is too large (HTTP 422 / 413)."""


class SttRefused(RuntimeError):
    """Speech-to-text may not or cannot run (flag off, no consent, no provider)."""

    def __init__(self, key: str, detail: str = "") -> None:
        super().__init__(detail or key)
        self.key, self.detail = key, detail


class SpeechToText(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def transcribe(self, path: Path) -> str: ...


class CloudSTT:
    """The ml/voice cloud adapters named in audio.stt_providers, first available one wins."""

    name = "cloud_stt"

    def __init__(self, names: list[str]) -> None:
        cfg = load_voice_config()
        self.providers = [p for p in build_providers(cfg) if p.name in names]

    def available(self) -> tuple[bool, str]:
        reasons = []
        for p in self.providers:
            ok, why = p.available()
            if ok:
                return True, p.name
            reasons.append(f"{p.name}: {why}")
        return False, "; ".join(reasons) or "no provider configured"

    def transcribe(self, path: Path) -> str:
        for p in self.providers:
            if p.available()[0]:
                return p.transcribe(path)
        raise SttRefused("stt_unavailable", "no speech-to-text provider is available")


def check_upload(data: bytes, filename: str, content_type: str | None, cfg: AudioConfig) -> str:
    """The file extension to use, or AudioRejected."""
    ext = Path(filename or "").suffix.lower()
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ext not in cfg.allowed_extensions or (ctype and ctype not in cfg.allowed_types
                                            and ctype != "application/octet-stream"):
        raise AudioRejected(f"audio type not allowed ({ctype or 'unknown'}, {ext or 'no '
                            'extension'}); allowed: {', '.join(cfg.allowed_extensions)}")
    if len(data) > cfg.max_megabytes * BYTES_PER_MB:
        raise AudioRejected(f"audio is larger than {cfg.max_megabytes:g} MB")
    if not data:
        raise AudioRejected("audio file is empty")
    return ext


def transcribe_upload(data: bytes, filename: str, content_type: str | None, consent: bool,
                      cfg: AudioConfig, stt: SpeechToText | None) -> str:
    ext = check_upload(data, filename, content_type, cfg)
    if not cfg.allow_cloud_stt_for_owner_audio:
        raise SttRefused("cloud_stt_off")
    if not consent:
        raise SttRefused("consent_needed")
    if stt is None or not stt.available()[0]:
        raise SttRefused("stt_unavailable", "no speech-to-text provider is available")
    if cfg.store_audio:
        folder = REPO_ROOT / cfg.audio_dir
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4().hex}{ext}"
        path.write_bytes(data)
    else:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(data)
            path = Path(f.name)
    try:
        text = stt.transcribe(path)
    except SttRefused:
        raise
    except Exception as e:  # noqa: BLE001 - any provider failure -> the text fallback
        raise SttRefused("stt_unavailable", f"speech-to-text failed ({type(e).__name__})") from e
    finally:
        if not cfg.store_audio:
            path.unlink(missing_ok=True)
    if not text.strip():
        raise SttRefused("stt_unavailable", "speech-to-text returned no words")
    return text
