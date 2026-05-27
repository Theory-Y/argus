"""
financial_service.py — Valuation Engine
========================================
Fetches, transforms, and exports financial comparables for the
PropTech & Facilities sector using yfinance (no API key required).

Architecture (Clean Architecture + SOLID):
  - FinancialDataFetcher   → Infrastructure: raw yfinance I/O only
  - FinancialDataTransformer → Domain: mapping + ratio maths, no I/O
  - FinancialExporter      → Application: serialisation to CSV/DataFrame
  - FinancialService       → Façade: composes the three layers above
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

SECTOR_TICKERS: List[str] = [
    "CSGP", "CBRE", "CARR", "TT",   "JCI",
    "LII",  "ABM",  "CTAS", "ADT",  "ALLE",
    "HON",  "PCOR", "APPF", "Z",
]

NM: str = "N/M"                  # Not Meaningful — undefined or negative ratio
_MILLION: float = 1_000_000.0
_FETCH_DELAY: float = 0.6        # Seconds between yfinance calls (rate-limit courtesy)

OUTPUT_CSV: str = "TheoryY_Sector_Sheet.csv"


# ──────────────────────────────────────────────────────────────────────────────
# Domain Model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CompanyFinancials:
    """Typed snapshot of one company's key financial metrics (all $ in millions)."""

    ticker: str
    name: str
    market_cap_mm: Optional[float]          # Market capitalisation, USD MM
    enterprise_value_mm: Optional[float]    # Enterprise value, USD MM
    trailing_revenue_mm: Optional[float]    # TTM revenue, USD MM
    trailing_ebitda_mm: Optional[float]     # TTM EBITDA, USD MM
    forward_pe: Optional[float]             # Forward price-to-earnings
    yoy_revenue_growth_pct: Optional[float] # e.g. 12.5 means +12.5 %
    ev_revenue: Union[float, str]           # Calculated EV/Revenue or "N/M"
    ev_ebitda: Union[float, str]            # Calculated EV/EBITDA or "N/M"


# ──────────────────────────────────────────────────────────────────────────────
# Layer 1 — Infrastructure: raw data fetcher
# ──────────────────────────────────────────────────────────────────────────────

class FinancialDataFetcher:
    """
    Thin adapter over yfinance.
    Single responsibility: fetch raw API payload; zero transformation.
    """

    def fetch_ticker_info(self, ticker: str) -> Dict:
        """
        Return the yfinance `.info` dict for *ticker*.
        Returns an empty dict on any error so callers never receive an exception.
        """
        try:
            t = yf.Ticker(ticker)
            info: Dict = t.info
            if not info or "symbol" not in info:
                logger.warning("yfinance returned empty/invalid info for %s", ticker)
                return {}
            return info
        except Exception as exc:                                # pragma: no cover
            logger.error("yfinance fetch failed for %s: %s", ticker, exc)
            return {}


# ──────────────────────────────────────────────────────────────────────────────
# Layer 2 — Domain: transformation + ratio calculation
# ──────────────────────────────────────────────────────────────────────────────

class FinancialDataTransformer:
    """
    Maps a raw yfinance info dict → CompanyFinancials.
    Single responsibility: data shaping and ratio maths; no I/O.
    """

    def transform(self, ticker: str, raw_info: Dict) -> CompanyFinancials:
        name = (
            raw_info.get("longName")
            or raw_info.get("shortName")
            or ticker
        )

        market_cap_mm        = self._to_mm(raw_info.get("marketCap"))
        ev_mm                = self._to_mm(raw_info.get("enterpriseValue"))
        revenue_mm           = self._to_mm(raw_info.get("totalRevenue"))
        ebitda_mm            = self._to_mm(raw_info.get("ebitda"))
        forward_pe           = self._safe_float(raw_info.get("forwardPE"), positive_only=True)
        yoy_growth_pct       = self._growth_to_pct(raw_info.get("revenueGrowth"))

        return CompanyFinancials(
            ticker=ticker,
            name=name,
            market_cap_mm=market_cap_mm,
            enterprise_value_mm=ev_mm,
            trailing_revenue_mm=revenue_mm,
            trailing_ebitda_mm=ebitda_mm,
            forward_pe=forward_pe,
            yoy_revenue_growth_pct=yoy_growth_pct,
            ev_revenue=self._ratio(ev_mm, revenue_mm, require_positive_denom=False),
            ev_ebitda=self._ratio(ev_mm, ebitda_mm, require_positive_denom=True),
        )

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _to_mm(value: Optional[object]) -> Optional[float]:
        """Convert raw dollar value → USD millions, rounded to 2 dp."""
        if value is None:
            return None
        try:
            return round(float(value) / _MILLION, 2)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(value: Optional[object], positive_only: bool = False) -> Optional[float]:
        if value is None:
            return None
        try:
            f = float(value)
            if positive_only and f <= 0:
                return None
            return round(f, 2)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _growth_to_pct(value: Optional[object]) -> Optional[float]:
        """yfinance returns revenueGrowth as a decimal (0.15 = 15 %)."""
        if value is None:
            return None
        try:
            return round(float(value) * 100, 2)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _ratio(
        numerator: Optional[float],
        denominator: Optional[float],
        require_positive_denom: bool = False,
    ) -> Union[float, str]:
        """
        Return numerator / denominator, or NM when:
          - either operand is missing, OR
          - denominator is zero, OR
          - require_positive_denom=True and denominator ≤ 0
            (negative EBITDA makes EV/EBITDA meaningless).
        """
        if numerator is None or denominator is None:
            return NM
        if denominator == 0:
            return NM
        if require_positive_denom and denominator <= 0:
            return NM
        return round(numerator / denominator, 2)


# ──────────────────────────────────────────────────────────────────────────────
# Layer 3 — Application: output formatter / exporter
# ──────────────────────────────────────────────────────────────────────────────

class FinancialExporter:
    """
    Converts a list of CompanyFinancials objects into publication-ready output.
    Single responsibility: serialisation; no fetching or calculation.
    """

    _COLUMN_ORDER: List[str] = [
        "ticker", "name",
        "market_cap_mm", "enterprise_value_mm",
        "trailing_revenue_mm", "trailing_ebitda_mm",
        "forward_pe", "yoy_revenue_growth_pct",
        "ev_revenue", "ev_ebitda",
    ]

    _DISPLAY_HEADERS: Dict[str, str] = {
        "ticker":                 "Ticker",
        "name":                   "Company",
        "market_cap_mm":          "Mkt Cap ($MM)",
        "enterprise_value_mm":    "EV ($MM)",
        "trailing_revenue_mm":    "Revenue TTM ($MM)",
        "trailing_ebitda_mm":     "EBITDA TTM ($MM)",
        "forward_pe":             "Fwd P/E",
        "yoy_revenue_growth_pct": "YoY Rev Growth (%)",
        "ev_revenue":             "EV / Revenue",
        "ev_ebitda":              "EV / EBITDA",
    }

    def to_dataframe(self, financials: List[CompanyFinancials]) -> pd.DataFrame:
        rows = [asdict(f) for f in financials]
        df = pd.DataFrame(rows, columns=self._COLUMN_ORDER)
        return df.rename(columns=self._DISPLAY_HEADERS)

    def to_csv(self, financials: List[CompanyFinancials], output_path: Path) -> None:
        df = self.to_dataframe(financials)
        df.to_csv(output_path, index=False)
        logger.info("Sector sheet written → %s  (%d rows)", output_path.resolve(), len(df))


# ──────────────────────────────────────────────────────────────────────────────
# Service Façade — composes all three layers
# ──────────────────────────────────────────────────────────────────────────────

class FinancialService:
    """
    High-level entry point for all callers (ContextAggregator, CLI, tests).
    Accepts injected collaborators for easy unit-test mocking.
    """

    def __init__(
        self,
        fetcher:     Optional[FinancialDataFetcher]     = None,
        transformer: Optional[FinancialDataTransformer] = None,
        exporter:    Optional[FinancialExporter]        = None,
    ) -> None:
        self._fetcher     = fetcher     or FinancialDataFetcher()
        self._transformer = transformer or FinancialDataTransformer()
        self._exporter    = exporter    or FinancialExporter()

    # ── public API ────────────────────────────────────────────────────────────

    def get_company_financials(self, ticker: str) -> CompanyFinancials:
        """Fetch and transform a single ticker synchronously."""
        raw = self._fetcher.fetch_ticker_info(ticker)
        return self._transformer.transform(ticker, raw)

    def get_sector_financials(
        self, tickers: List[str] = SECTOR_TICKERS
    ) -> List[CompanyFinancials]:
        """
        Fetch all tickers with a polite inter-request delay.
        Returns results in the same order as *tickers*.
        """
        results: List[CompanyFinancials] = []
        for i, ticker in enumerate(tickers, start=1):
            logger.info("[%d/%d] Fetching %s …", i, len(tickers), ticker)
            results.append(self.get_company_financials(ticker))
            if i < len(tickers):
                time.sleep(_FETCH_DELAY)
        return results

    def export_sector_sheet(
        self,
        tickers:     List[str] = SECTOR_TICKERS,
        output_path: str       = OUTPUT_CSV,
    ) -> List[CompanyFinancials]:
        """Fetch → transform → write CSV. Returns the data for downstream use."""
        financials = self.get_sector_financials(tickers)
        self._exporter.to_csv(financials, Path(output_path))
        return financials


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )
    svc = FinancialService()
    svc.export_sector_sheet()
