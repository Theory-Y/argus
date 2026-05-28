"""server.security — password/secret hashing, API-key minting, JWT issuance."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt

from .config import get_settings

# API key format: "ty_<prefix>.<secret>". The prefix is stored/indexed in the
# clear for lookup; only the secret half is hashed.
_API_KEY_SEP = "."
_PREFIX_NAMESPACE = "ty_"


def _bcrypt_hash(value: str) -> str:
    # bcrypt only considers the first 72 bytes; truncate explicitly (4.1+ raises otherwise).
    return bcrypt.hashpw(value.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def _bcrypt_verify(value: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(value.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_password(password: str) -> str:
    return _bcrypt_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _bcrypt_verify(password, password_hash)


def hash_secret(secret: str) -> str:
    return _bcrypt_hash(secret)


def verify_secret(secret: str, secret_hash: str) -> bool:
    return _bcrypt_verify(secret, secret_hash)


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, secret_hash). The full key is shown to the user once."""
    prefix = _PREFIX_NAMESPACE + secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    full_key = f"{prefix}{_API_KEY_SEP}{secret}"
    return full_key, prefix, hash_secret(secret)


def split_api_key(key: str) -> tuple[str, str] | None:
    """Split 'ty_<prefix>.<secret>' into (prefix, secret); None if malformed."""
    if _API_KEY_SEP not in key or not key.startswith(_PREFIX_NAMESPACE):
        return None
    prefix, _, secret = key.partition(_API_KEY_SEP)
    if not prefix or not secret:
        return None
    return prefix, secret


def issue_jwt(user_id: str) -> str:
    s = get_settings()
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=s.jwt_ttl_seconds),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_jwt(token: str) -> str | None:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        return payload.get("sub")
    except Exception:
        return None
