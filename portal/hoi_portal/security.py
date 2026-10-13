"""Password hashing (PBKDF2-HMAC-SHA256, 200k iterations), signed access tokens (JWT HS256), opaque refresh tokens and API keys."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from . import config

ITERATIONS = 200_000
API_KEY_PREFIX = "uthp_"


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS).hex(), salt.hex()


def verify_password(password: str, pw_hash: str, salt_hex: str) -> bool:
    calc, _ = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(calc, pw_hash)


def burn_time(password: str) -> None:
    """Same work for unknown usernames so response time does not reveal which accounts exist."""
    hash_password(password, b"0" * 16)


def issue_token(user: dict) -> str:
    s = config.settings
    now = datetime.now(UTC)
    claims = {
        "sub": user["id"],
        "usr": user["username"],
        "role": user["role"],
        "dst": user.get("district"),
        "iat": now,
        "exp": now + timedelta(minutes=s.access_ttl_minutes),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, config.settings.jwt_secret, algorithms=["HS256"])


def sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Opaque refresh token for the client and its SHA-256 for storage (the raw token is never stored)."""
    raw = secrets.token_urlsafe(48)
    return raw, sha256(raw)


def new_api_key() -> tuple[str, str]:
    """Business API key (shown once) and its SHA-256 (stored)."""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, sha256(raw)


def new_tracking_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def tracking_hash(ticket_id: str, code: str) -> str:
    return sha256(f"{ticket_id}:{code}")


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
