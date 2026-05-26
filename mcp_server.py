import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from alt_data_service import AltDataService
from context_aggregator import COMPETITOR_MAP, ContextAggregator
from financial_service import SECTOR_TICKERS, FinancialService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Startup checks
# ──────────────────────────────────────────────────────────────────────────────

_MISSING_ENV: list[str] = []
if not os.environ.get("FRED_API_KEY"):
    _MISSING_ENV.append("FRED_API_KEY (macro data will be unavailable)")
if not os.environ.get("SEC_USER_AGENT"):
    _MISSING_ENV.append("SEC_USER_AGENT (SEC EDGAR will return 403)")

for warn in _MISSING_ENV:
    logger.warning("Environment variable not set: %s", warn)

# ──────────────────────────────────────────────────────────────────────────────
# Shared service instances — created once, reused across all tool calls.
# This preserves the SecCikResolver CIK cache, HTTP sessions, and avoids
# rebuilding collaborator graphs on every invocation.
# ──────────────────────────────────────────────────────────────────────────────

_financial_service = FinancialService()
_alt_data_service  = AltDataService()
_aggregator        = ContextAggregator(
    financial_service=_financial_service,
    alt_data_service=_alt_data_service,
)

# ──────────────────────────────────────────────────────────────────────────────
# MCP server
# ──────────────────────────────────────────────────────────────────────────────

mcp = FastMCP("TheoryY_Finance_Oracle")

_OUTPUT_CSV = "TheoryY_Sector_Sheet.csv"
_VALID_TICKERS = set(SECTOR_TICKERS)


@mcp.tool()
def generate_sector_sheet(tickers: list[str]) -> str:
    """
    Generate a CSV of valuation metrics (Market Cap, EV, EV/Revenue, EV/EBITDA,
    Fwd P/E, YoY Revenue Growth) for one or more PropTech & Facilities companies.

    Args:
        tickers: Stock tickers to include, e.g. ["CARR", "PCOR", "CBRE"].
                 Pass an empty list to run all 14 sector tickers.

    Returns:
        On success: "Saved: <absolute path>" — the CSV is also written to disk.
        On failure: "Error: <message>" — check FRED_API_KEY / network access.
        Rows with missing yfinance data will contain null values, not errors.
    """
    resolved = _resolve_tickers(tickers)
    if isinstance(resolved, str):      # validation error message
        return resolved
    try:
        _financial_service.export_sector_sheet(resolved, _OUTPUT_CSV)
        return f"Saved: {os.path.abspath(_OUTPUT_CSV)}  ({len(resolved)} tickers)"
    except Exception as exc:
        logger.exception("generate_sector_sheet failed")
        return f"Error: {exc}"


@mcp.tool()
def build_company_context(ticker: str) -> str:
    """
    Build a minified JSON context payload for a single company, combining:
      • Fundamental financials (via yfinance)
      • Three peer comparables
      • Google Trends search-velocity signal (12-month)
      • FRED commercial construction macro (TLNRESCONS)
      • SEC 10-K Item 1A risk-factor snippet
      • SEC 8-K material-event feed (last 12 months, item-labeled)
      • GlobeNewswire press releases (last 5, public RSS)
      • Stanford SCAC securities litigation monitor
      • Apify job-market signal (stub until APIFY_API_KEY is set)

    The JSON is whitespace-stripped for LLM token efficiency. Individual
    data sources that fail return {"error": "<message>"} inside their key
    rather than aborting the whole payload.

    Args:
        ticker: Target stock ticker, e.g. "PCOR". Case-insensitive.

    Returns:
        Minified JSON string, or "Error: <message>" if the pipeline fails entirely.
    """
    ticker_up = ticker.upper().strip()
    if not ticker_up:
        return "Error: ticker must not be empty"

    try:
        return _aggregator.build_minified_context(ticker_up)
    except Exception as exc:
        logger.exception("build_company_context failed for %s", ticker_up)
        return f"Error: {exc}"


@mcp.tool()
def list_supported_tickers() -> dict[str, Any]:
    """
    Return the set of tickers this server has pre-configured competitor mappings
    for, along with their known peer groups.

    Use this before calling build_company_context to confirm a ticker is supported.
    Tickers outside this list can still be queried but will have an empty peers list.
    """
    return {
        "sector_tickers": SECTOR_TICKERS,
        "competitor_map": COMPETITOR_MAP,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_tickers(tickers: list[str]) -> list[str] | str:
    """
    Validate and normalise a user-supplied ticker list.
    Returns a clean list, or an error string if input is unusable.
    """
    if not tickers:
        return list(SECTOR_TICKERS)

    cleaned = [t.upper().strip() for t in tickers if t and t.strip()]
    if not cleaned:
        return "Error: all provided tickers were empty strings"

    unknown = [t for t in cleaned if t not in _VALID_TICKERS]
    if unknown:
        logger.warning("Unrecognised tickers passed to generate_sector_sheet: %s", unknown)
        # Allow through — yfinance may still return data; row will contain nulls

    return cleaned


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting TheoryY Finance Oracle MCP Server …")
    if _MISSING_ENV:
        logger.warning("Degraded mode — missing env vars: %s", ", ".join(_MISSING_ENV))
    mcp.run(transport="stdio")
