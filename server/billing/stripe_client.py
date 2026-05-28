"""server.billing.stripe_client — thin Stripe wrapper (SaaS mode only)."""

from __future__ import annotations

from fastapi import HTTPException

from ..config import get_settings
from ..db.models import User
from .plans import stripe_price_id


def _web_base() -> str:
    origins = get_settings().cors_origin_list
    return origins[0] if origins else "http://localhost:5173"


def _stripe():
    import stripe

    s = get_settings()
    if not s.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    stripe.api_key = s.stripe_secret_key
    return stripe


def create_checkout_session(user: User, plan: str) -> str:
    stripe = _stripe()
    price = stripe_price_id(plan)
    if not price:
        raise HTTPException(status_code=400, detail=f"No Stripe price configured for '{plan}'")
    base = _web_base()
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price, "quantity": 1}],
        client_reference_id=user.id,
        customer=user.stripe_customer_id or None,
        customer_email=None if user.stripe_customer_id else user.email,
        metadata={"user_id": user.id, "plan": plan},
        success_url=f"{base}/account?checkout=success",
        cancel_url=f"{base}/account?checkout=cancel",
    )
    return session.url


def create_billing_portal(user: User) -> str:
    stripe = _stripe()
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account yet")
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{_web_base()}/account",
    )
    return session.url


def construct_event(payload: bytes, sig_header: str):
    stripe = _stripe()
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")
    try:
        return stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid webhook signature: {exc}")
