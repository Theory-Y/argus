"""server.config — env-driven settings. The AUTH_MODE switch is the business-model hinge."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_KNOWN_PLACEHOLDER = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Business-model switch ────────────────────────────────────────────────
    auth_mode: Literal["license", "saas"] = "license"

    # ── Persistence ──────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./theoryy_service.db"

    # ── Memo generation (Anthropic) ──────────────────────────────────────────
    # ANTHROPIC_API_KEY is read directly by the anthropic SDK from the env.
    anthropic_model: str = "claude-opus-4-7"
    anthropic_effort: str = "medium"
    anthropic_max_tokens: int = 6000

    # ── Storage ──────────────────────────────────────────────────────────────
    storage_backend: Literal["local", "s3"] = "local"
    storage_dir: str = "output/service"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"  # use "auto" for Cloudflare R2
    s3_prefix: str = "memos"
    signed_url_ttl: int = 86400  # seconds
    # For S3-compatible stores (Cloudflare R2, MinIO): set the endpoint + keys.
    # R2 endpoint looks like https://<accountid>.r2.cloudflarestorage.com
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # ── Background queue ─────────────────────────────────────────────────────
    queue_backend: Literal["inprocess", "rq"] = "inprocess"
    redis_url: str = "redis://localhost:6379/0"

    # ── License mode ─────────────────────────────────────────────────────────
    # If empty, the self-hosted server runs open (trusted network). If set, the
    # client must present a license token signed with this secret.
    license_secret: str = ""

    # ── SaaS mode ────────────────────────────────────────────────────────────
    jwt_secret: str = ""
    jwt_ttl_seconds: int = 86400

    @model_validator(mode="after")
    def _require_jwt_secret_in_saas(self) -> "Settings":
        if self.auth_mode == "saas" and (
            not self.jwt_secret or self.jwt_secret == _KNOWN_PLACEHOLDER
        ):
            raise ValueError(
                "JWT_SECRET must be set to a strong random value when AUTH_MODE=saas. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return self

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
