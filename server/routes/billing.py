"""Stripe billing (SaaS mode): checkout, customer portal, webhook.

All routes 404 in license mode via the require_saas guard.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..billing import stripe_client
from ..billing.plans import plan_for_stripe_price
from ..db.models import Subscription, User
from ..db.session import get_db
from ..deps import current_user, require_saas
from ..schemas import CheckoutRequest, UrlResponse

router = APIRouter(prefix="/api/v1/billing", tags=["billing"], dependencies=[Depends(require_saas)])


@router.post("/checkout", response_model=UrlResponse)
def checkout(
    req: CheckoutRequest,
    user: User = Depends(current_user),
) -> UrlResponse:
    return UrlResponse(url=stripe_client.create_checkout_session(user, req.plan))


@router.get("/portal", response_model=UrlResponse)
def portal(user: User = Depends(current_user)) -> UrlResponse:
    return UrlResponse(url=stripe_client.create_billing_portal(user))


def _upsert_subscription(db: Session, user_id: str, **fields) -> None:
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if sub is None:
        sub = Subscription(user_id=user_id)
        db.add(sub)
    for k, v in fields.items():
        setattr(sub, k, v)
    db.commit()


@router.post("/webhook")
async def webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    payload = await request.body()
    event = stripe_client.construct_event(payload, stripe_signature or "")
    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        user_id = (obj.get("metadata") or {}).get("user_id") or obj.get("client_reference_id")
        plan = (obj.get("metadata") or {}).get("plan", "pro")
        if user_id:
            user = db.get(User, user_id)
            if user and obj.get("customer"):
                user.stripe_customer_id = obj["customer"]
            _upsert_subscription(
                db,
                user_id,
                plan=plan,
                status="active",
                stripe_subscription_id=obj.get("subscription"),
            )

    elif etype in ("customer.subscription.updated", "customer.subscription.created"):
        user = db.scalar(select(User).where(User.stripe_customer_id == obj.get("customer")))
        if user:
            items = (obj.get("items") or {}).get("data") or []
            price_id = items[0]["price"]["id"] if items else None
            plan = plan_for_stripe_price(price_id) if price_id else None
            period_end = obj.get("current_period_end")
            _upsert_subscription(
                db,
                user.id,
                plan=plan or "pro",
                status=obj.get("status", "active"),
                stripe_subscription_id=obj.get("id"),
                current_period_end=(
                    datetime.fromtimestamp(period_end, tz=timezone.utc) if period_end else None
                ),
            )

    elif etype == "customer.subscription.deleted":
        user = db.scalar(select(User).where(User.stripe_customer_id == obj.get("customer")))
        if user:
            _upsert_subscription(db, user.id, plan="free", status="canceled")

    return {"received": True}
