"""Voice interface (Task T11): voice.extract(audio_path).

Transcribe a staff voice note with the first provider that is available (config provider_order;
cloud providers only get cleared synthetic / HM-student clips), then extract room / issue /
urgency / department with the glossary. If no provider can run and the file is the manifest's
demo clip, the cached demo result is returned with fallback_used=True, so a live demo never
breaks. Otherwise a VoiceUnavailable error says exactly what is missing.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from ml.voice.config import (
    CACHE_PATH,
    load_glossary,
    load_manifest,
    load_voice_config,
)
from ml.voice.extraction import Extraction, extract_fields
from ml.voice.providers import ProviderUnavailable, build_providers, run_provider


class VoiceUnavailable(RuntimeError):
    """No provider could transcribe the clip and no cached fallback applies."""


class VoiceResult(BaseModel):
    audio_file: str
    provider: str
    transcript: str
    extraction: Extraction
    fallback_used: bool = False
    synthetic: bool = True


def load_cached_demo(path: Path = CACHE_PATH) -> VoiceResult:
    return VoiceResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


def extract(audio_path: str | Path, cache_path: Path = CACHE_PATH) -> VoiceResult:
    """Transcript + validated extraction for one voice note."""
    path = Path(audio_path)
    cfg, glossary, manifest = load_voice_config(), load_glossary(), load_manifest()
    reasons = []
    if path.exists():
        for provider in build_providers(cfg):
            try:
                text = run_provider(provider, path, manifest, cfg)
            except ProviderUnavailable as e:
                reasons.append(str(e))
                continue
            return VoiceResult(audio_file=path.name, provider=provider.name, transcript=text,
                               extraction=extract_fields(text, glossary, cfg))
    else:
        reasons.append(f"audio file not found: {path}")
    if path.name == manifest.demo_clip and cache_path.exists():
        return load_cached_demo(cache_path).model_copy(update={"fallback_used": True})
    raise VoiceUnavailable("voice.extract could not run: " + "; ".join(reasons))
