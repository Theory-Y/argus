"""server.auth.license — offline license-key auth for source-sale / self-host.

No DB lookups, no quota, no metering. If ``LICENSE_SECRET`` is unset the server
runs open (trusted network). If set, the client must present a license token
signed with that secret — an HMAC token the seller mints offline and hands to the
buyer, verifiable without any callback to us.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..config import get_settings
from .base import Principal


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload_b64: str, secret: str) -> str:
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return _b64u_encode(sig)


def mint_license_token(licensee: str, days: int, secret: str) -> str:
    """Offline helper: create a license token to hand to a source-sale buyer."""
    payload = {"sub": licensee, "exp": int(time.time()) + days * 86400}
    payload_b64 = _b64u_encode(json.dumps(payload, separators=(",", ":")).encode())
    return f"{payload_b64}.{_sign(payload_b64, secret)}"


def _verify_token(token: str, secret: str) -> Principal:
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Malformed license token")
    if not hmac.compare_digest(sig, _sign(payload_b64, secret)):
        raise HTTPException(status_code=401, detail="Invalid license signature")
    payload = json.loads(_b64u_decode(payload_b64))
    if payload.get("exp", 0) < time.time():
        raise HTTPException(status_code=401, detail="License expired")
    return Principal(id=payload.get("sub"), kind="license", plan="licensed", monthly_quota=None)


class LicenseAuthProvider:
    def authenticate(self, token: str | None, db: Session) -> Principal:
        secret = get_settings().license_secret
        if not secret:
            # Open self-host: no license configured, trusted network.
            return Principal(id=None, kind="license", plan="self_hosted", monthly_quota=None)
        if not token:
            raise HTTPException(status_code=401, detail="License token required")
        return _verify_token(token, secret)

    def check_quota(self, principal: Principal, db: Session) -> None:
        return  # unlimited

    def record_usage(self, principal: Principal, job_id: str, db: Session) -> None:
        return  # not metered
