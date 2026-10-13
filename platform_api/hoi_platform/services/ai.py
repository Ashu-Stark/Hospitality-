"""Cloud AI adapters for the guest concierge and worker voice: Whisper speech-to-text and chat completions (JSON mode).

Provider-neutral: any OpenAI-compatible API works unchanged (config LLM_BASE_URL / LLM_MODEL / LLM_JSON_MODE and
STT_BASE_URL / STT_MODEL): Groq (default), OpenAI, or a local Ollama (chat only; Ollama has no Whisper endpoint).

Standard library only (urllib, multipart built by hand), adapted from ml/voice/providers.py and
backend/onboarding/llm.py; this package deploys on its own, so it does not import them.

- Keys come ONLY from the environment (LLM_API_KEY / STT_API_KEY, else GROQ_API_KEY), read at call time; never logged or returned.
- Audio is sent from memory: nothing is written to disk here.
- Tests swap the adapters with fakes through `use(chat=..., stt=...)`; the default test run never calls the network.
- PRIVACY: free AI tiers give no privacy guarantee. Callers send only what the guest/worker typed or said (after consent),
  plus the hotel's public profile. No names, no ids of staff, no other rooms.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .. import config

log = logging.getLogger("hoi.platform.ai")
KEY_ENV = "GROQ_API_KEY"  # fallback for both LLM_API_KEY and STT_API_KEY
AUDIO_EXT = {  # browser MediaRecorder types -> file extension Groq accepts
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "video/mp4": "mp4",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/aac": "m4a",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}
# Whisper "hears" these on silence or a test tone; treated as nothing said.
STT_HALLUCINATIONS = {
    "",
    "you",
    "thank you",
    "thank you.",
    "thanks for watching!",
    "thanks for watching",
    "bye.",
    "bye",
    ".",
    "धन्यवाद",
    "धन्यवाद।",
    "शुक्रिया",
    "subtitles by the amara.org community",
}


class AiUnavailable(RuntimeError):
    """Cloud AI cannot run (disabled, no key, network error, rate limit, bad reply). Callers fall back."""


class ChatAdapter(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def complete_json(self, system: str, messages: list[dict]) -> str: ...


class SttAdapter(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def transcribe(self, audio: bytes, mime: str, lang: str | None) -> str: ...


def _key(kind: str = "LLM") -> str | None:
    """kind 'LLM' or 'STT': {kind}_API_KEY, else GROQ_API_KEY. Ollama accepts any non-empty string."""
    return os.environ.get(f"{kind}_API_KEY") or os.environ.get(KEY_ENV) or None


def chat_url() -> str:
    return config.settings.llm_base_url.rstrip("/") + "/chat/completions"


def stt_url() -> str:
    return config.settings.stt_base_url.rstrip("/") + "/audio/transcriptions"


def _enabled(kind: str = "LLM") -> tuple[bool, str]:
    if not config.settings.guest_ai_enabled:
        return False, "cloud AI is turned off (HOI_GUEST_AI_ENABLED=false)"
    if not _key(kind):
        return False, f"set {kind}_API_KEY or {KEY_ENV}"
    return True, "ok"


_COOLDOWN = {"until": 0.0}  # after HTTP 429, skip cloud calls until then (answers come from the rules meanwhile)
DEFAULT_COOLDOWN_S, MAX_COOLDOWN_S = 20.0, 120.0
MAX_INLINE_WAIT_S = 2.0  # a 429 with Retry-After up to this is retried once on the same key; longer -> rules


def cooling_down() -> bool:
    return time.monotonic() < _COOLDOWN["until"]


def _keys(kind: str) -> list[str]:
    """Primary key, then backups ({kind}_API_KEYS_BACKUP, else GROQ_API_KEYS_BACKUP; comma-separated). Never logged."""
    primary = _key(kind)
    backups = os.environ.get(f"{kind}_API_KEYS_BACKUP") or os.environ.get("GROQ_API_KEYS_BACKUP") or ""
    out: list[str] = []
    for k in [primary or "", *backups.split(",")]:
        k = k.strip()
        if k and k not in out:
            out.append(k)
    return out


_UNHEALTHY: dict[str, float] = {}  # sha256(key) -> monotonic time until which the key is skipped (the key itself is not kept)
ROTATE_HTTP = {401, 403}  # invalid / revoked key


def _kid(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _post_keys(kind: str, make: Callable[[str], urllib.request.Request], timeout: float) -> dict:
    """POST with key failover. The next key is tried ONLY when a key is invalid/revoked (401/403) or the provider fails
    (5xx, connection error, timeout); that key is then skipped for ai_key_cooldown_minutes. Logs show indices only.

    HTTP 429 never rotates: moving to another key to get around a provider's per-account rate limit would break its terms
    (Groq's included). A 429 starts the shared cool-down (Retry-After, bounded) and the caller falls back to the rules.
    """
    if cooling_down():
        raise AiUnavailable("rate limited (cooling down)")
    keys = _keys(kind)
    if not keys:
        raise AiUnavailable(f"set {kind}_API_KEY or {KEY_ENV}")
    now = time.monotonic()
    healthy = [(i, k) for i, k in enumerate(keys) if _UNHEALTHY.get(_kid(k), 0.0) <= now]
    if not healthy:
        raise AiUnavailable("all keys failed recently")
    label = kind.lower()
    last = "no key tried"
    for i, k in healthy:
        try:
            try:
                return _post(make(k), timeout)
            except _RateLimited as rl:
                # 429: the SAME key may be retried once after a short Retry-After; it is never swapped for another key.
                if rl.wait > MAX_INLINE_WAIT_S:
                    raise
                time.sleep(max(rl.wait, 0.0))
                return _post(make(k), timeout)
        except _RateLimited as rl:
            _COOLDOWN["until"] = time.monotonic() + min(max(rl.wait, 1.0), MAX_COOLDOWN_S)
            raise AiUnavailable("HTTP 429") from None  # the caller answers with the rules meanwhile
        except _KeyFailed as e:
            _UNHEALTHY[_kid(k)] = time.monotonic() + config.settings.ai_key_cooldown_minutes * 60
            log.warning("%s key #%d failed: %s", label, i + 1, e.reason)
            last = e.reason
    raise AiUnavailable(f"all keys failed ({last})")


class _RateLimited(AiUnavailable):
    def __init__(self, wait: float):
        super().__init__("HTTP 429")
        self.wait = wait


class _KeyFailed(AiUnavailable):
    """This key cannot be used now (401/403, 5xx, connection error): try the next one."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _post(req: urllib.request.Request, timeout: float) -> dict:
    if cooling_down():
        raise AiUnavailable("rate limited (cooling down)")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # never include the response body (could echo input)
        if e.code == 429:
            try:
                wait = float(e.headers.get("retry-after") or DEFAULT_COOLDOWN_S)
            except ValueError:
                wait = DEFAULT_COOLDOWN_S
            raise _RateLimited(wait) from None  # never a reason to rotate keys (see _post_keys)
        if e.code in ROTATE_HTTP or e.code >= 500:
            raise _KeyFailed(f"{e.code}") from None
        raise AiUnavailable(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise _KeyFailed(type(e).__name__) from None
    except ValueError as e:
        raise AiUnavailable(type(e).__name__) from None


def multipart(fields: dict[str, str], file_field: str, filename: str, mime: str, data: bytes) -> tuple[bytes, str]:
    """Encode form fields + one in-memory file as multipart/form-data (body, content type)."""
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


@dataclass
class OpenAICompatChat:
    name: str = "llm"

    def available(self) -> tuple[bool, str]:
        return _enabled("LLM")

    def complete_json(self, system: str, messages: list[dict]) -> str:
        s = config.settings
        body: dict = {
            "model": s.llm_model,
            "temperature": s.chat_temperature,
            "max_tokens": 600,  # includes the reasoning tokens of gpt-oss; kept small for the free-tier token budget
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if s.llm_json_mode:  # off for servers without JSON mode; the reply is validated by Pydantic either way
            body["response_format"] = {"type": "json_object"}
        if s.llm_model.startswith("openai/gpt-oss"):  # Groq's gpt-oss naming; other providers do not get this field
            body["reasoning_effort"] = "low"
        data = json.dumps(body).encode("utf-8")

        def make(key: str) -> urllib.request.Request:
            return urllib.request.Request(
                chat_url(),
                data=data,
                method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "hoi-platform/1"},
            )

        out = _post_keys("LLM", make, s.ai_timeout_seconds)
        try:
            return str(out["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            raise AiUnavailable("unexpected reply shape") from None


@dataclass
class OpenAICompatWhisper:
    name: str = "whisper"

    def available(self) -> tuple[bool, str]:
        return _enabled("STT")

    def transcribe(self, audio: bytes, mime: str, lang: str | None) -> str:
        s = config.settings
        base = (mime or "").split(";")[0].strip().lower()
        ext = AUDIO_EXT.get(base, "webm")
        fields = {
            "model": s.stt_model,
            "response_format": "json",
            "temperature": "0",
            # a short bias prompt: hotel vocabulary, Hindi in Devanagari (avoids Urdu script for Hindi speech)
            "prompt": "Hotel guest or staff speaking English, Hindi (देवनागरी) or Hinglish: towels, AC, checkout, Wi-Fi, room.",
        }
        if lang == "hi":
            fields["language"] = "hi"
        body, ctype = multipart(fields, "file", f"audio.{ext}", base or "audio/webm", audio)

        def make(key: str) -> urllib.request.Request:
            return urllib.request.Request(
                stt_url(),
                data=body,
                method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": ctype, "User-Agent": "hoi-platform/1"},
            )

        out = _post_keys("STT", make, s.ai_timeout_seconds)
        return str(out.get("text") or "")


class LocalWhisper:
    """faster-whisper on this machine (STT_PROVIDER=local). Imported lazily: deployments without the package still start.

    Model LOCAL_STT_MODEL (default "small", multilingual incl. Hindi; the first run downloads it, about 460 MB) is loaded
    once per process. Device LOCAL_STT_DEVICE: auto = CUDA when ctranslate2 sees a GPU (float16), else CPU int8; a failed
    CUDA load falls back to CPU. Audio goes through a temporary file that is deleted in `finally`.
    """

    name = "local-whisper"
    _model = None
    _device: str | None = None
    _lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        if not config.settings.guest_ai_enabled:
            return False, "cloud AI is turned off (HOI_GUEST_AI_ENABLED=false)"
        if importlib.util.find_spec("faster_whisper") is None:
            return False, "faster-whisper is not installed (pip install -r requirements-local.txt)"
        return True, "ok"

    @classmethod
    def model(cls):  # noqa: ANN206
        with cls._lock:
            if cls._model is None:
                from faster_whisper import WhisperModel  # lazy: optional dependency

                s = config.settings
                want = s.local_stt_device
                if want == "auto":
                    try:
                        import ctranslate2

                        want = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
                    except Exception:  # noqa: BLE001
                        want = "cpu"
                try:
                    if want == "cuda":
                        cls._model, cls._device = WhisperModel(s.local_stt_model, device="cuda", compute_type="float16"), "cuda"
                    else:
                        raise RuntimeError("cpu requested")
                except Exception:  # noqa: BLE001 - CUDA missing or failed: CPU int8 still works
                    cls._model, cls._device = WhisperModel(s.local_stt_model, device="cpu", compute_type="int8"), "cpu"
                log.info("local speech-to-text model %s loaded on %s", s.local_stt_model, cls._device)
            return cls._model

    @classmethod
    def to_cpu(cls) -> None:
        from faster_whisper import WhisperModel  # lazy

        with cls._lock:
            cls._model, cls._device = WhisperModel(config.settings.local_stt_model, device="cpu", compute_type="int8"), "cpu"
        log.warning("local speech-to-text: CUDA failed at run time; switched to CPU (int8)")

    def transcribe(self, audio: bytes, mime: str, lang: str | None) -> str:
        ext = AUDIO_EXT.get((mime or "").split(";")[0].strip().lower(), "webm")
        fd, path = tempfile.mkstemp(suffix="." + ext, prefix="hoi-stt-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(audio)
            pcm = _decode(path)
            language = lang if lang in ("hi", "en") else None
            try:
                segments, _info = self.model().transcribe(pcm, language=language, beam_size=1, vad_filter=True)
                return " ".join(seg.text.strip() for seg in segments)  # segments are lazy: decoding runs here
            except RuntimeError:
                if LocalWhisper._device != "cuda":
                    raise
                self.to_cpu()  # e.g. cuBLAS/cuDNN DLLs missing: the GPU model loads but cannot run
                segments, _info = self.model().transcribe(pcm, language=language, beam_size=1, vad_filter=True)
                return " ".join(seg.text.strip() for seg in segments)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def _decode(path: str):  # noqa: ANN202 - numpy float32 mono 16 kHz, what faster-whisper expects
    """faster-whisper's own decoder, or (PyAV >= 16 dropped an argument it passes) the same decode with PyAV's current API."""
    from faster_whisper import decode_audio  # lazy

    try:
        return decode_audio(path, sampling_rate=16000)
    except TypeError:
        import av
        import numpy as np

        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        chunks = []
        with av.open(path, mode="r") as container:
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray().reshape(-1))
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
        return audio.astype(np.float32) / 32768.0


_OVERRIDE: dict[str, object] = {}


def use(chat: ChatAdapter | None = None, stt: SttAdapter | None = None) -> None:
    """Swap adapters (tests). use() with no arguments restores the configured providers."""
    _OVERRIDE.clear()
    if chat is not None:
        _OVERRIDE["chat"] = chat
    if stt is not None:
        _OVERRIDE["stt"] = stt


def chat_adapter() -> ChatAdapter:
    return _OVERRIDE.get("chat") or OpenAICompatChat()  # type: ignore[return-value]


def stt_adapter() -> SttAdapter:
    if "stt" in _OVERRIDE:
        return _OVERRIDE["stt"]  # type: ignore[return-value]
    return LocalWhisper() if config.settings.stt_provider == "local" else OpenAICompatWhisper()


def clean_transcript(text: str, limit: int = 500) -> str:
    t = " ".join((text or "").split())[:limit]
    return "" if t.strip().lower() in STT_HALLUCINATIONS else t


def transcribe(audio: bytes, mime: str, lang: str | None) -> dict:
    """Speech to text from memory. Raises AiUnavailable (the caller answers 503 'type instead')."""
    if not config.settings.guest_ai_enabled:
        raise AiUnavailable("disabled")
    stt = stt_adapter()
    ok, why = stt.available()
    if not ok:
        raise AiUnavailable(why)
    try:
        text = stt.transcribe(audio, mime, lang)
    except AiUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 - any adapter failure means "type instead"
        raise AiUnavailable(type(e).__name__) from None
    return {"text": clean_transcript(text), "provider": stt.name}


# Old names kept for readers of earlier docs.
GroqChat, GroqWhisper = OpenAICompatChat, OpenAICompatWhisper
