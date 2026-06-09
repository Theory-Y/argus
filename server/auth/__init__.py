"""server.auth — pluggable authentication.

One ``AuthProvider`` interface, two implementations. ``get_auth_provider()`` picks
the one named by ``AUTH_MODE`` — flipping that single env var switches the whole
service between the source-sale/self-host model and the hosted SaaS model.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.session import get_db
from .base import AuthProvider, Principal
from .license import LicenseAuthProvider
from .saas import SaasAuthProvider


@lru_cache
def get_auth_provider() -> AuthProvider:
    if get_settings().auth_mode == "saas":
        return SaasAuthProvider()
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
