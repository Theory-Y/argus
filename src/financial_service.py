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
from datetime import date, timedelta
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


@dataclass
class InsiderTransaction:
    """One normalized insider transaction (SEC Form 4 via yfinance)."""

    insider: str                            # Filer name
    position: str                           # e.g. "Chief Executive Officer", "Director"
    kind: str                               # 'sell' | 'buy' | 'other' (awards, conversions, gifts)
    shares: Optional[float]                 # Shares in the transaction
    value_usd: Optional[float]              # Transaction value in plain USD (0/None when unpriced)
    date: Optional[str]                     # ISO date, "YYYY-MM-DD"
    text: str                               # yfinance's transaction description
    url: str                                # Link to the underlying filing when provided


@dataclass
class InsiderActivitySignal:
    """
    Aggregated insider buy/sell read over a trailing window.

    LIMITATION (by design, surfaced to the memo writer): free Form 4 data does not
    expose 10b5-1 scheduled-plan footnotes, so 'scheduled vs unscheduled' cannot be
    distinguished mechanically. The signal carries clustering/size facts; the
    interpretation rule lives in the memo spec (clustered, large, officer-level
    sells near events are the signal — a lone planned sale is not).
    """

    ticker: str
    window_months: int = 12
    sell_count: int = 0
    buy_count: int = 0
    total_sell_value_usd: Optional[float] = None
    total_buy_value_usd: Optional[float] = None
    notable_sells: List[InsiderTransaction] = field(default_factory=list)  # top by value
    note: str = ""
    error: Optional[str] = None


@dataclass
class EarningsSurprise:
    """One reported quarter: consensus EPS vs reported."""

    period: str                             # ISO date of the earnings event
    eps_estimate: Optional[float]
    eps_reported: Optional[float]
    surprise_pct: Optional[float]           # (reported - estimate) / |estimate| * 100


@dataclass
class EarningsTrack:
    """
    Beat/miss pattern over the last `max_quarters` REPORTED earnings (newest first).
    Serves as the deterministic proxy for guidance credibility: persistent or
    recent consecutive misses are the machine-readable trace a guidance cut leaves.
    """

    ticker: str
    quarters: List[EarningsSurprise] = field(default_factory=list)  # newest first, ≤8
    beat_count: int = 0
    miss_count: int = 0
    inline_count: int = 0
    consecutive_misses: int = 0             # counting back from the most recent report
    avg_surprise_pct: Optional[float] = None
    note: str = ""
    error: Optional[str] = None


@dataclass
class AnnualFinancials:
    """One fiscal year of history (statement figures in $MM; ratios approximate)."""

    fiscal_year: str                        # e.g. "FY2025"
    fy_end: str                             # ISO date of the fiscal-year end
    revenue_mm: Optional[float]
    ebitda_mm: Optional[float]
    net_income_mm: Optional[float]
    yoy_revenue_growth_pct: Optional[float]
    ev_mm_approx: Optional[float]           # year-end close × shares + debt − cash
    ev_revenue_approx: Union[float, str, None]
    pe_trailing_approx: Union[float, str, None]  # year-end mktcap / FY net income


@dataclass
class FundamentalsHistory:
    """
    Multi-year (≤5 FY) fundamentals trajectory, oldest → newest.

    `approximate` is always True for the valuation ratios: EV is reconstructed from
    the FY-end close, balance-sheet share count, total debt and cash, and the P/E is
    TRAILING (historical *forward* P/E needs a consensus-estimates archive, which no
    free source provides — substitute documented in the memo spec & roadmap).
    """

    ticker: str
    years: List[AnnualFinancials] = field(default_factory=list)
    approximate: bool = True
    method_note: str = (
        "EV/Revenue and P/E are reconstructed per FY-end (close x shares + debt - cash); "
        "P/E is trailing, not forward."
    )
    error: Optional[str] = None


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

    def fetch_insider_transactions(self, ticker: str) -> List[Dict]:
        """
        Return normalized insider-transaction records (plain dicts, newest first).
        Keys: insider, position, text, shares, value, date (ISO), url.
        Returns [] on any error — callers never receive an exception.
        """
        try:
            df = yf.Ticker(ticker).insider_transactions
            if df is None or df.empty:
                return []
            records: List[Dict] = []
            for _, row in df.iterrows():
                start = row.get("Start Date")
                records.append({
                    "insider":  str(row.get("Insider") or "").strip(),
                    "position": str(row.get("Position") or "").strip(),
                    "text":     str(row.get("Text") or "").strip(),
                    "shares":   row.get("Shares"),
                    "value":    row.get("Value"),
                    "date":     start.strftime("%Y-%m-%d") if pd.notna(start) else None,
                    "url":      str(row.get("URL") or "").strip(),
                })
            return records
        except Exception as exc:                                # pragma: no cover
            logger.error("yfinance insider transactions failed for %s: %s", ticker, exc)
            return []

    def fetch_earnings_history(self, ticker: str, limit: int = 16) -> List[Dict]:
        """
        Return past+scheduled earnings rows as plain dicts (newest first).
        Keys: period (ISO date), eps_estimate, eps_reported, surprise_pct.
        Future rows carry eps_reported=None; the transformer filters to reported.
        Returns [] on any error.
        """
        try:
            df = yf.Ticker(ticker).get_earnings_dates(limit=limit)
            if df is None or df.empty:
                return []
            records: List[Dict] = []
            for idx, row in df.iterrows():
                def _f(v):
                    return float(v) if pd.notna(v) else None
                records.append({
                    "period":       idx.strftime("%Y-%m-%d"),
                    "eps_estimate": _f(row.get("EPS Estimate")),
                    "eps_reported": _f(row.get("Reported EPS")),
                    "surprise_pct": _f(row.get("Surprise(%)")),
                })
            records.sort(key=lambda r: r["period"], reverse=True)
            return records
        except Exception as exc:                                # pragma: no cover
            logger.error("yfinance earnings history failed for %s: %s", ticker, exc)
            return []

    def fetch_annual_statements(self, ticker: str) -> Dict[str, Dict]:
        """
        Return per-fiscal-year statement figures keyed by FY-end ISO date:
        {fy_end: {revenue, ebitda, net_income, total_debt, cash, shares}} — raw USD.
        Missing line items are None. Returns {} on any error.
        """
        try:
            t = yf.Ticker(ticker)
            inc = t.income_stmt
            bs  = t.balance_sheet
        except Exception as exc:                                # pragma: no cover
            logger.error("yfinance annual statements failed for %s: %s", ticker, exc)
            return {}

        def _cell(df, row_names, col):
            if df is None or df.empty or col not in df.columns:
                return None
            for name in row_names:
                if name in df.index:
                    v = df.at[name, col]
                    if pd.notna(v):
                        return float(v)
            return None

        out: Dict[str, Dict] = {}
        if inc is None or inc.empty:
            return out
        for col in inc.columns:
            fy_end = col.strftime("%Y-%m-%d")
            out[fy_end] = {
                "revenue":    _cell(inc, ["Total Revenue"], col),
                "ebitda":     _cell(inc, ["EBITDA", "Normalized EBITDA"], col),
                "net_income": _cell(inc, ["Net Income"], col),
                "total_debt": _cell(bs, ["Total Debt"], col),
                "cash":       _cell(bs, ["Cash And Cash Equivalents",
                                         "Cash Cash Equivalents And Short Term Investments"], col),
                "shares":     _cell(bs, ["Ordinary Shares Number", "Share Issued"], col),
            }
        return out


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
# Pure builders — insider activity, earnings track, fundamentals history
# (no I/O; unit-testable on plain records)
# ──────────────────────────────────────────────────────────────────────────────

_NOTABLE_SELLS_MAX: int = 5
_HISTORY_MAX_YEARS: int = 5


def _classify_insider_kind(text: str) -> str:
    """Map yfinance's free-text transaction description → 'sell' | 'buy' | 'other'."""
    t = (text or "").lower()
    if "sale" in t or "sold" in t:
        return "sell"
    if "purchase" in t or "buy" in t or "bought" in t:
        return "buy"
    return "other"   # awards/grants, conversions, gifts, option exercises


def build_insider_activity(
    ticker: str,
    records: List[Dict],
    window_months: int = 12,
    today: Optional[date] = None,
) -> InsiderActivitySignal:
    """Aggregate normalized insider records into the memo-facing signal."""
    if not records:
        return InsiderActivitySignal(
            ticker=ticker, window_months=window_months,
            note="No insider transactions reported by the data source.",
            error="no_data",
        )
    cutoff = ((today or date.today()) - timedelta(days=round(window_months * 30.44)))
    cutoff_iso = cutoff.isoformat()

    sells: List[InsiderTransaction] = []
    buys = 0
    sell_value = 0.0
    buy_value = 0.0
    for r in records:
        d = r.get("date")
        if not d or d < cutoff_iso:
            continue
        kind = _classify_insider_kind(r.get("text", ""))
        if kind == "other":
            continue
        value = r.get("value")
        try:
            value = float(value) if value is not None else None
        except (TypeError, ValueError):
            value = None
        if kind == "buy":
            buys += 1
            buy_value += value or 0.0
            continue
        shares = r.get("shares")
        try:
            shares = float(shares) if shares is not None else None
        except (TypeError, ValueError):
            shares = None
        sells.append(InsiderTransaction(
            insider=r.get("insider", ""), position=r.get("position", ""),
            kind="sell", shares=shares, value_usd=value, date=d,
            text=r.get("text", ""), url=r.get("url", ""),
        ))
        sell_value += value or 0.0

    notable = sorted(sells, key=lambda s: s.value_usd or 0.0, reverse=True)[:_NOTABLE_SELLS_MAX]
    return InsiderActivitySignal(
        ticker=ticker,
        window_months=window_months,
        sell_count=len(sells),
        buy_count=buys,
        total_sell_value_usd=round(sell_value, 2) if sells else None,
        total_buy_value_usd=round(buy_value, 2) if buys else None,
        notable_sells=notable,
        note=(
            "Form 4 data does not expose 10b5-1 scheduled-plan footnotes; weigh "
            "clustering, size vs. role, and proximity to events rather than treating "
            "any single sale as a conviction signal."
        ),
    )


def build_earnings_track(
    ticker: str, records: List[Dict], max_quarters: int = 8
) -> EarningsTrack:
    """Distill reported earnings rows into the beat/miss guidance-credibility proxy."""
    reported = [r for r in records if r.get("eps_reported") is not None]
    reported.sort(key=lambda r: r["period"], reverse=True)
    reported = reported[:max_quarters]
    if not reported:
        return EarningsTrack(
            ticker=ticker,
            note="No reported earnings history available from the data source.",
            error="no_data",
        )

    quarters = [
        EarningsSurprise(
            period=r["period"],
            eps_estimate=r.get("eps_estimate"),
            eps_reported=r.get("eps_reported"),
            surprise_pct=r.get("surprise_pct"),
        )
        for r in reported
    ]
    beats = sum(1 for q in quarters if (q.surprise_pct or 0) > 0)
    misses = sum(1 for q in quarters if q.surprise_pct is not None and q.surprise_pct < 0)
    inline = len(quarters) - beats - misses
    streak = 0
    for q in quarters:                       # newest first
        if q.surprise_pct is not None and q.surprise_pct < 0:
            streak += 1
        else:
            break
    surprises = [q.surprise_pct for q in quarters if q.surprise_pct is not None]
    return EarningsTrack(
        ticker=ticker,
        quarters=quarters,
        beat_count=beats,
        miss_count=misses,
        inline_count=inline,
        consecutive_misses=streak,
        avg_surprise_pct=round(statistics.mean(surprises), 2) if surprises else None,
        note=(
            "EPS estimate-vs-reported pattern is the deterministic proxy for guidance "
            "credibility; cross-check 8-K 2.02 events for explicit guidance language."
        ),
    )


def build_fundamentals_history(
    ticker: str,
    statements: Dict[str, Dict],
    price_history: List["PricePoint"],
) -> FundamentalsHistory:
    """
    Assemble the ≤5-FY trajectory (oldest → newest) with approximate year-end
    valuation ratios. Statement inputs are raw USD; output figures are $MM.
    """
    if not statements:
        return FundamentalsHistory(ticker=ticker, error="no_data")

    closes = sorted(
        ((p.date if not isinstance(p, dict) else p.get("date"),
          p.close if not isinstance(p, dict) else p.get("close"))
         for p in (price_history or [])),
        key=lambda x: x[0] or "",
    )

    def _close_on_or_before(fy_end: str) -> Optional[float]:
        best = None
        for d, c in closes:
            if d and c is not None and d <= fy_end:
                best = c
            elif d and d > fy_end:
                break
        return best

    def _mm(v: Optional[float]) -> Optional[float]:
        return round(v / _MILLION, 2) if v is not None else None

    years: List[AnnualFinancials] = []
    prev_revenue: Optional[float] = None
    for fy_end in sorted(statements.keys())[-_HISTORY_MAX_YEARS:]:
        s = statements[fy_end]
        revenue, ebitda  = s.get("revenue"), s.get("ebitda")
        net_income       = s.get("net_income")
        shares, debt, cash = s.get("shares"), s.get("total_debt"), s.get("cash")
        if revenue is None and ebitda is None and net_income is None:
            continue   # an all-empty statement year carries no signal

        growth = None
        if revenue is not None and prev_revenue:
            growth = round((revenue - prev_revenue) / abs(prev_revenue) * 100, 2)
        if revenue is not None:
            prev_revenue = revenue

        close = _close_on_or_before(fy_end)
        ev = ev_revenue = pe = None
        if close is not None and shares:
            mktcap = close * shares
            ev = mktcap + (debt or 0.0) - (cash or 0.0)
            if revenue and revenue > 0:
                ev_revenue = round(ev / revenue, 2)
            if net_income and net_income > 0:
                pe = round(mktcap / net_income, 2)

        years.append(AnnualFinancials(
            fiscal_year=f"FY{fy_end[:4]}",
            fy_end=fy_end,
            revenue_mm=_mm(revenue),
            ebitda_mm=_mm(ebitda),
            net_income_mm=_mm(net_income),
            yoy_revenue_growth_pct=growth,
            ev_mm_approx=_mm(ev),
            ev_revenue_approx=ev_revenue if ev_revenue is not None else NM,
            pe_trailing_approx=pe if pe is not None else NM,
        ))

    return FundamentalsHistory(ticker=ticker, years=years)


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

    def get_insider_activity(
        self, ticker: str, window_months: int = 12
    ) -> InsiderActivitySignal:
        """Fetch and aggregate the trailing insider buy/sell signal."""
        records = self._fetcher.fetch_insider_transactions(ticker)
        return build_insider_activity(ticker, records, window_months=window_months)

    def get_earnings_track(self, ticker: str, max_quarters: int = 8) -> EarningsTrack:
        """Fetch the last *max_quarters* reported earnings and the beat/miss pattern."""
        records = self._fetcher.fetch_earnings_history(ticker, limit=max_quarters + 8)
        return build_earnings_track(ticker, records, max_quarters=max_quarters)

    def get_fundamentals_history(self, ticker: str) -> FundamentalsHistory:
        """Fetch ≤5 fiscal years of fundamentals with approximate year-end ratios."""
        statements = self._fetcher.fetch_annual_statements(ticker)
        prices = (
            self._fetcher.fetch_price_history(ticker, period="5y") if statements else []
        )
        return build_fundamentals_history(ticker, statements, prices)

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
