"""server.deps — shared FastAPI dependencies for SaaS web-session routes."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .db.models import User
from .db.session import get_db
from .security import decode_jwt


def require_saas() -> None:
    """Block account/billing routes when running in license mode."""
    if get_settings().auth_mode != "saas":
        raise HTTPException(status_code=404, detail="Not available in license mode")


def current_user(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> User:
    """Resolve a web-session JWT into a User, or 401.

    Accepts the JWT via either ``Authorization: Bearer`` or ``X-API-Key`` so the
    web dashboard and the CLI (both of which send X-API-Key) work uniformly. An
    API key (``ty_...``) is not a JWT and will not decode — account management
    requires being logged in.
    """
    token = x_api_key
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Login required")
    user_id = decode_jwt(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user
