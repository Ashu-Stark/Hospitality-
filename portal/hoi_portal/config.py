"""Settings from environment variables. Nothing secret has a hard-coded default.

HOI_ENV=production makes startup fail fast on unsafe settings (see validate()).
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
    mongodb_uri: str = field(repr=False)
    db_name: str
    jwt_secret: str = field(repr=False)
    jwt_secret_from_env: bool
    access_ttl_minutes: int
    refresh_ttl_days: int
    demo_login: bool
    admin_password: str | None = field(repr=False)
    seed_demo: bool
    cors_origins: list[str] = field(default_factory=list)
    login_rate_per_minute: int = 10
    grievance_rate_per_hour: int = 5
    track_rate_per_minute: int = 20
    verify_rate_per_minute: int = 60
    ingest_rate_per_minute: int = 120
    weather_enabled: bool = True
    weather_ttl_minutes: int = 30

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def uses_mongomock(self) -> bool:
        return not self.mongodb_uri or self.mongodb_uri.startswith("mongomock")


_EPHEMERAL_SECRET = secrets.token_urlsafe(48)


def load() -> Settings:
    secret = os.getenv("PORTAL_JWT_SECRET")
    env = os.getenv("HOI_ENV", "development").strip().lower()
    prod = env == "production"
    return Settings(
        env=env,
        mongodb_uri=os.getenv("MONGODB_URI", "").strip(),
        db_name=os.getenv("HOI_PORTAL_DB", "hoi_portal").strip() or "hoi_portal",
        # Without PORTAL_JWT_SECRET a random per-process secret is used (development only): tokens stop working after a restart.
        jwt_secret=secret or _EPHEMERAL_SECRET,
        jwt_secret_from_env=bool(secret),
        access_ttl_minutes=int(os.getenv("PORTAL_ACCESS_TTL_MINUTES", "30")),
        refresh_ttl_days=int(os.getenv("PORTAL_REFRESH_TTL_DAYS", "14")),
        demo_login=_bool(os.getenv("PORTAL_DEMO_LOGIN"), not prod),
        admin_password=os.getenv("PORTAL_ADMIN_PASSWORD"),
        seed_demo=_bool(os.getenv("PORTAL_SEED_DEMO"), not prod),
        cors_origins=[o.strip() for o in os.getenv("PORTAL_CORS_ORIGINS", "" if prod else "*").split(",") if o.strip()],
        login_rate_per_minute=int(os.getenv("PORTAL_LOGIN_RATE_PER_MINUTE", "10")),
        grievance_rate_per_hour=int(os.getenv("PORTAL_GRIEVANCE_RATE_PER_HOUR", "5")),
        track_rate_per_minute=int(os.getenv("PORTAL_TRACK_RATE_PER_MINUTE", "20")),
        verify_rate_per_minute=int(os.getenv("PORTAL_VERIFY_RATE_PER_MINUTE", "60")),
        ingest_rate_per_minute=int(os.getenv("PORTAL_INGEST_RATE_PER_MINUTE", "120")),
        weather_enabled=_bool(os.getenv("PORTAL_WEATHER_ENABLED"), True),
        weather_ttl_minutes=int(os.getenv("PORTAL_WEATHER_TTL_MINUTES", "30")),
    )


def validate(s: Settings) -> list[str]:
    """Problems that must stop a production start. Empty list = OK."""
    if not s.is_production:
        return []
    problems = []
    if s.uses_mongomock:
        problems.append("MONGODB_URI must point at a real MongoDB cluster in production (not empty, not mongomock://).")
    if not s.jwt_secret_from_env or len(s.jwt_secret) < 32:
        problems.append("PORTAL_JWT_SECRET must be set to at least 32 characters.")
    if s.demo_login:
        problems.append("PORTAL_DEMO_LOGIN must be false in production.")
    if not s.cors_origins or "*" in s.cors_origins:
        problems.append("PORTAL_CORS_ORIGINS must list explicit origins in production (no '*').")
    if not s.admin_password or len(s.admin_password) < 12:
        problems.append("PORTAL_ADMIN_PASSWORD must be set (12+ characters) so the state admin can sign in.")
    return problems


settings = load()


def reload() -> Settings:
    """Re-read the environment (tests)."""
    global settings
    settings = load()
    return settings
