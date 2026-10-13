"""Load and validate the voice config, glossary and clip manifest (Task T11)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

VOICE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = VOICE_DIR / "config.yaml"
GLOSSARY_PATH = VOICE_DIR / "glossary.yaml"
CLIPS_DIR = VOICE_DIR / "clips"
MANIFEST_PATH = CLIPS_DIR / "manifest.yaml"
CACHE_PATH = VOICE_DIR / "cache" / "demo_result.json"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CloudProvider(_Strict):
    api_key_env: str
    url: str
    model: str
    language_code: str | None = None


class LocalWhisper(_Strict):
    model_size: str
    device: str
    compute_type: str


class VoiceConfig(_Strict):
    provider_order: list[str] = Field(min_length=1)
    request_timeout_seconds: float = Field(gt=0)
    max_audio_megabytes: float = Field(gt=0)
    allowed_external_sources: list[str]
    groq: CloudProvider
    sarvam: CloudProvider
    faster_whisper: LocalWhisper
    room_digits: tuple[int, int]
    default_urgency: str


class Term(_Strict):
    id: str
    english: list[str]
    hindi: list[str]
    romanised: list[str]
    issue: str
    department: str

    @property
    def phrases(self) -> list[str]:
        return [*self.english, *self.hindi, *self.romanised]


class Glossary(_Strict):
    departments: list[str]
    urgency_levels: list[str]
    room_words: list[str]
    urgency_terms: dict[str, list[str]]
    terms: list[Term] = Field(min_length=20, max_length=30)
    review_defaults: dict[str, str | bool]

    @model_validator(mode="after")
    def _consistent(self) -> Glossary:
        bad = [t.id for t in self.terms if t.department not in self.departments]
        if bad:
            raise ValueError(f"glossary terms with unknown departments: {bad}")
        if set(self.urgency_terms) - set(self.urgency_levels):
            raise ValueError("urgency_terms keys must be urgency levels")
        if len({t.id for t in self.terms}) != len(self.terms):
            raise ValueError("glossary term ids must be unique")
        return self

    @property
    def issues(self) -> set[str]:
        return {t.issue for t in self.terms}


class Expected(_Strict):
    room: str | None
    issue: str
    urgency: str
    department: str


class Clip(_Strict):
    file: str
    source: str
    language: str
    reference: str
    expected: Expected


class Manifest(_Strict):
    demo_clip: str
    clips: list[Clip]

    @model_validator(mode="after")
    def _demo_listed(self) -> Manifest:
        if self.demo_clip not in {c.file for c in self.clips}:
            raise ValueError("demo_clip must be one of the clips")
        return self

    def clip(self, file_name: str) -> Clip | None:
        return next((c for c in self.clips if c.file == file_name), None)


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_voice_config(path: Path = CONFIG_PATH) -> VoiceConfig:
    return VoiceConfig.model_validate(_yaml(path))


def load_glossary(path: Path = GLOSSARY_PATH) -> Glossary:
    return Glossary.model_validate(_yaml(path))


def load_manifest(path: Path = MANIFEST_PATH) -> Manifest:
    return Manifest.model_validate(_yaml(path))
