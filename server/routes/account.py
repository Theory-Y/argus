"""Account management (SaaS mode): signup, login, API keys, usage.

All routes 404 in license mode via the require_saas guard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..billing.plans import current_billing_period, quota_for
from ..db.models import ApiKey, Subscription, UsageRecord, User
from ..db.session import get_db
from ..deps import current_user, require_saas
from ..schemas import (
    ApiKeyCreated,
    ApiKeyCreateRequest,
    ApiKeyInfo,
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UsageResponse,
)
from ..security import generate_api_key, hash_password, issue_jwt, verify_password

router = APIRouter(prefix="/api/v1/account", tags=["account"], dependencies=[Depends(require_saas)])


@router.post("/signup", response_model=TokenResponse, status_code=201)
def signup(req: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.scalar(select(User).where(User.email == req.email)):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=req.email, password_hash=hash_password(req.password))
    db.add(user)
    db.flush()
    db.add(Subscription(user_id=user.id, plan="free", status="active"))
    db.commit()
    return TokenResponse(access_token=issue_jwt(user.id))


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == req.email))
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=issue_jwt(user.id))


@router.post("/keys", response_model=ApiKeyCreated, status_code=201)
def create_key(
    req: ApiKeyCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ApiKeyCreated:
    full_key, prefix, secret_hash = generate_api_key()
    db.add(ApiKey(user_id=user.id, prefix=prefix, secret_hash=secret_hash, name=req.name))
    db.commit()
    return ApiKeyCreated(api_key=full_key, prefix=prefix, name=req.name)


@router.get("/keys", response_model=list[ApiKeyInfo])
def list_keys(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[ApiKeyInfo]:
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id)).all()
    return [
        ApiKeyInfo(
            prefix=k.prefix,
            name=k.name,
            created_at=k.created_at.isoformat(),
            revoked=k.revoked_at is not None,
        )
        for k in keys
    ]


@router.delete("/keys/{prefix}", status_code=204)
def revoke_key(prefix: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    from datetime import datetime, timezone

    key = db.scalar(select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.user_id == user.id))
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()


@router.get("/usage", response_model=UsageResponse)
def usage(user: User = Depends(current_user), db: Session = Depends(get_db)) -> UsageResponse:
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    plan = sub.plan if sub else "free"
    period = current_billing_period()
    used = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == user.id, UsageRecord.billing_period == period)
        .count()
    )
    return UsageResponse(plan=plan, billing_period=period, used=used, quota=quota_for(plan))
