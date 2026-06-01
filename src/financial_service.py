"""
financial_service.py — Valuation Engine
========================================
Fetches, transforms, and exports financial comparables for any sector using
yfinance (no API key required). The transformer is fully sector-agnostic: it
captures each issuer's sector/industry classification so downstream peer
discovery and macro selection can adapt to whatever universe is requested.

Architecture (Clean Architecture + SOLID):
  - FinancialDataFetcher   → Infrastructure: raw yfinance I/O only
  - FinancialDataTransformer → Domain: mapping + ratio maths, no I/O
  - FinancialExporter      → Application: serialisation to CSV/DataFrame
  - FinancialService       → Façade: composes the three layers above
"""

from __future__ import annotations

import logging
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

# Default convenience universe. This is NOT a constraint on what the engine can
# research — any valid ticker can be fetched, peered (via dynamic discovery), and
# memo'd. This list is only the seed cohort used when a caller asks for a sector
# sheet without naming tickers, and it remains the project's original
# PropTech/Facilities cluster for backward compatibility.
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
    # ── Data-provenance & quality (additive; default-safe for existing callers) ──
    currency: Optional[str] = None          # Trading currency of price/market cap (e.g. "USD")
    financial_currency: Optional[str] = None  # Reporting currency of the statements (e.g. "TWD")
    quality_flags: List[str] = field(default_factory=list)  # Coherence-check annotations
    # ── Classification (drives sector-aware peer discovery + macro selection) ──
    sector: Optional[str] = None            # yfinance GICS-style sector, e.g. "Technology"
    industry: Optional[str] = None          # yfinance industry, e.g. "Semiconductors"


@dataclass
class PricePoint:
    """One day of price history (adjusted close)."""

    date: str                               # ISO date, "YYYY-MM-DD"
    close: float                            # Adjusted closing price, USD


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

    def fetch_price_history(
        self, ticker: str, period: str = "1y", retries: int = 3
    ) -> List["PricePoint"]:
        """
        Return the daily closing-price series for *ticker* over *period*.

        Single responsibility: raw yfinance I/O only. Yahoo intermittently
        rate-limits a fresh session, so we retry with a short backoff. Returns an
        empty list on persistent failure (network, unknown ticker) so callers
        never receive an exception — the chart layer renders an "unavailable" note.
        """
        for attempt in range(1, retries + 1):
            try:
                hist = yf.Ticker(ticker).history(
                    period=period, interval="1d", auto_adjust=True
                )
                if hist is not None and not hist.empty and "Close" in hist:
                    closes = hist["Close"].dropna()
                    return [
                        PricePoint(date=idx.strftime("%Y-%m-%d"), close=round(float(val), 4))
                        for idx, val in closes.items()
                    ]
                logger.warning(
                    "yfinance returned no price history for %s (attempt %d/%d)",
                    ticker, attempt, retries,
                )
            except Exception as exc:                            # pragma: no cover
                logger.warning(
                    "yfinance price-history fetch failed for %s (attempt %d/%d): %s",
                    ticker, attempt, retries, exc,
                )
            if attempt < retries:
                time.sleep(_FETCH_DELAY * attempt)
        logger.error("yfinance price history unavailable for %s after %d attempts",
                     ticker, retries)
        return []


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

        currency           = self._norm_ccy(raw_info.get("currency"))
        financial_currency = self._norm_ccy(raw_info.get("financialCurrency"))

        sector   = self._norm_text(raw_info.get("sector"))
        industry = self._norm_text(raw_info.get("industry"))

        ev_revenue = self._ratio(ev_mm, revenue_mm, require_positive_denom=False)
        ev_ebitda  = self._ratio(ev_mm, ebitda_mm, require_positive_denom=True)

        # Currency-coherence gate. Market-based figures (market cap, enterprise
        # value) are denominated in the *trading* currency; statement-based figures
        # (revenue, EBITDA) in the *reporting* currency (`financialCurrency`). For a
        # US-listed ADR that reports in a local currency — e.g. TSMC: USD price vs.
        # TWD statements — dividing one by the other yields a ratio that is wrong by
        # the FX factor (TSM printed EV/EBITDA 3.1x against a true ~14x). yfinance's
        # own enterpriseValue can itself be field-mixed for ADRs, so an FX conversion
        # would substitute a different wrong number that *looks* plausible — worse
        # than a visible gap. The institutionally-correct response is to refuse to
        # certify the cross-currency ratio: mark it N/M with a structured reason and
        # let the memo writer source the comp externally (peer-comp rigor rule).
        flags: List[str] = []
        if currency and financial_currency and currency != financial_currency:
            flags.append(f"currency_mismatch:{financial_currency}!={currency}")
            ev_revenue = NM
            ev_ebitda  = NM

        return CompanyFinancials(
            ticker=ticker,
            name=name,
            market_cap_mm=market_cap_mm,
            enterprise_value_mm=ev_mm,
            trailing_revenue_mm=revenue_mm,
            trailing_ebitda_mm=ebitda_mm,
            forward_pe=forward_pe,
            yoy_revenue_growth_pct=yoy_growth_pct,
            ev_revenue=ev_revenue,
            ev_ebitda=ev_ebitda,
            currency=currency,
            financial_currency=financial_currency,
            quality_flags=flags,
            sector=sector,
            industry=industry,
        )

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _norm_text(value: Optional[object]) -> Optional[str]:
        """Normalise a free-text classification field to a trimmed string, or None."""
        if not value:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _norm_ccy(value: Optional[object]) -> Optional[str]:
        """Normalise a currency code to an upper-case string, or None if absent."""
        if not value:
            return None
        code = str(value).strip().upper()
        return code or None

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
# Cross-sectional data-quality auditor (pure, sector-agnostic)
# ──────────────────────────────────────────────────────────────────────────────

# Universal sanity bounds. A going-concern equity outside these is almost always a
# parse/units error, not a real multiple — independent of sector. These catch gross
# anomalies that survive into a same-currency cohort.
_RATIO_BOUNDS: Dict[str, Tuple[float, float]] = {
    "ev_revenue": (0.05, 100.0),
    "ev_ebitda":  (0.50, 400.0),
    "forward_pe": (0.50, 500.0),
}

# A finite ratio this many times above/below the cohort median is treated as a
# cross-sectional outlier and flagged for analyst verification. Set wide enough that
# genuinely-extreme-but-real multiples (a cyclical's depressed-EBITDA 100x EV/EBITDA)
# are not falsely condemned, but a ~5x currency/parse artifact is.
_OUTLIER_FACTOR: float = 4.0
_MIN_COHORT_FOR_MEDIAN: int = 3


def _finite(value: Union[float, str, None]) -> Optional[float]:
    """Return the value if it is a usable positive number, else None (NM/None/≤0)."""
    if isinstance(value, bool):           # guard: bool is a subclass of int
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def _add_flag(company: "CompanyFinancials", flag: str) -> None:
    if flag not in company.quality_flags:
        company.quality_flags.append(flag)


def audit_peer_set(companies: List["CompanyFinancials"]) -> Dict[str, List[str]]:
    """
    Plausibility-audit a target+peers cohort and annotate each company in place.

    Two sector-agnostic checks per ratio (EV/Revenue, EV/EBITDA, forward P/E):
      1. Absolute bounds — values outside `_RATIO_BOUNDS` are structurally
         implausible for any equity → `implausible:<field>=…`.
      2. Cross-sectional outlier — values more than `_OUTLIER_FACTOR`× away from the
         cohort median → `peer_outlier:<field>=…`.

    Relies only on the dispersion of the cohort and universal sanity bounds, so it
    catches misparsed or mis-currencied figures in *any* sector with no per-sector
    config. It is the safety net behind the per-company currency-coherence gate:
    a cross-currency ratio is already N/M'd (and excluded from the median) by the
    transformer, while a same-currency parse error is caught here.

    Returns a {ticker: [flags]} summary for the data-quality payload node.
    """
    for field_name, (lo, hi) in _RATIO_BOUNDS.items():
        pairs = [(c, _finite(getattr(c, field_name))) for c in companies]
        finite_vals = [v for _, v in pairs if v is not None]
        median = (
            statistics.median(finite_vals)
            if len(finite_vals) >= _MIN_COHORT_FOR_MEDIAN
            else None
        )
        for company, value in pairs:
            if value is None:
                continue
            if value < lo or value > hi:
                _add_flag(company, f"implausible:{field_name}={value} (sane range {lo}-{hi})")
            elif median and median > 0:
                deviation = value / median
                if deviation > _OUTLIER_FACTOR or deviation < 1.0 / _OUTLIER_FACTOR:
                    _add_flag(
                        company,
                        f"peer_outlier:{field_name}={value} (cohort median ~{round(median, 1)})",
                    )

    return {c.ticker: list(c.quality_flags) for c in companies if c.quality_flags}


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

    def get_price_history(self, ticker: str, period: str = "1y") -> List[PricePoint]:
        """Fetch the daily adjusted-close series for *ticker* over *period*."""
        return self._fetcher.fetch_price_history(ticker, period=period)

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
