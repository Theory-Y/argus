"""theory_y.client — HTTP wrapper for the TheoryY Research API."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from . import config


class TheoryYError(RuntimeError):
    """Raised when the API returns a non-success status."""


class Client:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        resolved_url, resolved_key = config.resolve(base_url, api_key)
        headers = {"X-API-Key": resolved_key} if resolved_key else {}
        self._http = httpx.Client(
            base_url=resolved_url,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,  # S3 presigned download redirects
        )
        self.base_url = resolved_url

    # ── internals ────────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        resp = self._http.request(method, path, **kwargs)
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise TheoryYError(f"{resp.status_code}: {detail}")
        return resp

    # ── public API ───────────────────────────────────────────────────────────
    def health(self) -> dict:
        return self._request("GET", "/health").json()

    def tickers(self) -> dict:
        return self._request("GET", "/api/v1/tickers").json()

    def sector(self, tickers: list[str]) -> str:
        return self._request("POST", "/api/v1/sector", json={"tickers": tickers}).text

    def create_memo(self, ticker: str, fmt: str = "pdf") -> dict:
        return self._request(
            "POST", "/api/v1/memos", json={"ticker": ticker, "format": fmt}
        ).json()

    def list_memos(self, limit: int = 50) -> list[dict]:
        return self._request("GET", "/api/v1/memos", params={"limit": limit}).json()

    def memo_status(self, job_id: str) -> dict:
        return self._request("GET", f"/api/v1/memos/{job_id}").json()

    def wait_for(self, job_id: str, poll: float = 3.0, timeout: float = 600.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            status = self.memo_status(job_id)
            if status["status"] in ("complete", "failed"):
                return status
            if time.monotonic() > deadline:
                raise TheoryYError(f"Timed out waiting for job {job_id}")
            time.sleep(poll)

    def download(self, job_id: str, fmt: str, out_path: str | Path) -> Path:
        resp = self._request(
            "GET", f"/api/v1/memos/{job_id}/download", params={"format": fmt}
        )
        out = Path(out_path)
        out.write_bytes(resp.content)
        return out

    def generate(
        self,
        ticker: str,
        fmt: str = "pdf",
        out_path: str | Path | None = None,
        poll: float = 3.0,
        timeout: float = 600.0,
    ) -> Path:
        """Submit → wait → download in one call. Returns the saved file path."""
        job = self.create_memo(ticker, fmt)
        result = self.wait_for(job["job_id"], poll=poll, timeout=timeout)
        if result["status"] == "failed":
            raise TheoryYError(f"Memo generation failed: {result.get('error')}")
        out = out_path or f"TheoryY_Memo_{ticker.upper()}.{fmt}"
        return self.download(job["job_id"], fmt, out)

    # ── account (SaaS mode only) ─────────────────────────────────────────────
    def signup(self, email: str, password: str) -> str:
        token = self._request(
            "POST", "/api/v1/account/signup", json={"email": email, "password": password}
        ).json()["access_token"]
        return token

    def login(self, email: str, password: str) -> str:
        token = self._request(
            "POST", "/api/v1/account/login", json={"email": email, "password": password}
        ).json()["access_token"]
        return token

    def create_api_key(self, name: str = "default") -> dict:
        return self._request("POST", "/api/v1/account/keys", json={"name": name}).json()

    def list_api_keys(self) -> list[dict]:
        return self._request("GET", "/api/v1/account/keys").json()

    def usage(self) -> dict:
        return self._request("GET", "/api/v1/account/usage").json()

    def checkout(self, plan: str) -> str:
        return self._request("POST", "/api/v1/billing/checkout", json={"plan": plan}).json()["url"]

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
