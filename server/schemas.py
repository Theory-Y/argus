"""server.schemas — request/response models for the public API contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

MemoFormat = Literal["md", "pdf", "docx"]


class MemoCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    format: MemoFormat = "pdf"


class MemoJob(BaseModel):
    job_id: str
    ticker: str
    status: str
    progress: int
    error: str | None = None
    formats: list[str] = []


class SectorRequest(BaseModel):
    tickers: list[str] = []


class TickersResponse(BaseModel):
    sector_tickers: list[str]
    competitor_map: dict[str, list[str]]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(default="default", max_length=128)


class ApiKeyCreated(BaseModel):
    api_key: str  # shown once
    prefix: str
    name: str


class ApiKeyInfo(BaseModel):
    prefix: str
    name: str
    created_at: str
    revoked: bool


class UsageResponse(BaseModel):
    plan: str
    billing_period: str
    used: int
    quota: int | None  # None = unlimited


class CheckoutRequest(BaseModel):
    plan: Literal["pro", "team"]


class UrlResponse(BaseModel):
    url: str
