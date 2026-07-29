"""server.auth — pluggable authentication.

One ``AuthProvider`` interface; license mode (source-sale/self-host) is the
only implementation.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from ..db.session import get_db
from .base import AuthProvider, Principal
from .license import LicenseAuthProvider


@lru_cache
def get_auth_provider() -> AuthProvider:
    return LicenseAuthProvider()


def _extract_token(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def authenticate(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> Principal:
    """FastAPI dependency: resolve the caller into a Principal or raise 401.

    ``X-User-Id`` names the end user a trusted gateway (our Cloudflare Worker) is
    acting for. It is passed to the provider, which decides whether to trust it —
    license mode does so only after verifying the gateway's ``LICENSE_SECRET`` token.
    """
    token = _extract_token(authorization, x_api_key)
    return get_auth_provider().authenticate(token, db, x_user_id)


__all__ = ["AuthProvider", "Principal", "authenticate", "get_auth_provider"]
