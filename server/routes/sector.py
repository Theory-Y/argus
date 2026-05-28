"""POST /api/v1/sector — valuation comparables CSV for a list of tickers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from core import engine

from ..auth import Principal, authenticate
from ..schemas import SectorRequest

router = APIRouter(prefix="/api/v1", tags=["sector"])


@router.post("/sector", response_class=PlainTextResponse)
def sector_sheet(req: SectorRequest, _: Principal = Depends(authenticate)) -> PlainTextResponse:
    with tempfile.TemporaryDirectory(prefix="theoryy_sector_") as work:
        out = Path(work) / "sector.csv"
        try:
            engine.export_sector_sheet(req.tickers, out)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sector sheet failed: {exc}")
        csv_text = out.read_text(encoding="utf-8")
    return PlainTextResponse(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="TheoryY_Sector_Sheet.csv"'},
    )
