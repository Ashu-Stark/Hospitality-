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
    cors_origins: list[str] = field(default_factory=list)
    public_base_url: str = ""
    login_rate_per_minute: int = 10
    mongodb_uri: str = field(default="", repr=False)
    db_name: str = "hoi_platform"

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
        cors_origins=[o.strip() for o in os.getenv("HOI_CORS_ORIGINS", "*" if env != "production" else "").split(",") if o.strip()],
        public_base_url=os.getenv("HOI_PUBLIC_BASE_URL", "").rstrip("/"),
        login_rate_per_minute=int(os.getenv("HOI_LOGIN_RATE_PER_MINUTE", "10")),
        mongodb_uri=os.getenv("MONGODB_URI", "").strip(),
        db_name=os.getenv("HOI_PLATFORM_DB", "").strip() or "hoi_platform",
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
