"""server.auth.base — the AuthProvider contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session


@dataclass
class Principal:
    """The authenticated caller. ``id`` is None for open/self-host license mode."""

    id: str | None
    kind: str  # "license"
    plan: str  # "self_hosted" | "licensed"
    monthly_quota: int | None  # None = unlimited


class AuthProvider(Protocol):
    def authenticate(
        self, token: str | None, db: Session, user_id: str | None = None
    ) -> Principal:
        """Resolve a token into a Principal, or raise HTTPException(401).

        ``user_id`` is the end-user a trusted gateway (our Cloudflare Worker) is
        acting on behalf of, forwarded via the ``X-User-Id`` header. It is honored
        only by providers that can first prove the caller is trusted; license mode
        accepts it only when a valid ``LICENSE_SECRET`` token was presented.
        """
        ...

    def check_quota(self, principal: Principal, db: Session) -> None:
        """Raise HTTPException(402) if the principal is over quota."""
        ...

    def record_usage(self, principal: Principal, job_id: str, db: Session) -> None:
        """Record a completed action (no-op in license mode)."""
        ...
