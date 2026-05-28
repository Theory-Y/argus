"""server.config — env-driven settings. The AUTH_MODE switch is the business-model hinge."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Business-model switch ────────────────────────────────────────────────
    auth_mode: Literal["license", "saas"] = "license"

    # ── Persistence ──────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./theoryy_service.db"

    # ── Memo generation (Anthropic) ──────────────────────────────────────────
    # ANTHROPIC_API_KEY is read directly by the anthropic SDK from the env.
    anthropic_model: str = "claude-opus-4-7"
    anthropic_effort: str = "high"
    anthropic_max_tokens: int = 16000

    # ── Storage ──────────────────────────────────────────────────────────────
    storage_backend: Literal["local", "s3"] = "local"
    storage_dir: str = "output/service"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_prefix: str = "memos"
    signed_url_ttl: int = 86400  # seconds

    # ── Background queue ─────────────────────────────────────────────────────
    queue_backend: Literal["inprocess", "rq"] = "inprocess"
    redis_url: str = "redis://localhost:6379/0"

    # ── License mode ─────────────────────────────────────────────────────────
    # If empty, the self-hosted server runs open (trusted network). If set, the
    # client must present a license token signed with this secret.
    license_secret: str = ""

    # ── SaaS mode ────────────────────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production"
    jwt_ttl_seconds: int = 86400

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Map plan name → Stripe price id (set in SaaS deployments).
    stripe_price_pro: str = ""
    stripe_price_team: str = ""

    # ── CORS (web client origin) ─────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
