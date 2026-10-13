"""Settings from environment variables. Nothing secret has a hard-coded default.

HOI_ENV=production makes startup fail fast on unsafe settings (see validate()).
MONGODB_URI is a secret: it is never logged or returned (repr=False keeps it out of reprs too).
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _bool(v: str | None, default: bool) -> bool:
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str
    jwt_secret: str = field(repr=False)
    jwt_secret_from_env: bool
    access_ttl_minutes: int
    refresh_ttl_days: int
    demo_login: bool
    admin_password: str | None = field(repr=False)
    seed_demo: bool
    seed_homestay: bool = True  # the demo homestay next to the demo hotel; off for hotel-only simulations
    cors_origins: list[str] = field(default_factory=list)
    public_base_url: str = ""
    login_rate_per_minute: int = 10
    mongodb_uri: str = field(default="", repr=False)
    db_name: str = "hoi_platform"
    # Guest concierge + worker voice (docs/HOSPITALITY_SUITE.md section 6). ASSUMED defaults.
    # Any OpenAI-compatible provider (Groq default, OpenAI, local Ollama). API keys are read from the environment at
    # call time only (services/ai.py: LLM_API_KEY / STT_API_KEY, falling back to GROQ_API_KEY); never stored here.
    guest_ai_enabled: bool = True
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-20b"
    llm_json_mode: bool = True
    stt_base_url: str = "https://api.groq.com/openai/v1"
    stt_model: str = "whisper-large-v3-turbo"
    ai_timeout_seconds: float = 20.0
    ai_key_cooldown_minutes: float = 10.0  # ASSUMED: a key that failed with 401/403/5xx is skipped this long
    stt_provider: str = "groq"  # "groq" = any OpenAI-compatible Whisper API (STT_*); "local" = faster-whisper on this PC
    local_stt_model: str = "small"
    local_stt_device: str = "auto"  # auto | cuda | cpu
    # Spoken replies. ASSUMED (user preference: a woman's voice, soft, Indian accent, same speaker for Hindi and English).
    tts_provider: str = "browser"  # "browser" (speechSynthesis) | "sarvam" (needs SARVAM_API_KEY in the environment)
    sarvam_model: str = "bulbul:v3"
    sarvam_speaker: str = "priya"
    sarvam_pace: float = 0.9
    tts_rate_per_minute: int = 20
    chat_temperature: float = 0.3
    chat_history_turns: int = 6
    chat_max_reply_chars: int = 600
    stt_max_mb: float = 8.0
    stt_max_seconds: int = 60
    guest_chat_rate_per_minute: int = 10
    guest_stt_rate_per_minute: int = 6
    guest_action_rate_per_minute: int = 10
    feedback_max_chars: int = 1000
    hotel_utc_offset_minutes: int = 330  # hotel local time for "HH:MM" checkout times (India, no DST)
    # Concierge "places to visit": look up the tourism portal when a hotel's own list is short (services/places.py)
    places_lookup: bool = True
    places_cache_hours: float = 24.0

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def uses_mongomock(self) -> bool:
        return not self.mongodb_uri or self.mongodb_uri.startswith("mongomock://")


_EPHEMERAL_SECRET = secrets.token_urlsafe(48)


def load() -> Settings:
    secret = os.getenv("HOI_JWT_SECRET")
    env = os.getenv("HOI_ENV", "development").strip().lower()
    return Settings(
        env=env,
        # Without HOI_JWT_SECRET a random per-process secret is used (development only): tokens stop working after a restart.
        jwt_secret=secret or _EPHEMERAL_SECRET,
        jwt_secret_from_env=bool(secret),
        access_ttl_minutes=int(os.getenv("HOI_ACCESS_TTL_MINUTES", "30")),
        refresh_ttl_days=int(os.getenv("HOI_REFRESH_TTL_DAYS", "14")),
        demo_login=_bool(os.getenv("HOI_DEMO_LOGIN"), env != "production"),
        admin_password=os.getenv("HOI_ADMIN_PASSWORD"),
        seed_demo=_bool(os.getenv("HOI_SEED_DEMO"), env != "production"),
        seed_homestay=_bool(os.getenv("HOI_SEED_HOMESTAY"), True),
        cors_origins=[o.strip() for o in os.getenv("HOI_CORS_ORIGINS", "*" if env != "production" else "").split(",") if o.strip()],
        public_base_url=os.getenv("HOI_PUBLIC_BASE_URL", "").rstrip("/"),
        login_rate_per_minute=int(os.getenv("HOI_LOGIN_RATE_PER_MINUTE", "10")),
        mongodb_uri=os.getenv("MONGODB_URI", "").strip(),
        db_name=os.getenv("HOI_PLATFORM_DB", "").strip() or "hoi_platform",
        guest_ai_enabled=_bool(os.getenv("HOI_GUEST_AI_ENABLED"), True),
        llm_base_url=(os.getenv("LLM_BASE_URL") or "https://api.groq.com/openai/v1").strip().rstrip("/"),
        llm_model=(os.getenv("LLM_MODEL") or "openai/gpt-oss-20b").strip(),
        llm_json_mode=_bool(os.getenv("LLM_JSON_MODE"), True),
        stt_base_url=(os.getenv("STT_BASE_URL") or "https://api.groq.com/openai/v1").strip().rstrip("/"),
        stt_model=(os.getenv("STT_MODEL") or "whisper-large-v3-turbo").strip(),
        ai_timeout_seconds=float(os.getenv("HOI_AI_TIMEOUT_SECONDS", "20")),
        ai_key_cooldown_minutes=float(os.getenv("HOI_AI_KEY_COOLDOWN_MINUTES") or "10"),
        stt_provider=(os.getenv("STT_PROVIDER") or "groq").strip().lower(),
        local_stt_model=(os.getenv("LOCAL_STT_MODEL") or "small").strip(),
        local_stt_device=(os.getenv("LOCAL_STT_DEVICE") or "auto").strip().lower(),
        tts_provider=(os.getenv("TTS_PROVIDER") or "browser").strip().lower(),
        sarvam_model=(os.getenv("SARVAM_MODEL") or "bulbul:v3").strip(),
        sarvam_speaker=(os.getenv("SARVAM_SPEAKER") or "priya").strip(),
        sarvam_pace=float(os.getenv("SARVAM_PACE") or "0.9"),
        tts_rate_per_minute=int(os.getenv("HOI_TTS_RATE_PER_MINUTE", "20")),
        chat_temperature=float(os.getenv("HOI_CHAT_TEMPERATURE", "0.3")),
        chat_history_turns=int(os.getenv("HOI_CHAT_HISTORY_TURNS", "6")),
        chat_max_reply_chars=int(os.getenv("HOI_CHAT_MAX_REPLY_CHARS", "600")),
        stt_max_mb=float(os.getenv("HOI_STT_MAX_MB", "8")),
        stt_max_seconds=int(os.getenv("HOI_STT_MAX_SECONDS", "60")),
        guest_chat_rate_per_minute=int(os.getenv("HOI_GUEST_CHAT_RATE_PER_MINUTE", "10")),
        guest_stt_rate_per_minute=int(os.getenv("HOI_GUEST_STT_RATE_PER_MINUTE", "6")),
        guest_action_rate_per_minute=int(os.getenv("HOI_GUEST_ACTION_RATE_PER_MINUTE", "10")),
        feedback_max_chars=int(os.getenv("HOI_FEEDBACK_MAX_CHARS", "1000")),
        hotel_utc_offset_minutes=int(os.getenv("HOI_HOTEL_UTC_OFFSET_MINUTES", "330")),
        places_lookup=_bool(os.getenv("HOI_PLACES_LOOKUP"), True),
        places_cache_hours=float(os.getenv("HOI_PLACES_CACHE_HOURS") or "24"),
    )


def validate(s: Settings) -> list[str]:
    """Problems that must stop a production start. Empty list = OK."""
    if not s.is_production:
        return []
    problems = []
    if not s.jwt_secret_from_env or len(s.jwt_secret) < 32:
        problems.append("HOI_JWT_SECRET must be set to at least 32 characters.")
    if s.demo_login:
        problems.append("HOI_DEMO_LOGIN must be false in production.")
    if "*" in s.cors_origins:
        problems.append("HOI_CORS_ORIGINS must list explicit origins in production (no '*').")
    if not s.admin_password or len(s.admin_password) < 12:
        problems.append("HOI_ADMIN_PASSWORD must be set (12+ characters) so the platform admin can sign in.")
    if s.uses_mongomock:
        problems.append("MONGODB_URI must point at a real MongoDB deployment in production (not unset or mongomock://).")
    return problems


settings = load()


def reload() -> Settings:
    """Re-read the environment (used by tests that point HOI_PLATFORM_DB at a fresh database)."""
    global settings
    settings = load()
    return settings
