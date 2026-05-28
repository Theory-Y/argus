"""server.app — FastAPI application factory and wiring."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db.session import init_db
from .routes import account, billing, memos, sector, tickers


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TheoryY Research API",
        version="1.0.0",
        description="Institutional equity research memos as a service.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Create tables up front. Fine for SQLite/self-host; SaaS uses Alembic on top.
    init_db()

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "auth_mode": settings.auth_mode}

    app.include_router(tickers.router)
    app.include_router(sector.router)
    app.include_router(memos.router)
    # account + billing routers self-disable (404) in license mode.
    app.include_router(account.router)
    app.include_router(billing.router)

    return app


app = create_app()
