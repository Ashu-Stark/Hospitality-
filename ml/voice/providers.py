"""Swappable speech-to-text adapters (Task T11): Groq Whisper, Sarvam, local faster-whisper.

Every adapter has the same shape: `available()` -> (bool, reason) and `transcribe(path)` -> text.
Cloud adapters use only the standard library (urllib, multipart built by hand), so no new
dependency. faster-whisper is NOT installed; its adapter reports that until the user approves
an install.

PRIVACY: cloud adapters are `external`. guard_external() refuses any file that is not listed in
clips/manifest.yaml with a cleared source (synthetic / hm_student) or that is too large, BEFORE
anything is sent. Never send real guest or staff audio to a free tier.
"""

from __future__ import annotations

import importlib.util
import json
import mimetypes
import os
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ml.voice.config import CloudProvider, LocalWhisper, Manifest, VoiceConfig

BYTES_PER_MB = 1024 * 1024


class ProviderUnavailable(RuntimeError):
    """The provider cannot run here (missing key, package or cleared clip)."""


class Transcriber(Protocol):
    name: str
    external: bool

    def available(self) -> tuple[bool, str]: ...

    def transcribe(self, path: Path) -> str: ...


def guard_external(path: Path, manifest: Manifest, cfg: VoiceConfig) -> None:
    """Raise unless `path` is a cleared synthetic / HM-student clip of acceptable size."""
    clip = manifest.clip(path.name)
    if clip is None or clip.source not in cfg.allowed_external_sources:
        raise ProviderUnavailable(
            f"{path.name} is not a cleared clip in clips/manifest.yaml (source must be one of "
            f"{cfg.allowed_external_sources}); refusing to send it to a cloud provider")
    if path.stat().st_size > cfg.max_audio_megabytes * BYTES_PER_MB:
        raise ProviderUnavailable(f"{path.name} is larger than {cfg.max_audio_megabytes} MB")


def multipart(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    """Encode form fields + one file as multipart/form-data (body, content type)."""
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                 f'filename="{path.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
                 + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https URL)
        return json.loads(resp.read().decode("utf-8"))


@dataclass
class GroqWhisper:
    settings: CloudProvider
    timeout: float
    name: str = "groq"
    external: bool = True

    def available(self) -> tuple[bool, str]:
        ok = bool(os.environ.get(self.settings.api_key_env))
        return ok, "ok" if ok else f"set {self.settings.api_key_env}"

    def transcribe(self, path: Path) -> str:
        body, ctype = multipart({"model": self.settings.model, "response_format": "json"},
                                "file", path)
        key = os.environ[self.settings.api_key_env]
        out = _post(self.settings.url, {"Authorization": f"Bearer {key}", "Content-Type": ctype},
                    body, self.timeout)
        return str(out["text"])


@dataclass
class Sarvam:
    settings: CloudProvider
    timeout: float
    name: str = "sarvam"
    external: bool = True

    def available(self) -> tuple[bool, str]:
        ok = bool(os.environ.get(self.settings.api_key_env))
        return ok, "ok" if ok else f"set {self.settings.api_key_env}"

    def transcribe(self, path: Path) -> str:
        fields = {"model": self.settings.model}
        if self.settings.language_code:
            fields["language_code"] = self.settings.language_code
        body, ctype = multipart(fields, "file", path)
        key = os.environ[self.settings.api_key_env]
        out = _post(self.settings.url, {"api-subscription-key": key, "Content-Type": ctype},
                    body, self.timeout)
        return str(out["transcript"])


@dataclass
class FasterWhisper:
    settings: LocalWhisper
    name: str = "faster_whisper"
    external: bool = False

    def available(self) -> tuple[bool, str]:
        ok = importlib.util.find_spec("faster_whisper") is not None
        return ok, "ok" if ok else "faster-whisper not installed (ask the user before installing)"

    def transcribe(self, path: Path) -> str:
        from faster_whisper import WhisperModel  # optional, local only

        model = WhisperModel(self.settings.model_size, device=self.settings.device,
                             compute_type=self.settings.compute_type)
        segments, _ = model.transcribe(str(path))
        return " ".join(s.text.strip() for s in segments)


def build_providers(cfg: VoiceConfig) -> list[Transcriber]:
    """Adapters in config provider_order."""
    all_ = {"groq": GroqWhisper(cfg.groq, cfg.request_timeout_seconds),
            "sarvam": Sarvam(cfg.sarvam, cfg.request_timeout_seconds),
            "faster_whisper": FasterWhisper(cfg.faster_whisper)}
    unknown = set(cfg.provider_order) - set(all_)
    if unknown:
        raise ValueError(f"unknown providers in config: {sorted(unknown)}")
    return [all_[n] for n in cfg.provider_order]


def run_provider(provider: Transcriber, path: Path, manifest: Manifest, cfg: VoiceConfig) -> str:
    ok, reason = provider.available()
    if not ok:
        raise ProviderUnavailable(f"{provider.name}: {reason}")
    if provider.external:
        guard_external(path, manifest, cfg)
    return provider.transcribe(path)
