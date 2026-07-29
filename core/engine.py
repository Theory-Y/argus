"""
core.engine — internal façade over the deterministic data engine in ../src.

PROPRIETARY. We reuse the existing engine modules verbatim rather than
reimplementing them. Those
modules use bare imports (e.g. ``from financial_service import ...``), so ``src/``
must be on ``sys.path`` before importing them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"

if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


def build_context(ticker: str, output_dir: str | Path) -> str:
    """Fetch the deterministic data payload for one ticker; return minified JSON.

    Reuses ``context_aggregator.ContextAggregator.build_minified_context`` which
    also writes ``context_<TICKER>.json`` into ``output_dir`` as a side effect.
    """
    from context_aggregator import ContextAggregator

    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker must not be empty")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    return ContextAggregator(output_dir=out).build_minified_context(ticker)


def supported_tickers() -> dict[str, Any]:
    """Return the pre-configured ticker universe and peer mappings."""
    from context_aggregator import COMPETITOR_MAP
    from financial_service import SECTOR_TICKERS

    return {
        "sector_tickers": list(SECTOR_TICKERS),
        "competitor_map": COMPETITOR_MAP,
    }


def resolve_tickers(tickers: list[str]) -> list[str]:
    """Normalise a user-supplied ticker list.

    Mirrors ``mcp_server._resolve_tickers``: an empty list expands to the full
    sector universe; unknown tickers are allowed through (yfinance may still
    return data).
    """
    from financial_service import SECTOR_TICKERS

    if not tickers:
        return list(SECTOR_TICKERS)
    cleaned = [t.upper().strip() for t in tickers if t and t.strip()]
    if not cleaned:
        raise ValueError("all provided tickers were empty strings")
    return cleaned


def export_sector_sheet(tickers: list[str], out_path: str | Path) -> str:
    """Write the valuation comparables CSV to ``out_path``; return the path."""
    from financial_service import FinancialService

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    FinancialService().export_sector_sheet(resolve_tickers(tickers), str(out))
    return str(out)
