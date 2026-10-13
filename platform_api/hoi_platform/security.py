"""Password hashing (PBKDF2-HMAC-SHA256) and signed access tokens (JWT, HS256)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from . import config

ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS).hex(), salt.hex()


def verify_password(password: str, pw_hash: str, salt_hex: str) -> bool:
    calc, _ = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(calc, pw_hash)


def burn_time(password: str) -> None:
    """Do the same work for unknown usernames so response time does not reveal which accounts exist."""
    hash_password(password, b"0" * 16)


def issue_token(user: dict, impersonated_by: str | None = None, tenant_override: str | None = None) -> str:
    s = config.settings
    now = datetime.now(UTC)
    claims = {
        "sub": user["id"],
        "usr": user["username"],
        "role": user["role"],
        "tid": tenant_override or user["tenant_id"],
        "emp": user.get("employee_id"),
        "iat": now,
        "exp": now + timedelta(minutes=s.access_ttl_minutes),
    }
    if impersonated_by:
        claims["imp"] = impersonated_by
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, config.settings.jwt_secret, algorithms=["HS256"])


def new_refresh_token() -> tuple[str, str]:
    """Opaque refresh token for the client and its SHA-256 for storage (the raw token is never stored)."""
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
