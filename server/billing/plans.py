"""server.billing.plans — subscription tiers and their monthly memo quotas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import get_settings


@dataclass(frozen=True)
class Plan:
    name: str
    monthly_quota: int | None  # None = unlimited
    price_usd: int
    stripe_price_attr: str | None  # which Settings field holds the Stripe price id


_PLANS: dict[str, Plan] = {
    "free": Plan("free", monthly_quota=5, price_usd=0, stripe_price_attr=None),
    "pro": Plan("pro", monthly_quota=100, price_usd=29, stripe_price_attr="stripe_price_pro"),
    "team": Plan("team", monthly_quota=500, price_usd=99, stripe_price_attr="stripe_price_team"),
    "enterprise": Plan("enterprise", monthly_quota=None, price_usd=0, stripe_price_attr=None),
}


def get_plan(name: str) -> Plan:
    return _PLANS.get(name, _PLANS["free"])


def quota_for(plan_name: str) -> int | None:
    return get_plan(plan_name).monthly_quota


def stripe_price_id(plan_name: str) -> str | None:
    plan = get_plan(plan_name)
    if not plan.stripe_price_attr:
        return None
    return getattr(get_settings(), plan.stripe_price_attr) or None


def plan_for_stripe_price(price_id: str) -> str | None:
    """Reverse-map a Stripe price id back to a plan name (for webhook handling)."""
    for name in ("pro", "team"):
        if stripe_price_id(name) == price_id:
            return name
    return None


def current_billing_period() -> str:
    """Month bucket used for quota counting, e.g. '2026-05'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")
