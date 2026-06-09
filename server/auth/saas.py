"""server.auth.saas — DB-backed API keys + plan quota for the hosted offering."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..billing.plans import current_billing_period, quota_for
from ..db.models import ApiKey, Subscription, UsageRecord
from ..security import decode_jwt, split_api_key, verify_secret
from .base import Principal


class SaasAuthProvider:
    def authenticate(
        self, token: str | None, db: Session, user_id: str | None = None
    ) -> Principal:
        # SaaS mode owns identity itself (API key / JWT), so the gateway X-User-Id
        # hint is ignored — the token is the source of truth for who the caller is.
        if not token:
            raise HTTPException(status_code=401, detail="API key required")

        parsed = split_api_key(token)
        if parsed:
            user_id = self._user_from_api_key(parsed, db)
        else:
            # Fall back to a web-session JWT so the browser client works too.
            user_id = decode_jwt(token)
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid credentials")

        return self._principal_for_user(user_id, db)

    def _user_from_api_key(self, parsed: tuple[str, str], db: Session) -> str:
        prefix, secret = parsed
        api_key = db.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
        if api_key is None or api_key.revoked_at is not None:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")
        if not verify_secret(secret, api_key.secret_hash):
            raise HTTPException(status_code=401, detail="Invalid API key")
        return api_key.user_id

    def _principal_for_user(self, user_id: str, db: Session) -> Principal:
        sub = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
        plan = sub.plan if sub else "free"
        return Principal(
            id=user_id,
            kind="saas",
            plan=plan,
            monthly_quota=quota_for(plan),
        )

    def check_quota(self, principal: Principal, db: Session) -> None:
        if principal.monthly_quota is None:
            return
        count = (
            db.query(UsageRecord)
            .filter(UsageRecord.user_id == principal.id)
            .filter(UsageRecord.billing_period == current_billing_period())
            .count()
        )
        if count >= principal.monthly_quota:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Monthly quota of {principal.monthly_quota} memos reached on the "
                    f"'{principal.plan}' plan. Upgrade to continue."
                ),
            )

    def record_usage(self, principal: Principal, job_id: str, db: Session) -> None:
        if principal.id is None:
            return
        db.add(
            UsageRecord(
                user_id=principal.id,
                job_id=job_id,
                action="memo",
                billing_period=current_billing_period(),
            )
        )
        db.commit()
