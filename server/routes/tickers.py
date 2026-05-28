"""GET /api/v1/tickers — the supported universe + peer mappings."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core import engine

from ..auth import Principal, authenticate
from ..schemas import TickersResponse

router = APIRouter(prefix="/api/v1", tags=["tickers"])


@router.get("/tickers", response_model=TickersResponse)
def list_tickers(_: Principal = Depends(authenticate)) -> TickersResponse:
    data = engine.supported_tickers()
    return TickersResponse(
        sector_tickers=data["sector_tickers"],
        competitor_map=data["competitor_map"],
    )
