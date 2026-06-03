"""
alt_data_service.py — Macro & Alternative Signal Engine
=========================================================
Sources:
  1. Google Trends (pytrends)  — search-interest velocity as demand proxy
  2. FRED API (requests)       — commercial construction macro indicator
  3. SEC EDGAR API (requests)  — most-recent 10-K + Item 1A risk snippet
  4. Apify REST API (requests) — job-listing scraper (live when APIFY_API_KEY set)
  5. Consumer sentiment        — blended across four key-free public sources,
       uniformly for any ticker (MultiSourceSentimentAggregator):
         • Stocktwits      — per-ticker investors, native Bull/Bear labels (primary)
         • Yahoo Finance   — RSS news headlines; factual demand/earnings signal
         • HackerNews      — tech / B2B discussion via the Algolia search API
         • Reddit          — investing subreddits, public JSON (fallback only)
  6. Massive / Polygon API (requests, MASSIVE_API_KEY) — two signals:
         • MassiveNewsFetcher      — recent news with machine-written per-ticker
                                     sentiment labels and reasoning text (replaces
                                     raw RSS lexicon scoring as the primary news signal)
         • MassivePriceFetcher     — 365 days of OHLCV bars for 52-week high/low,
                                     1-year return, and 30-day momentum

Architecture (Clean Architecture + SOLID):
  Each data source has a dedicated Fetcher (I/O) and Processor (pure logic).
  AltDataService is the façade that wires them together.
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
import defusedxml.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from pytrends.request import TrendReq
import pandas as pd

from pathlib import Path
from dotenv import load_dotenv

# Load credentials from the project-root .env before reading any env vars below.
# This is the canonical load point: every key (FRED_API_KEY, SEC_USER_AGENT,
# APIFY_API_KEY, …) is consumed from this module, so any importer is covered.
# Real environment variables take precedence (override=False); a missing .env is a no-op.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration — inject credentials via environment variables
# ──────────────────────────────────────────────────────────────────────────────

# FRED API key — free registration at https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "YOUR_FRED_API_KEY_HERE")
FRED_BASE_URL: str = "https://api.stlouisfed.org/fred/series/observations"

# Massive / Polygon API key — set MASSIVE_API_KEY in .env to activate price metrics
# and structured-news signals. Without it both nodes are marked unavailable.
MASSIVE_API_KEY: str = os.getenv("MASSIVE_API_KEY", "")
_MASSIVE_BASE_URL: str = "https://api.polygon.io"

# SEC EDGAR requires a descriptive User-Agent (app name + contact email).
# See SEC Fair Access policy: https://www.sec.gov/developer
SEC_USER_AGENT: str = os.getenv(
    "SEC_USER_AGENT",
    "TheoryY-ResearchAgent/1.0 contact@theoryy.com",   # ← replace with real email
)
SEC_TICKERS_URL: str = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL: str = "https://data.sec.gov/submissions/CIK{cik}.json"

# HTTP timeouts (seconds)
_HTTP_TIMEOUT: int = 15
_SEC_TIMEOUT:  int = 25   # 10-K documents can be large

# Polite delay between SEC requests to stay within EDGAR rate limits (10 req/s max)
_SEC_DELAY: float = 0.15

# Number of characters to extract from Item 1A for the LLM snippet
_RISK_SNIPPET_CHARS: int = 800


# ──────────────────────────────────────────────────────────────────────────────
# Ticker → primary search keyword map (demand proxy for Google Trends)
# ──────────────────────────────────────────────────────────────────────────────

# Human-readable labels for SEC 8-K item numbers
_8K_ITEM_LABELS: Dict[str, str] = {
    "1.01": "Entry into Material Agreement",
    "1.02": "Termination of Material Agreement",
    "1.03": "Bankruptcy/Receivership",
    "2.01": "Completion of Acquisition/Disposition",
    "2.02": "Results of Operations",
    "2.03": "Creation of Direct Financial Obligation",
    "2.05": "Exit or Disposal Cost Obligations",
    "2.06": "Material Impairment",
    "3.01": "Notice of Delisting",
    "3.02": "Unregistered Sales of Equity Securities",
    "4.01": "Changes in Certifying Accountant",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Directors/Officers Departure/Appointment",
    "5.03": "Amendments to Articles/Certificate",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

TICKER_KEYWORDS: Dict[str, str] = {
    "CSGP": "CoStar commercial real estate",
    "CBRE": "CBRE commercial property",
    "CARR": "Carrier HVAC",
    "TT":   "Trane HVAC",
    "JCI":  "Johnson Controls building management",
    "LII":  "Lennox HVAC",
    "ABM":  "ABM facility services",
    "CTAS": "Cintas uniform services",
    "ADT":  "ADT security system",
    "ALLE": "Allegion door security",
    "HON":  "Honeywell building automation",
    "PCOR": "Procore construction software",
    "APPF": "AppFolio property management",
    "Z":    "Zillow home search",
}

# Corporate-form suffixes stripped from a company name before using it as a search
# keyword, so "Procore Technologies Inc" → "Procore Technologies".
_CORP_SUFFIXES = re.compile(
    r"[,\.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|"
    r"llc|lp|holdings|group|sa|nv|ag|se|class\s+[a-c])\b\.?",
    re.IGNORECASE,
)


def _trends_keyword(ticker: str, company_name: Optional[str] = None) -> str:
    """
    Pick the Google-Trends search keyword for *ticker*.

    Curated keywords win (they encode the most search-relevant product/brand for
    the original universe). Otherwise fall back to the cleaned company name —
    which generalises to every sector — and finally to the bare ticker.
    """
    curated = TICKER_KEYWORDS.get(ticker.upper())
    if curated:
        return curated
    if company_name:
        cleaned = _CORP_SUFFIXES.sub("", company_name).strip()
        if cleaned:
            return cleaned
    return ticker


# ──────────────────────────────────────────────────────────────────────────────
# Domain Models
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TrendsSignal:
    """12-month Google Trends summary for one ticker's primary keyword."""
    ticker:           str
    keyword:          str
    velocity_pct:     Optional[float]  # % Δ: last-4-obs avg vs first-4-obs avg
    peak_interest:    Optional[int]    # 0–100 normalised scale
    trough_interest:  Optional[int]
    latest_interest:  Optional[int]


@dataclass
class FredSeries:
    """Summary of a single FRED time series."""
    series_id:       str
    title:           str
    latest_value:    Optional[float]
    latest_date:     Optional[str]
    yoy_change_pct:  Optional[float]   # Δ vs observation 12 periods prior


@dataclass
class SecRiskSnippet:
    """Most-recent 10-K metadata + leading excerpt from Item 1A Risk Factors."""
    ticker:                str
    cik:                   Optional[str]
    filing_url:            Optional[str]
    risk_factors_snippet:  Optional[str]


@dataclass
class ApifyJobsResult:
    """Job-listing scrape result (stub until Apify actor is configured)."""
    company_name:     str
    total_open_roles: int
    engineering_roles: List[Dict] = field(default_factory=list)
    is_stub:          bool = True


@dataclass
class Sec8KEvent:
    """Single 8-K filing — metadata only, no document download."""
    filing_date:   str
    items_raw:     Optional[str]        # e.g. "1.01,9.01"
    items_labeled: Optional[List[str]]  # human-readable labels per item
    url:           Optional[str]


@dataclass
class Sec8KSignal:
    """Collection of recent 8-K filings for one ticker."""
    ticker: str
    cik:    Optional[str]
    events: List[Sec8KEvent] = field(default_factory=list)


@dataclass
class PressRelease:
    """Single press release headline from GlobeNewswire RSS."""
    title: str
    date:  Optional[str]
    url:   Optional[str]


@dataclass
class PressReleaseSignal:
    """Recent press releases for one ticker."""
    ticker:   str
    source:   str
    releases: List[PressRelease] = field(default_factory=list)
    error:    Optional[str] = None


@dataclass
class LitigationCase:
    """Single securities class-action case from Stanford SCAC."""
    case_name:  str
    filed_date: Optional[str]
    status:     Optional[str]


@dataclass
class LitigationSignal:
    """Active or recent class-action cases for one company."""
    company_name: str
    source:       str
    cases:        List[LitigationCase] = field(default_factory=list)
    error:        Optional[str] = None


@dataclass
class SourceSentiment:
    """Per-source contribution to the blended consumer-sentiment signal."""
    source:          str              # "stocktwits", "hackernews", "reddit"
    available:       bool             # True if the source returned any messages
    message_count:   int              # messages/posts that fed the score
    sentiment_score: Optional[float]  # -1.0 … 1.0 for this source alone (smoothed)
    weight:          float            # contribution weight in the blend (0 if unused)
    error:           Optional[str] = None
    signal_count:    int   = 0        # matched sentiment words (drives weight + confidence)
    confidence:      str   = "low"    # "low" | "medium" | "high" — from signal_count


@dataclass
class ConsumerSentimentSignal:
    """
    Consumer & investor sentiment blended across multiple public sources.

    Computed uniformly for *any* ticker (no per-sector configuration) by
    MultiSourceSentimentAggregator. `sources` carries the per-source breakdown
    so the LLM can judge data quality; the top-level score is the weighted blend.
    """
    ticker:          str
    company_name:    str
    post_count:      int               # total messages across all sources
    sentiment:       Optional[str]      # "positive", "mixed", "negative", or None
    sentiment_score: Optional[float]    # -1.0 (very negative) to 1.0 (very positive)
    top_themes:      List[str]          # recurring topics across all sources
    source:          str               # "multi_source" (or single source if only one)
    subreddits:      List[str]          # Reddit subreddits that were searched
    sources:         List[SourceSentiment] = field(default_factory=list)
    top_quotes:      List[Dict[str, str]] = field(default_factory=list)  # [{"source": ..., "text": ...}]
    error:           Optional[str] = None
    # Overall confidence in the blended score, from the total matched signal and the
    # number of sources that actually contributed. The blend can be "positive" yet
    # "low" confidence — the writer must hedge accordingly rather than assert it.
    confidence:      Optional[str] = None  # "low" | "medium" | "high" | None


# ──────────────────────────────────────────────────────────────────────────────
# Google Trends — Fetcher (I/O) + Processor (pure logic)
# ──────────────────────────────────────────────────────────────────────────────

class GoogleTrendsFetcher:
    """
    Infrastructure: wraps pytrends TrendReq.
    Single responsibility: issue the HTTP request; return raw DataFrame.
    """

    def __init__(self, hl: str = "en-US", tz: int = 300) -> None:
        # tz=300 → US Eastern; adjust for your target market
        self._pytrends = TrendReq(hl=hl, tz=tz, timeout=(10, 25))

    def fetch_interest_over_time(
        self,
        keyword:   str,
        timeframe: str = "today 12-m",
        geo:       str = "US",
    ) -> pd.DataFrame:
        """
        Fetch weekly interest-over-time for *keyword*.
        Returns an empty DataFrame on any error.
        """
        try:
            self._pytrends.build_payload([keyword], timeframe=timeframe, geo=geo)
            df = self._pytrends.interest_over_time()
            if df.empty:
                logger.warning("Trends: no data returned for '%s'", keyword)
            return df
        except Exception as exc:
            logger.error("Trends fetch failed for '%s': %s", keyword, exc)
            return pd.DataFrame()


class GoogleTrendsProcessor:
    """
    Domain: derives velocity and summary statistics from raw Trends data.
    Single responsibility: signal computation; no I/O.
    """

    def compute_signal(
        self, ticker: str, keyword: str, df: pd.DataFrame
    ) -> TrendsSignal:
        if df.empty or keyword not in df.columns:
            return TrendsSignal(
                ticker=ticker, keyword=keyword,
                velocity_pct=None, peak_interest=None,
                trough_interest=None, latest_interest=None,
            )

        series = df[keyword].dropna()
        return TrendsSignal(
            ticker=ticker,
            keyword=keyword,
            velocity_pct=self._velocity(series),
            peak_interest=int(series.max()),
            trough_interest=int(series.min()),
            latest_interest=int(series.iloc[-1]),
        )

    @staticmethod
    def _velocity(series: pd.Series) -> Optional[float]:
        """
        Compare the mean of the last 4 observations to the first 4.
        Returns percent change, or None if insufficient data.
        """
        if len(series) < 8:
            return None
        baseline = series.iloc[:4].mean()
        recent   = series.iloc[-4:].mean()
        if baseline == 0:
            return None
        return round((recent - baseline) / baseline * 100, 2)


# ──────────────────────────────────────────────────────────────────────────────
# FRED API — Fetcher (I/O) + Processor (pure logic)
# ──────────────────────────────────────────────────────────────────────────────

class FredApiFetcher:
    """
    Infrastructure: queries the FRED REST API.
    API key is read from the FRED_API_KEY environment variable.
    Register for a free key at: https://fred.stlouisfed.org/docs/api/api_key.html
    """

    def __init__(self, api_key: str = FRED_API_KEY) -> None:
        if api_key == "YOUR_FRED_API_KEY_HERE":
            logger.warning("FRED API key is not set — set env var FRED_API_KEY")
        self._api_key = api_key
        self._session = requests.Session()

    def fetch_series(
        self,
        series_id:   str,
        sort_order:  str = "desc",
        limit:       int = 24,      # 24 months → sufficient for 12-month YoY delta
    ) -> List[Dict]:
        """
        Return a list of {date, value} observation dicts, newest first.
        Values of "." (FRED missing-data sentinel) are included; filter downstream.
        """
        params = {
            "series_id":   series_id,
            "api_key":     self._api_key,
            "file_type":   "json",
            "sort_order":  sort_order,
            "limit":       limit,
        }
        try:
            resp = self._session.get(FRED_BASE_URL, params=params, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            return resp.json().get("observations", [])
        except requests.RequestException as exc:
            logger.error("FRED fetch failed for series '%s': %s", series_id, exc)
            return []


class FredDataProcessor:
    """
    Domain: summarises raw FRED observations into a FredSeries dataclass.
    Single responsibility: aggregation maths; no I/O.
    """

    def process(self, series_id: str, observations: List[Dict]) -> FredSeries:
        # Filter out FRED's "." missing-value sentinel
        valid = [
            o for o in observations
            if o.get("value") not in (".", "", None)
        ]
        if not valid:
            return FredSeries(
                series_id=series_id, title=series_id,
                latest_value=None, latest_date=None, yoy_change_pct=None,
            )

        latest_val  = float(valid[0]["value"])
        latest_date = valid[0]["date"]

        # YoY assumes monthly frequency; index 12 = same month last year
        yoy_change: Optional[float] = None
        if len(valid) >= 13:
            prior_val = float(valid[12]["value"])
            if prior_val != 0:
                yoy_change = round((latest_val - prior_val) / prior_val * 100, 2)

        return FredSeries(
            series_id=series_id,
            title=series_id,            # Caller can override .title with a label
            latest_value=round(latest_val, 2),
            latest_date=latest_date,
            yoy_change_pct=yoy_change,
        )


# ──────────────────────────────────────────────────────────────────────────────
# SEC EDGAR — CIK Resolver, Filing Fetcher, Risk Factor Extractor
# ──────────────────────────────────────────────────────────────────────────────

class SecCikResolver:
    """
    Infrastructure: resolves a ticker symbol → zero-padded 10-digit CIK.
    Uses EDGAR's canonical company_tickers.json master file.
    Results are in-memory cached to avoid redundant HTTP calls.
    """

    def __init__(self) -> None:
        self._cache:   Dict[str, str]  = {}
        self._session: requests.Session = requests.Session()
        self._session.headers.update({"User-Agent": SEC_USER_AGENT})

    def resolve(self, ticker: str) -> Optional[str]:
        ticker_up = ticker.upper()
        if ticker_up in self._cache:
            return self._cache[ticker_up]
        try:
            resp = self._session.get(SEC_TICKERS_URL, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            # Populate cache for all entries in one shot
            for entry in resp.json().values():
                t = str(entry.get("ticker", "")).upper()
                if t:
                    self._cache[t] = str(entry["cik_str"]).zfill(10)
            return self._cache.get(ticker_up)
        except requests.RequestException as exc:
            logger.error("CIK resolution failed for %s: %s", ticker, exc)
            return None


class SecFilingFetcher:
    """
    Infrastructure: retrieves the URL of the primary document in the most recent 10-K.
    Uses EDGAR submissions API: https://data.sec.gov/submissions/CIK{cik}.json
    """

    def __init__(self) -> None:
        self._session: requests.Session = requests.Session()
        self._session.headers.update({"User-Agent": SEC_USER_AGENT})

    def get_latest_10k_url(self, cik: str) -> Optional[str]:
        """
        Returns the direct HTTPS URL of the most recent 10-K primary document,
        or None if no 10-K is found in the submissions index.
        """
        url = SEC_SUBMISSIONS_URL.format(cik=cik)
        try:
            resp = self._session.get(url, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            filings = resp.json().get("filings", {}).get("recent", {})

            forms      = filings.get("form", [])
            accessions = filings.get("accessionNumber", [])
            docs       = filings.get("primaryDocument", [])

            for form, accession, doc in zip(forms, accessions, docs):
                if form == "10-K":
                    clean_cik = cik.lstrip("0")          # EDGAR archive path uses unpadded CIK
                    acc_nodash = accession.replace("-", "")
                    return (
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{clean_cik}/{acc_nodash}/{doc}"
                    )
            logger.warning("No 10-K found in EDGAR submissions for CIK %s", cik)
            return None
        except requests.RequestException as exc:
            logger.error("EDGAR submissions fetch failed (CIK=%s): %s", cik, exc)
            return None


class SecRiskFactorExtractor:
    """
    Infrastructure + Domain: downloads a 10-K document and extracts the
    opening passage of Item 1A (Risk Factors) via regex + BeautifulSoup.

    Handles both HTML (.htm) and plain-text (.txt) filing formats.
    """

    _ITEM_1A_RE = re.compile(
        r"item\s+1a[\.\:—\s]+risk\s+factors",
        re.IGNORECASE,
    )
    # Lookahead anchor: stop snippet at the next "Item" heading
    _ITEM_NEXT_RE = re.compile(r"item\s+\d", re.IGNORECASE)

    def __init__(self) -> None:
        self._session: requests.Session = requests.Session()
        self._session.headers.update({"User-Agent": SEC_USER_AGENT})

    def extract(self, filing_url: str) -> Optional[str]:
        try:
            time.sleep(_SEC_DELAY)
            resp = self._session.get(filing_url, timeout=_SEC_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("10-K download failed (%s): %s", filing_url, exc)
            return None

        content_type = resp.headers.get("Content-Type", "")
        raw_text = (
            self._html_to_text(resp.text)
            if "html" in content_type or filing_url.lower().endswith((".htm", ".html"))
            else resp.text
        )
        return self._extract_snippet(raw_text)

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _html_to_text(html: str) -> str:
        soup = BeautifulSoup(html, "lxml-xml")
        return soup.get_text(separator=" ", strip=True)

    # Generic boilerplate that opens most 10-K Item 1A sections — zero signal.
    _RISK_BOILERPLATE_RE = re.compile(
        r"Investing in our (common stock|securities|shares) involves (a high degree of )?risk"
        r".{0,400}?(before (deciding|investing|purchasing)|before you (decide|invest|purchase))",
        re.IGNORECASE | re.DOTALL,
    )

    def _extract_snippet(self, text: str) -> Optional[str]:
        # Iterate all matches: the first hit is often a TOC entry ("Item 1A...12"),
        # so skip any match whose extracted body is shorter than 100 chars.
        for match in self._ITEM_1A_RE.finditer(text):
            body = text[match.end(): match.end() + _RISK_SNIPPET_CHARS * 5]
            next_item = self._ITEM_NEXT_RE.search(body)
            if next_item:
                body = body[: next_item.start()]
            body = re.sub(r"\s+", " ", body).strip()
            # Skip generic preamble so the 800-char window lands on actual risks.
            bp = self._RISK_BOILERPLATE_RE.search(body)
            if bp and bp.end() < len(body) - 100:
                body = body[bp.end():].lstrip(". ")
            snippet = body[:_RISK_SNIPPET_CHARS]
            if len(snippet) >= 100:
                return snippet
        logger.debug("Item 1A pattern not found in document")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Apify Stub — activate by injecting APIFY_API_KEY
# ──────────────────────────────────────────────────────────────────────────────

# Corporate-suffix tokens stripped so the same query shape is sent for every
# company regardless of how yfinance spells its long name.
_COMPANY_SUFFIX_RE = re.compile(
    r"[,\.]?\s*\b("
    r"inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|lp|"
    r"holdings|group|sa|nv|ag|the"
    r")\b\.?",
    re.IGNORECASE,
)

# Job titles counted as "engineering" roles — keeps the metric comparable
# across companies that label postings differently.
_ENGINEERING_TITLE_RE = re.compile(
    r"\b(engineer|developer|software|sde|programmer|devops|sre|"
    r"data scientist|machine learning|ml engineer|architect)\b",
    re.IGNORECASE,
)


def normalize_company_name(company_name: str) -> str:
    """Strip corporate suffixes/punctuation so Apify queries are uniform."""
    cleaned = _COMPANY_SUFFIX_RE.sub(" ", company_name or "")
    return re.sub(r"\s+", " ", cleaned).strip() or company_name


class ApifyJobScraper:
    """
    Apify-powered job-listing scraper.

    Runs synchronously and returns a *consistent* result schema for every
    company. Activates automatically when both env vars are present:
      • APIFY_API_KEY  — your Apify API token
      • APIFY_ACTOR_ID — actor to run (e.g. a LinkedIn/Indeed jobs scraper)
    Without them it degrades to a clearly-marked stub (is_stub=True) so the
    pipeline never blocks on a missing key.

    The run-sync-get-dataset-items endpoint blocks until the run finishes and
    returns the dataset in one call, so no manual polling loop is needed.
    Apify REST docs: https://docs.apify.com/api/v2
    """

    _RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    _RUN_TIMEOUT  = 90  # seconds; Apify run-sync caps server-side too

    def __init__(
        self,
        api_key:  Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> None:
        self._api_key  = api_key  or os.getenv("APIFY_API_KEY", "")
        self._actor_id = actor_id or os.getenv("APIFY_ACTOR_ID", "")
        self._session  = requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key) and bool(self._actor_id)

    def get_open_engineering_roles(self, company_name: str) -> ApifyJobsResult:
        """
        Fetch open roles for *company_name* and return a normalized result.
        Returns an is_stub=True result when Apify is not configured or errors,
        so every company yields the same shape regardless of data availability.
        """
        if not self.is_configured:
            logger.info(
                "Apify not configured (set APIFY_API_KEY + APIFY_ACTOR_ID) — "
                "returning stub for '%s'", company_name,
            )
            return self._stub(company_name)

        query = normalize_company_name(company_name)
        url = self._RUN_SYNC_URL.format(actor_id=self._actor_id)
        payload = {
            # Common input keys across job-scraper actors; extra keys are ignored
            # by actors that don't use them, keeping one payload usable broadly.
            "company":  query,
            "keywords": ["engineer", "software", "developer"],
            "maxItems": 100,
        }
        try:
            resp = self._session.post(
                url,
                params={"token": self._api_key},
                json=payload,
                timeout=self._RUN_TIMEOUT,
            )
            resp.raise_for_status()
            items = resp.json()
        except requests.RequestException as exc:
            logger.error("Apify run failed for '%s': %s", company_name, exc)
            return self._stub(company_name)
        except ValueError as exc:
            logger.error("Apify returned non-JSON for '%s': %s", company_name, exc)
            return self._stub(company_name)

        if not isinstance(items, list):
            logger.warning("Apify returned unexpected payload type for '%s'", company_name)
            return self._stub(company_name)

        return self._normalize(company_name, items)

    def _normalize(self, company_name: str, items: List[Dict]) -> ApifyJobsResult:
        """Coerce heterogeneous actor output into the fixed ApifyJobsResult schema."""
        engineering: List[Dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("positionName") or item.get("jobTitle") or "")
            if _ENGINEERING_TITLE_RE.search(title):
                engineering.append({
                    "title":    title,
                    "location": item.get("location") or item.get("jobLocation"),
                    "url":      item.get("url") or item.get("jobUrl") or item.get("link"),
                })
        return ApifyJobsResult(
            company_name=company_name,
            total_open_roles=len(items),
            engineering_roles=engineering,
            is_stub=False,
        )

    @staticmethod
    def _stub(company_name: str) -> ApifyJobsResult:
        return ApifyJobsResult(
            company_name=company_name,
            total_open_roles=0,
            engineering_roles=[],
            is_stub=True,
        )

    def get_headcount_proxy(self, company_name: str) -> Dict:
        """
        Optional LinkedIn/Glassdoor employee-count proxy via an Apify actor.
        No reliable key-free source exists, so this returns a stub unless a
        dedicated headcount actor is wired in. Kept for API stability.
        """
        logger.info("Headcount proxy called for '%s' (stub)", company_name)
        return {"company": company_name, "employee_estimate": None, "is_stub": True}


# ──────────────────────────────────────────────────────────────────────────────
# SEC EDGAR 8-K Feed — recent material-event filings (metadata only)
# ──────────────────────────────────────────────────────────────────────────────

class Sec8KFetcher:
    """
    Fetches the most recent 8-K filings for a ticker from the EDGAR submissions API.
    Returns structured metadata + item labels; no per-document HTTP download.
    Shares SecCikResolver with the rest of the SEC pipeline to reuse the CIK cache.
    """
    _MAX_EVENTS      = 8
    _LOOKBACK_DAYS   = 365

    def __init__(self, cik_resolver: Optional["SecCikResolver"] = None) -> None:
        self._cik_resolver = cik_resolver or SecCikResolver()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": SEC_USER_AGENT})

    def fetch(self, ticker: str) -> Sec8KSignal:
        cik = self._cik_resolver.resolve(ticker)
        if not cik:
            return Sec8KSignal(ticker=ticker, cik=None, events=[])

        try:
            resp = self._session.get(
                SEC_SUBMISSIONS_URL.format(cik=cik), timeout=_HTTP_TIMEOUT
            )
            resp.raise_for_status()
            recent = resp.json().get("filings", {}).get("recent", {})
        except requests.RequestException as exc:
            logger.error("8-K submissions fetch failed for %s: %s", ticker, exc)
            return Sec8KSignal(ticker=ticker, cik=cik, events=[])

        cutoff    = (datetime.now(timezone.utc) - timedelta(days=self._LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        forms     = recent.get("form", [])
        dates     = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs      = recent.get("primaryDocument", [])
        items_raw = recent.get("items", [None] * len(forms))
        clean_cik = cik.lstrip("0")

        # 8-K = domestic material events; 6-K = foreign private issuer equivalent
        _MATERIAL_FORMS = {"8-K", "8-K/A", "6-K", "6-K/A"}

        events: List[Sec8KEvent] = []
        for form, date, acc, doc, items in zip(forms, dates, accessions, docs, items_raw):
            if form not in _MATERIAL_FORMS:
                continue
            if date < cutoff:
                break  # submissions are newest-first; stop when past the lookback window
            acc_nodash = acc.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{clean_cik}/{acc_nodash}/{doc}"
            )
            labeled = self._label_items(items) if items else None
            events.append(Sec8KEvent(
                filing_date=date,
                items_raw=items or None,
                items_labeled=labeled,
                url=url,
            ))
            if len(events) >= self._MAX_EVENTS:
                break

        return Sec8KSignal(ticker=ticker, cik=cik, events=events)

    @staticmethod
    def _label_items(items_str: str) -> List[str]:
        labels = []
        for item in items_str.split(","):
            item = item.strip()
            label = _8K_ITEM_LABELS.get(item)
            labels.append(f"{item}: {label}" if label else item)
        return labels


# ──────────────────────────────────────────────────────────────────────────────
# GlobeNewswire Press Release Feed (public RSS, no API key)
# ──────────────────────────────────────────────────────────────────────────────

class PressReleaseFetcher:
    """
    Fetches recent 6-K/8-K filings via the EDGAR submissions API.
    Uses the company's own submission history (CIK-scoped) to avoid cross-company
    noise that EFTS phrase queries produce for short tickers like "Z".
    No API key required.
    """
    _MAX_RELEASES  = 5
    _LOOKBACK_DAYS = 365
    _PR_FORMS      = {"6-K", "6-K/A", "8-K", "8-K/A"}

    def __init__(self, cik_resolver: Optional["SecCikResolver"] = None) -> None:
        self._cik_resolver = cik_resolver or SecCikResolver()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": SEC_USER_AGENT})

    def fetch(self, ticker: str) -> PressReleaseSignal:
        cik = self._cik_resolver.resolve(ticker)
        if not cik:
            return PressReleaseSignal(
                ticker=ticker, source="edgar_submissions", releases=[],
                error=f"CIK not found for {ticker}",
            )

        try:
            resp = self._session.get(
                SEC_SUBMISSIONS_URL.format(cik=cik), timeout=_HTTP_TIMEOUT
            )
            resp.raise_for_status()
            recent = resp.json().get("filings", {}).get("recent", {})
        except requests.RequestException as exc:
            logger.warning("EDGAR submissions press release fetch failed for %s: %s", ticker, exc)
            return PressReleaseSignal(
                ticker=ticker, source="edgar_submissions", releases=[], error=str(exc)
            )

        cutoff     = (datetime.now(timezone.utc) - timedelta(days=self._LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        forms      = recent.get("form", [])
        dates      = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs       = recent.get("primaryDocument", [])
        descs      = recent.get("primaryDocDescription", [""] * len(forms))
        clean_cik  = cik.lstrip("0")

        releases: List[PressRelease] = []
        for form, date, acc, doc, desc in zip(forms, dates, accessions, docs, descs):
            if form not in self._PR_FORMS:
                continue
            if date < cutoff:
                break  # submissions are newest-first; past window means we're done
            acc_nodash = acc.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{acc_nodash}/{doc}"
                if acc_nodash and doc else None
            )
            releases.append(PressRelease(title=desc or f"{form} filing", date=date, url=url))
            if len(releases) >= self._MAX_RELEASES:
                break

        return PressReleaseSignal(ticker=ticker, source="edgar_submissions", releases=releases)


# ──────────────────────────────────────────────────────────────────────────────
# Stanford Securities Class Action Clearinghouse — litigation monitor
# ──────────────────────────────────────────────────────────────────────────────

class LitigationFetcher:
    """
    Securities litigation monitor with two-stage strategy:
      1. Stanford SCAC full-text search (https://securities.stanford.edu/fullsearch.html)
         — primary source, detects restructuring/unavailability by banner text.
      2. EDGAR EFTS keyword fallback — searches the company's own 6-K/8-K filings for
         "class action" or "securities litigation" mentions when SCAC is unavailable.

    SCAC restructuring notice (as of 2026-05-26): site is down until Winter 2026.
    """
    _SCAC_URL      = "https://securities.stanford.edu/fullsearch.html"
    _EFTS_URL      = "https://efts.sec.gov/LATEST/search-index"
    _LOOKBACK_DAYS = 730  # 2 years for litigation
    _MAX_CASES     = 5
    _RESTRUCTURING_SENTINEL = "under construction"

    def __init__(self, cik_resolver: Optional["SecCikResolver"] = None) -> None:
        self._cik_resolver = cik_resolver or SecCikResolver()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": SEC_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*",
        })

    def fetch(self, company_name: str, ticker: Optional[str] = None) -> LitigationSignal:
        # Stage 1: Stanford SCAC
        scac_result = self._try_scac(company_name)
        if scac_result is not None:
            return scac_result

        # Stage 2: EDGAR EFTS keyword search on the company's own filings
        return self._try_edgar_efts(company_name, ticker=ticker)

    def _try_scac(self, company_name: str) -> Optional[LitigationSignal]:
        try:
            resp = self._session.get(
                self._SCAC_URL, params={"q": company_name}, timeout=_HTTP_TIMEOUT
            )
            resp.raise_for_status()
            if self._RESTRUCTURING_SENTINEL in resp.text.lower():
                logger.info("Stanford SCAC is under restructuring — using EDGAR fallback")
                return None
            cases = self._parse_scac_html(resp.text)
            return LitigationSignal(company_name=company_name, source="stanford_scac", cases=cases)
        except requests.RequestException as exc:
            logger.warning("SCAC network error for '%s': %s", company_name, exc)
            return None
        except Exception as exc:
            logger.warning("SCAC parse error for '%s': %s", company_name, exc)
            return None

    def _try_edgar_efts(self, company_name: str, ticker: Optional[str] = None) -> LitigationSignal:
        resolved_ticker = ticker or ""
        cik = self._cik_resolver.resolve(resolved_ticker) if resolved_ticker else None
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._LOOKBACK_DAYS)).strftime("%Y-%m-%d")

        query = f'"class action" {resolved_ticker}' if resolved_ticker else '"class action"'
        try:
            resp = self._session.get(
                self._EFTS_URL,
                params={
                    "q": query,
                    "forms": "6-K,8-K",
                    "dateRange": "custom",
                    "startdt": cutoff,
                    "sort": "file-date",
                    "order": "desc",
                },
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            cases = self._parse_efts_hits(cik, resp.json())
            note = "stanford_scac_unavailable_edgar_efts_fallback"
            return LitigationSignal(
                company_name=company_name,
                source=note,
                cases=cases,
                error="Stanford SCAC temporarily down (restructuring until Winter 2026). Results from EDGAR EFTS keyword search.",
            )
        except Exception as exc:
            logger.warning("EDGAR EFTS litigation fallback failed for '%s': %s", company_name, exc)
            return LitigationSignal(
                company_name=company_name,
                source="stanford_scac",
                cases=[],
                error="Stanford SCAC temporarily unavailable (restructuring until Winter 2026). EDGAR fallback also failed.",
            )

    def _parse_scac_html(self, html: str) -> List[LitigationCase]:
        soup = BeautifulSoup(html, "html.parser")
        cases: List[LitigationCase] = []
        rows = soup.select("table.table tbody tr") or soup.select("table tbody tr")
        for row in rows[: self._MAX_CASES]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or not cells[0]:
                continue
            cases.append(LitigationCase(
                case_name=cells[0],
                filed_date=cells[1] if len(cells) > 1 else None,
                status=cells[-1] if len(cells) > 2 else None,
            ))
        return cases

    def _parse_efts_hits(self, cik: Optional[str], data: Dict) -> List[LitigationCase]:
        if cik is None:
            return []  # can't CIK-filter → skip rather than accept cross-company hits
        cases: List[LitigationCase] = []
        for hit in data.get("hits", {}).get("hits", []):
            src = hit.get("_source", {})
            if cik and cik not in (src.get("ciks") or []):
                continue
            description = src.get("file_description") or src.get("form") or "SEC Filing"
            date        = src.get("file_date") or ""
            adsh        = src.get("adsh", "").replace("-", "")
            clean_cik   = (cik or "").lstrip("0")
            hit_id      = hit.get("_id", "")
            filename    = hit_id.split(":")[-1] if ":" in hit_id else ""
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{adsh}/{filename}"
                if adsh and filename and clean_cik else None
            )
            cases.append(LitigationCase(
                case_name=f"{description} ({src.get('form','')}) — {url or 'no URL'}",
                filed_date=date,
                status="mentions_class_action_or_litigation",
            ))
            if len(cases) >= self._MAX_CASES:
                break
        return cases


# ──────────────────────────────────────────────────────────────────────────────
# Consumer Sentiment — blended across Stocktwits + HackerNews + Reddit
#
# Design goal: produce a *consistent* sentiment signal for ANY ticker, with no
# per-sector configuration required. Stocktwits and HackerNews are queried purely
# by ticker/company name (works identically for AAPL, INTC, PCOR, …); Reddit uses
# one uniform finance-subreddit set rather than a sparse hand-maintained map.
# All three are key-free; each degrades gracefully so one source failing (e.g.
# Reddit 403) never blanks the signal.
# ──────────────────────────────────────────────────────────────────────────────

_POSITIVE_WORDS = frozenset({
    "great", "excellent", "good", "strong", "solid", "impressive", "bullish",
    "growth", "beat", "outperform", "recommend", "buy", "winner", "best",
    "improving", "positive", "rising", "gain", "profit", "momentum",
    "undervalued", "cheap", "opportunity", "upside", "higher",
})
_NEGATIVE_WORDS = frozenset({
    "bad", "poor", "weak", "disappointing", "bearish", "miss", "underperform",
    "sell", "avoid", "worst", "declining", "negative", "falling", "loss",
    "cut", "concern", "risk", "overvalued", "expensive", "down", "lower",
    "terrible", "awful", "broken", "fraud", "crash", "layoffs", "lawsuit",
})
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "to", "of", "in", "for", "on", "with",
    "at", "by", "from", "as", "or", "and", "but", "not", "this", "that",
    "it", "its", "my", "your", "their", "our", "you", "we", "they",
    "about", "how", "why", "what", "when", "where", "who", "which", "just",
    "anyone", "any", "some", "more", "less", "very", "really", "still",
    # Generic comparison/temporal fillers that otherwise crowd out real themes
    "over", "than", "then", "into", "also", "even", "only", "much", "many",
    "like", "going", "make", "made", "well", "year", "years", "today", "now",
    "out", "get", "got", "one", "two", "new", "see", "say", "said",
})

# One uniform finance-discussion subreddit set, searched identically for every
# ticker. Replaces the old sparse per-sector map so a tech ticker (AAPL) and a
# PropTech ticker (PCOR) are treated the same way → consistent Reddit coverage.
_BASE_SUBREDDITS: List[str] = [
    "investing", "stocks", "StockMarket", "wallstreetbets",
    "ValueInvesting", "SecurityAnalysis",
]

_REDDIT_HEADERS = {"User-Agent": "TheoryY-ResearchAgent/1.0 (research)"}

# Source credibility weights for the blended score. Stocktwits carries native
# per-ticker investor Bull/Bear labels, so it is the most trustworthy; the news
# wires (Yahoo/Google/Bing) are factual press coverage; Reddit and HackerNews are
# lexicon-scored free-text discussion and weighted lower.
_SOURCE_WEIGHTS: Dict[str, float] = {
    "stocktwits":    1.0,
    "yahoo_finance": 0.70,
    "google_news":   0.70,
    "bing_news":     0.60,
    "reddit":        0.70,
    "hackernews":    0.60,
}
# Additive (Laplace-style) smoothing constant applied to every lexicon/label
# score: score = (pos - neg) / (pos + neg + K). It pulls thin samples toward
# neutral so a single matched word can no longer saturate the score to ±1.0 (a
# lone negative word yields ≈ -0.2, not -1.0). Saturation now requires real signal
# volume. This is the fix for the "HackerNews -1.0 / Bing +1.0 from n≈1 signal"
# artifact: confidence in the number must be *earned* by matched evidence.
_SENTIMENT_SMOOTHING_K: int = 4

# Number of *matched sentiment words* (NOT raw messages) at which a source reaches
# its full credibility weight. Sentiment words are far rarer than messages, so the
# matched-signal count — not message_count — is the honest measure of how much a
# source actually contributed. A source with 25 messages but 1 lexicon hit is a
# 1-signal source and is weighted as such.
_FULL_SIGNAL_AT: int = 8
# Matched-signal thresholds for the per-source confidence label.
_CONF_MEDIUM_AT: int = 3
_CONF_HIGH_AT:   int = 8

# If the primary sources (StockTwits + the news wires + HackerNews) return fewer
# messages than this threshold, also query Reddit as a fallback.
_REDDIT_FALLBACK_THRESHOLD: int = 10


# ──────────────────────────────────────────────────────────────────────────────
# Shared lexicon scorer — pure logic, reused by every free-text source
# ──────────────────────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
# Web/markup tokens + news-publisher names that survive cleaning and add no
# thematic signal. Publisher names leak in from news-wire titles (e.g. Google
# News appends "- Yahoo Finance"); excluding them keeps themes about the company.
_WEB_NOISE = frozenset({
    "https", "http", "www", "com", "amp", "href", "nbsp", "quot",
    "yahoo", "finance", "marketbeat", "zacks", "benzinga", "reuters",
    "bloomberg", "nasdaq", "motley", "fool", "seekingalpha", "insider",
    "barron", "barrons", "investing", "markets", "newswire", "globenewswire",
})


def _smoothed_score(pos: int, neg: int) -> Optional[float]:
    """
    Additive-smoothed polarity in [-1, 1], or None when no sentiment word matched.

    score = (pos - neg) / (pos + neg + K). The +K pseudo-count shrinks thin samples
    toward neutral so a single matched word cannot saturate the score; the magnitude
    only approaches ±1.0 as matched-word volume grows.
    """
    signal = pos + neg
    if signal == 0:
        return None
    return round((pos - neg) / (signal + _SENTIMENT_SMOOTHING_K), 2)


def _confidence_from_signal(signal_count: int) -> str:
    """Map matched-sentiment-word count → confidence label (low/medium/high)."""
    if signal_count >= _CONF_HIGH_AT:
        return "high"
    if signal_count >= _CONF_MEDIUM_AT:
        return "medium"
    return "low"


def _score_texts(texts: List[str]) -> Tuple[Optional[float], Dict[str, int], int]:
    """
    Lexicon-score a list of short texts (post titles, message bodies).

    Returns (smoothed sentiment_score in [-1, 1] or None, token-frequency map for
    themes, signal_count) — where signal_count is the number of matched
    positive/negative lexicon words. signal_count, not len(texts), is the true
    measure of how much sentiment evidence the sample carried.
    """
    pos = neg = 0
    word_freq: Dict[str, int] = {}
    for text in texts:
        clean = _URL_RE.sub(" ", text or "").lower()
        for tok in re.findall(r"[a-z]{3,}", clean):
            if tok in _WEB_NOISE:
                continue
            if tok in _POSITIVE_WORDS:
                pos += 1
            if tok in _NEGATIVE_WORDS:
                neg += 1
            if tok not in _STOPWORDS and len(tok) > 3:
                word_freq[tok] = word_freq.get(tok, 0) + 1
    return _smoothed_score(pos, neg), word_freq, pos + neg


def _pick_quotes(
    texts: List[str],
    n: int = 3,
    require_any: Optional[List[str]] = None,
) -> List[str]:
    """Select up to n representative excerpts, preferring texts with sentiment signal and length.

    require_any: if provided, only consider texts that contain at least one of these tokens
    (used to filter off-topic results from general-purpose sources like HackerNews).
    """
    _MIN_CHARS = 30

    def _clean(t: str) -> str:
        t = html.unescape(t)
        t = _URL_RE.sub("", t).strip()
        return t

    cleaned = [_clean(t) for t in texts]

    if require_any:
        must = {tok.lower() for tok in require_any}
        cleaned = [c for c in cleaned if any(m in c.lower() for m in must)]

    candidates = [c for c in cleaned if len(c) >= _MIN_CHARS]

    def _score(t: str) -> float:
        tokens = set(re.findall(r"[a-z]{3,}", t.lower()))
        signal = len(tokens & (_POSITIVE_WORDS | _NEGATIVE_WORDS))
        return signal * 10 + min(len(t), 280) / 280

    return sorted(candidates, key=_score, reverse=True)[:n]


def _parse_rss_headlines(content: bytes, max_items: int) -> List[str]:
    """Parse an RSS/Atom feed body into a list of 'title: description' strings.

    Shared by every news-wire fetcher (Yahoo, Google News, Bing). HTML tags inside
    descriptions are stripped; empty titles are dropped. Raises ET.ParseError on
    malformed XML so callers can record the error gracefully.
    """
    root = ET.fromstring(content)
    items = root.findall(".//item")[:max_items]
    texts: List[str] = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        desc  = (item.findtext("description") or "").strip()
        desc  = re.sub(r"<[^>]+>", " ", desc)           # strip HTML markup
        desc  = html.unescape(desc)                     # &nbsp; &amp; → real chars
        desc  = re.sub(r"\s+", " ", desc).strip()
        title = html.unescape(title)
        if title:
            texts.append(title if not desc else f"{title}: {desc}")
    return texts


@dataclass
class _RawSourceResult:
    """Internal: one source's raw contribution before blending."""
    source:        str
    texts:         List[str]            # free text used for theme extraction
    message_count: int
    native_score:  Optional[float] = None  # explicit-label score (Stocktwits); else None
    error:         Optional[str]   = None
    quotes:        List[str]       = field(default_factory=list)  # representative excerpts
    signal_count:  int = 0              # native-label count for native sources (else 0)


# ──────────────────────────────────────────────────────────────────────────────
# Stocktwits — per-ticker investor sentiment with native Bull/Bear labels
# ──────────────────────────────────────────────────────────────────────────────

class StocktwitsSentimentFetcher:
    """
    Infrastructure: queries Stocktwits' public symbol stream (no API key).
    Each message may carry an explicit Bullish/Bearish label, giving a native
    sentiment score independent of the lexicon. Works for any US ticker.
    """
    _URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _REDDIT_HEADERS["User-Agent"]})

    def fetch(self, ticker: str) -> _RawSourceResult:
        url = self._URL.format(symbol=ticker.upper())
        try:
            resp = self._session.get(url, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
        except requests.RequestException as exc:
            logger.warning("Stocktwits fetch failed for %s: %s", ticker, exc)
            return _RawSourceResult("stocktwits", [], 0, error=str(exc))
        except ValueError as exc:  # non-JSON body
            logger.warning("Stocktwits returned non-JSON for %s: %s", ticker, exc)
            return _RawSourceResult("stocktwits", [], 0, error="invalid response")

        texts: List[str] = []
        bull = bear = 0
        for msg in messages:
            body = msg.get("body") or ""
            if body:
                texts.append(body)
            basic = (((msg.get("entities") or {}).get("sentiment") or {}).get("basic"))
            if basic == "Bullish":
                bull += 1
            elif basic == "Bearish":
                bear += 1

        # Smooth the native Bull/Bear score the same way as the lexicon sources so a
        # handful of labels can't saturate it, and carry the labeled count as the
        # source's signal so the blend weights it by real evidence, not raw volume.
        labeled = bull + bear
        native = _smoothed_score(bull, bear)
        return _RawSourceResult(
            source="stocktwits",
            texts=texts,
            message_count=len(messages),
            native_score=native,
            signal_count=labeled,
            quotes=_pick_quotes(texts, n=3),
        )


# ──────────────────────────────────────────────────────────────────────────────
# HackerNews — tech / B2B discussion via the Algolia search API (no API key)
# ──────────────────────────────────────────────────────────────────────────────

class HackerNewsSentimentFetcher:
    """
    Infrastructure: full-text search of HackerNews stories + comments via the
    public Algolia API. Scored from the lexicon (no native sentiment). Surfaces
    enterprise/tech sentiment that finance forums miss; works for any company.
    """
    _URL       = "https://hn.algolia.com/api/v1/search"
    _MAX_HITS  = 25

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _REDDIT_HEADERS["User-Agent"]})

    def fetch(self, company_name: str) -> _RawSourceResult:
        params = {
            "query":       company_name,
            "tags":        "(story,comment)",
            "hitsPerPage": self._MAX_HITS,
        }
        try:
            resp = self._session.get(self._URL, params=params, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except requests.RequestException as exc:
            logger.warning("HackerNews fetch failed for '%s': %s", company_name, exc)
            return _RawSourceResult("hackernews", [], 0, error=str(exc))
        except ValueError as exc:
            logger.warning("HackerNews returned non-JSON for '%s': %s", company_name, exc)
            return _RawSourceResult("hackernews", [], 0, error="invalid response")

        # Algolia returns story titles and comment text in different fields.
        texts = [
            (h.get("title") or h.get("story_title") or h.get("comment_text") or "")
            for h in hits
        ]
        texts = [t for t in texts if t]
        # Only surface HN quotes that actually mention the company — HN searches by
        # relevance but can return loosely-related results for non-tech companies.
        name_tokens = re.findall(r"[A-Za-z]{3,}", company_name)
        return _RawSourceResult(
            source="hackernews",
            texts=texts,
            message_count=len(texts),
            quotes=_pick_quotes(texts, n=2, require_any=name_tokens),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Reddit — investing subreddits via public JSON (best-effort, no auth)
# ──────────────────────────────────────────────────────────────────────────────

class RedditSentimentFetcher:
    """
    Infrastructure: queries Reddit's public JSON search API (no auth required).
    Searches one uniform set of finance subreddits for every ticker. Best-effort:
    Reddit increasingly returns 403 to unauthenticated clients, which is handled
    gracefully (empty result, error recorded) rather than failing the blend.
    """
    _MAX_POSTS = 25
    _LOOKBACK  = "year"   # Reddit time filter: hour, day, week, month, year, all

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(_REDDIT_HEADERS)

    def fetch(self, ticker: str, company_name: str) -> _RawSourceResult:
        sr_param = "+".join(_BASE_SUBREDDITS)
        # Cashtag + name keeps the query identical in shape for every ticker.
        query = f"${ticker.upper()} OR \"{company_name}\""
        params: Dict = {
            "q":           query,
            "sort":        "relevance",
            "t":           self._LOOKBACK,
            "limit":       self._MAX_POSTS,
            "type":        "link",
            "restrict_sr": "true",
        }
        url = f"https://www.reddit.com/r/{sr_param}/search.json"
        try:
            resp = self._session.get(url, params=params, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
        except requests.RequestException as exc:
            logger.warning("Reddit fetch failed (query='%s'): %s", query, exc)
            return _RawSourceResult("reddit", [], 0, error=str(exc))
        except ValueError as exc:
            logger.warning("Reddit returned non-JSON (query='%s'): %s", query, exc)
            return _RawSourceResult("reddit", [], 0, error="invalid response")

        titles = [c["data"].get("title") or "" for c in children if "data" in c]
        titles = [t for t in titles if t]
        return _RawSourceResult(
            source="reddit",
            texts=titles,
            message_count=len(titles),
            quotes=_pick_quotes(titles, n=2),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Yahoo Finance — news RSS headlines (no API key, no auth)
# ──────────────────────────────────────────────────────────────────────────────

class YahooFinanceNewsFetcher:
    """
    Infrastructure: fetches Yahoo Finance news RSS for a ticker (no auth required).
    Returns up to 20 recent headlines + snippets. Scored via the lexicon (no native
    sentiment). Provides a factual news signal (earnings beats, guidance changes,
    analyst upgrades) that complements StockTwits opinion data.
    """
    _URL       = "https://finance.yahoo.com/rss/headline"
    _MAX_ITEMS = 20

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _REDDIT_HEADERS["User-Agent"]})

    def fetch(self, ticker: str) -> _RawSourceResult:
        try:
            resp = self._session.get(
                self._URL, params={"s": ticker.upper()}, timeout=_HTTP_TIMEOUT
            )
            resp.raise_for_status()
            texts = _parse_rss_headlines(resp.content, self._MAX_ITEMS)
        except requests.RequestException as exc:
            logger.warning("Yahoo Finance RSS failed for %s: %s", ticker, exc)
            return _RawSourceResult("yahoo_finance", [], 0, error=str(exc))
        except ET.ParseError as exc:
            logger.warning("Yahoo Finance RSS parse error for %s: %s", ticker, exc)
            return _RawSourceResult("yahoo_finance", [], 0, error="xml parse error")

        return _RawSourceResult(
            source="yahoo_finance",
            texts=texts,
            message_count=len(texts),
            quotes=_pick_quotes(texts, n=3),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Google News — broad press coverage via the public RSS search (no API key)
# ──────────────────────────────────────────────────────────────────────────────

class GoogleNewsFetcher:
    """
    Infrastructure: fetches Google News RSS search results for a company (no auth).
    Casts the widest net of any source — national press, trade publications, and
    wire services — so it captures coverage the finance-specific feeds miss. Scored
    via the lexicon. Query is company name + cashtag for consistent shape per ticker.
    """
    _URL       = "https://news.google.com/rss/search"
    _MAX_ITEMS = 25

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _REDDIT_HEADERS["User-Agent"]})

    def fetch(self, ticker: str, company_name: str) -> _RawSourceResult:
        query = f'"{company_name}" OR {ticker.upper()} stock'
        params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
        try:
            resp = self._session.get(self._URL, params=params, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            texts = _parse_rss_headlines(resp.content, self._MAX_ITEMS)
        except requests.RequestException as exc:
            logger.warning("Google News RSS failed for '%s': %s", company_name, exc)
            return _RawSourceResult("google_news", [], 0, error=str(exc))
        except ET.ParseError as exc:
            logger.warning("Google News RSS parse error for '%s': %s", company_name, exc)
            return _RawSourceResult("google_news", [], 0, error="xml parse error")

        # Google News appends " - Publisher" to titles; the company name should
        # still appear, so filter to on-topic items to drop bleed-over results.
        name_tokens = re.findall(r"[A-Za-z]{3,}", company_name)
        return _RawSourceResult(
            source="google_news",
            texts=texts,
            message_count=len(texts),
            quotes=_pick_quotes(texts, n=3, require_any=name_tokens),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Bing News — secondary press wire via the public RSS search (no API key)
# ──────────────────────────────────────────────────────────────────────────────

class BingNewsFetcher:
    """
    Infrastructure: fetches Bing News RSS search results for a company (no auth).
    Provides press-coverage redundancy against Google News with a different crawler
    and ranking, improving recall for thinly-covered tickers. Scored via the lexicon.
    """
    _URL       = "https://www.bing.com/news/search"
    _MAX_ITEMS = 20

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _REDDIT_HEADERS["User-Agent"]})

    def fetch(self, ticker: str, company_name: str) -> _RawSourceResult:
        params = {"q": f'"{company_name}"', "format": "rss"}
        try:
            resp = self._session.get(self._URL, params=params, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            texts = _parse_rss_headlines(resp.content, self._MAX_ITEMS)
        except requests.RequestException as exc:
            logger.warning("Bing News RSS failed for '%s': %s", company_name, exc)
            return _RawSourceResult("bing_news", [], 0, error=str(exc))
        except ET.ParseError as exc:
            logger.warning("Bing News RSS parse error for '%s': %s", company_name, exc)
            return _RawSourceResult("bing_news", [], 0, error="xml parse error")

        name_tokens = re.findall(r"[A-Za-z]{3,}", company_name)
        return _RawSourceResult(
            source="bing_news",
            texts=texts,
            message_count=len(texts),
            quotes=_pick_quotes(texts, n=2, require_any=name_tokens),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Multi-source aggregator — blends every source into one signal
# ──────────────────────────────────────────────────────────────────────────────

class MultiSourceSentimentAggregator:
    """
    Domain + orchestration: fetches every source for a ticker (primary sources in
    parallel; Reddit only as a thin-coverage fallback) and blends them into a single
    ConsumerSentimentSignal. The blend is a weighted mean of each source's score
    (native where available, else lexicon), weighted by source credibility scaled by
    sample size. Themes and representative quotes are pooled across all sources.
    """

    def __init__(
        self,
        stocktwits:  Optional[StocktwitsSentimentFetcher]  = None,
        hackernews:  Optional[HackerNewsSentimentFetcher]  = None,
        yahoo:       Optional[YahooFinanceNewsFetcher]      = None,
        google_news: Optional[GoogleNewsFetcher]           = None,
        bing_news:   Optional[BingNewsFetcher]             = None,
        reddit:      Optional[RedditSentimentFetcher]       = None,
    ) -> None:
        self._stocktwits  = stocktwits  or StocktwitsSentimentFetcher()
        self._hackernews  = hackernews  or HackerNewsSentimentFetcher()
        self._yahoo       = yahoo       or YahooFinanceNewsFetcher()
        self._google_news = google_news or GoogleNewsFetcher()
        self._bing_news   = bing_news   or BingNewsFetcher()
        self._reddit      = reddit      or RedditSentimentFetcher()

    def get_signal(self, ticker: str, company_name: str) -> ConsumerSentimentSignal:
        # Primary sources: always queried, fetched concurrently for speed.
        fetches = [
            lambda: self._stocktwits.fetch(ticker),
            lambda: self._yahoo.fetch(ticker),
            lambda: self._google_news.fetch(ticker, company_name),
            lambda: self._bing_news.fetch(ticker, company_name),
            lambda: self._hackernews.fetch(company_name),
        ]
        with ThreadPoolExecutor(max_workers=len(fetches)) as pool:
            raws = list(pool.map(lambda fn: fn(), fetches))

        # Reddit is a fallback: only queried when the primary sources are thin.
        primary_count = sum(r.message_count for r in raws)
        if primary_count < _REDDIT_FALLBACK_THRESHOLD:
            logger.info("Primary sources thin (%d msgs); adding Reddit fallback", primary_count)
            raws.append(self._reddit.fetch(ticker, company_name))
        return self._blend(ticker, company_name, raws)

    # ── private logic ───────────────────────────────────────────────────────────

    def _blend(
        self, ticker: str, company_name: str, raws: List[_RawSourceResult]
    ) -> ConsumerSentimentSignal:
        sources: List[SourceSentiment] = []
        pooled_freq: Dict[str, int] = {}
        weighted_sum = weight_total = 0.0
        total_messages = 0

        for raw in raws:
            # Effective signal = matched sentiment evidence, NOT raw message count.
            # For native (Stocktwits) sources it is the labeled count; for lexicon
            # sources it is the matched-word count. This is what gates credibility:
            # a 25-message source with one lexicon hit is a 1-signal source.
            if raw.native_score is not None:
                score = raw.native_score
                eff_signal = raw.signal_count if raw.signal_count > 0 else raw.message_count
                _, freq, _ = _score_texts(raw.texts)  # still pool themes from text
            else:
                score, freq, eff_signal = _score_texts(raw.texts)

            for tok, n in freq.items():
                pooled_freq[tok] = pooled_freq.get(tok, 0) + n
            total_messages += raw.message_count

            # Credibility weight scaled by matched signal, so thin samples can't
            # dominate even if they returned many (low-signal) messages.
            weight = 0.0
            if score is not None and eff_signal > 0:
                sample_factor = min(eff_signal, _FULL_SIGNAL_AT) / _FULL_SIGNAL_AT
                weight = _SOURCE_WEIGHTS.get(raw.source, 0.5) * sample_factor
                weighted_sum += score * weight
                weight_total += weight

            sources.append(SourceSentiment(
                source=raw.source,
                available=raw.message_count > 0,
                message_count=raw.message_count,
                sentiment_score=score,
                weight=round(weight, 3),
                error=raw.error,
                signal_count=eff_signal,
                confidence=_confidence_from_signal(eff_signal),
            ))

        blended:    Optional[float] = None
        label:      Optional[str]   = None
        confidence: Optional[str]   = None
        if weight_total > 0:
            blended = round(weighted_sum / weight_total, 2)
            label = "positive" if blended > 0.2 else "negative" if blended < -0.2 else "mixed"
            # Overall confidence: total matched signal across contributing sources,
            # tempered by how many cleared at least the medium bar. A blend resting on
            # a single low-signal source stays "low" even if its score is extreme.
            contributing = [s for s in sources if s.weight > 0]
            total_signal = sum(s.signal_count for s in contributing)
            med_plus = sum(1 for s in contributing if s.confidence in ("medium", "high"))
            if total_signal >= _CONF_HIGH_AT and med_plus >= 2:
                confidence = "high"
            elif total_signal >= _CONF_MEDIUM_AT and med_plus >= 1:
                confidence = "medium"
            else:
                confidence = "low"

        # Pooled top-5 themes, excluding the ticker/company name tokens.
        name_tokens = set(re.findall(r"[a-z]{3,}", company_name.lower()))
        name_tokens.add(ticker.lower())
        themes = [
            w for w, _ in sorted(pooled_freq.items(), key=lambda x: -x[1])
            if w not in name_tokens
        ][:5]

        # Aggregate representative quotes: up to 2 per source, max 5 total.
        all_quotes: List[Dict[str, str]] = []
        for raw in raws:
            for q in raw.quotes[:2]:
                all_quotes.append({"source": raw.source, "text": q})
        all_quotes = all_quotes[:5]

        # Surface a data-gap note only when every source came back empty.
        error: Optional[str] = None
        if total_messages == 0:
            reasons = "; ".join(
                f"{s.source}: {s.error}" for s in sources if s.error
            ) or "no messages returned by any source"
            error = f"no sentiment data available ({reasons})"

        active = [s.source for s in sources if s.available]
        return ConsumerSentimentSignal(
            ticker=ticker,
            company_name=company_name,
            post_count=total_messages,
            sentiment=label,
            sentiment_score=blended,
            top_themes=themes,
            source="multi_source" if len(active) != 1 else active[0],
            subreddits=_BASE_SUBREDDITS,
            sources=sources,
            top_quotes=all_quotes,
            error=error,
            confidence=confidence,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Massive / Polygon — structured news sentiment + 52-week price metrics
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class MassiveNewsArticle:
    """Single news article with machine-written per-ticker sentiment from Polygon."""
    title:                str
    published_utc:        str
    publisher:            str
    sentiment:            Optional[str]           # "positive" | "neutral" | "negative"
    sentiment_reasoning:  Optional[str]           # analyst-quality prose from Polygon
    url:                  Optional[str] = None    # article URL (for deep web-research scraping)


@dataclass
class MassiveNewsSignal:
    """Recent news for one ticker with pre-computed sentiment from Polygon news API."""
    ticker:            str
    article_count:     int
    articles:          List[MassiveNewsArticle]
    blended_sentiment: Optional[str]              # majority vote across articles
    error:             Optional[str] = None


@dataclass
class MassivePriceMetrics:
    """52-week price performance computed from Polygon OHLCV bars."""
    ticker:          str
    current_price:   Optional[float]
    high_52w:        Optional[float]
    low_52w:         Optional[float]
    return_1y_pct:   Optional[float]              # % change over trailing 52 weeks
    return_30d_pct:  Optional[float]              # % change over trailing ~22 trading days
    bars_used:       int = 0
    error:           Optional[str] = None


@dataclass
class RelatedCompaniesSignal:
    """Peer tickers for one company, discovered dynamically from Polygon."""
    ticker:    str
    related:   List[str]                          # related tickers, self excluded
    source:    str = "polygon_related_companies"
    error:     Optional[str] = None


class RelatedCompaniesFetcher:
    """
    Infrastructure: discovers peer tickers for *any* company from Polygon's
    `/v1/related-companies/{ticker}` endpoint.

    Polygon derives this set from news co-mentions and price-action correlation,
    so it generalises across every sector with zero hand-maintained config — it is
    the dynamic replacement for the static COMPETITOR_MAP. Returns an empty list
    (never raises) when the key is absent or the endpoint has no data, so callers
    can fall back to a curated mapping or simply omit peers.
    """

    def __init__(self, api_key: str = MASSIVE_API_KEY) -> None:
        self._api_key = api_key
        self._session = requests.Session()
        if api_key:
            self._session.headers.update({"Authorization": f"Bearer {api_key}"})

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def fetch(self, ticker: str) -> RelatedCompaniesSignal:
        ticker_up = ticker.upper().strip()
        if not self.is_configured:
            return RelatedCompaniesSignal(
                ticker=ticker_up, related=[], error="MASSIVE_API_KEY not configured"
            )
        try:
            resp = self._session.get(
                f"{_MASSIVE_BASE_URL}/v1/related-companies/{ticker_up}",
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except requests.RequestException as exc:
            logger.error("Related-companies fetch failed for %s: %s", ticker_up, exc)
            return RelatedCompaniesSignal(ticker=ticker_up, related=[], error=str(exc))

        related: List[str] = []
        for item in results:
            sym = (item.get("ticker") or "").upper().strip()
            if sym and sym != ticker_up and sym not in related:
                related.append(sym)
        return RelatedCompaniesSignal(ticker=ticker_up, related=related)


class MassiveNewsFetcher:
    """
    Infrastructure: fetches recent news articles for a ticker from the Polygon
    news API, extracting the per-ticker sentiment label and reasoning for each article.

    Polygon's `/v2/reference/news` returns an `insights` array per article where
    each element carries an explicit sentiment label and machine-written reasoning
    sentence for every ticker mentioned. This is substantially higher signal than
    lexicon-scored RSS headlines: the reasoning explains *why* sentiment was assigned,
    giving the memo writer concrete, citable analyst perspectives.
    """

    _NEWS_LIMIT: int = 6

    def __init__(self, api_key: str = MASSIVE_API_KEY) -> None:
        self._api_key = api_key
        self._session = requests.Session()
        if api_key:
            self._session.headers.update({"Authorization": f"Bearer {api_key}"})

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def fetch(self, ticker: str) -> MassiveNewsSignal:
        if not self.is_configured:
            return MassiveNewsSignal(
                ticker=ticker, article_count=0, articles=[],
                blended_sentiment=None, error="MASSIVE_API_KEY not configured",
            )
        ticker_up = ticker.upper()
        try:
            resp = self._session.get(
                f"{_MASSIVE_BASE_URL}/v2/reference/news",
                params={"ticker": ticker_up, "limit": self._NEWS_LIMIT,
                        "order": "desc", "sort": "published_utc"},
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except requests.RequestException as exc:
            logger.error("Massive news fetch failed for %s: %s", ticker, exc)
            return MassiveNewsSignal(
                ticker=ticker, article_count=0, articles=[],
                blended_sentiment=None, error=str(exc),
            )

        articles: List[MassiveNewsArticle] = []
        for item in results:
            insight = next(
                (i for i in (item.get("insights") or []) if i.get("ticker") == ticker_up),
                None,
            )
            articles.append(MassiveNewsArticle(
                title=item.get("title", ""),
                published_utc=item.get("published_utc", ""),
                publisher=(item.get("publisher") or {}).get("name", ""),
                sentiment=insight.get("sentiment") if insight else None,
                sentiment_reasoning=insight.get("sentiment_reasoning") if insight else None,
                url=item.get("article_url") or None,
            ))

        return MassiveNewsSignal(
            ticker=ticker,
            article_count=len(articles),
            articles=articles,
            blended_sentiment=self._majority_sentiment(articles),
        )

    @staticmethod
    def _majority_sentiment(articles: List[MassiveNewsArticle]) -> Optional[str]:
        counts: Dict[str, int] = {}
        for a in articles:
            if a.sentiment:
                counts[a.sentiment] = counts.get(a.sentiment, 0) + 1
        if not counts:
            return None
        return max(counts, key=lambda k: counts[k])


class MassivePriceFetcher:
    """
    Infrastructure: fetches one year of daily OHLCV bars from the Polygon aggregates
    API and derives the four price-performance metrics the memo uses most:
      • current_price   — latest adjusted close
      • high_52w        — highest intraday high over the trailing 52 weeks
      • low_52w         — lowest intraday low over the trailing 52 weeks
      • return_1y_pct   — total price return from the first bar to the latest bar
      • return_30d_pct  — price return over the last ~22 trading days (≈ 1 calendar month)

    These are standard valuation-snapshot anchors that the existing yfinance pipeline
    does not expose in the context payload.
    """

    _LOOKBACK_DAYS: int = 370    # fetch slightly more than 365 to absorb weekends/holidays

    def __init__(self, api_key: str = MASSIVE_API_KEY) -> None:
        self._api_key = api_key
        self._session = requests.Session()
        if api_key:
            self._session.headers.update({"Authorization": f"Bearer {api_key}"})

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def fetch(self, ticker: str) -> MassivePriceMetrics:
        if not self.is_configured:
            return MassivePriceMetrics(
                ticker=ticker, current_price=None, high_52w=None, low_52w=None,
                return_1y_pct=None, return_30d_pct=None, error="MASSIVE_API_KEY not configured",
            )
        today        = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        one_year_ago = (datetime.now(timezone.utc) - timedelta(days=self._LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        ticker_up    = ticker.upper()

        try:
            resp = self._session.get(
                f"{_MASSIVE_BASE_URL}/v2/aggs/ticker/{ticker_up}/range/1/day/{one_year_ago}/{today}",
                params={"adjusted": "true", "sort": "asc", "limit": 365},
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            bars = resp.json().get("results", [])
        except requests.RequestException as exc:
            logger.error("Massive price fetch failed for %s: %s", ticker, exc)
            return MassivePriceMetrics(
                ticker=ticker, current_price=None, high_52w=None, low_52w=None,
                return_1y_pct=None, return_30d_pct=None, error=str(exc),
            )

        if not bars:
            return MassivePriceMetrics(
                ticker=ticker, current_price=None, high_52w=None, low_52w=None,
                return_1y_pct=None, return_30d_pct=None, bars_used=0,
                error="no price bars returned",
            )

        closes = [b["c"] for b in bars]
        highs  = [b["h"] for b in bars]
        lows   = [b["l"] for b in bars]

        current  = round(closes[-1], 2)
        high_52w = round(max(highs), 2)
        low_52w  = round(min(lows), 2)

        ret_1y: Optional[float] = None
        if closes[0]:
            ret_1y = round((closes[-1] - closes[0]) / closes[0] * 100, 2)

        # ~22 trading days ≈ 1 calendar month; skip if we don't have enough history
        ret_30d: Optional[float] = None
        if len(closes) >= 23:
            ref = closes[-22]
            if ref:
                ret_30d = round((closes[-1] - ref) / ref * 100, 2)

        return MassivePriceMetrics(
            ticker=ticker,
            current_price=current,
            high_52w=high_52w,
            low_52w=low_52w,
            return_1y_pct=ret_1y,
            return_30d_pct=ret_30d,
            bars_used=len(bars),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Service Façade — composes all data sources
# ──────────────────────────────────────────────────────────────────────────────

class AltDataService:
    """
    High-level orchestrator for all alternative data sources.
    All collaborators are constructor-injected for testability (Dependency Inversion).
    """

    def __init__(
        self,
        fred_api_key:         str                                = FRED_API_KEY,
        trends_fetcher:       Optional[GoogleTrendsFetcher]      = None,
        trends_processor:     Optional[GoogleTrendsProcessor]    = None,
        fred_fetcher:         Optional[FredApiFetcher]           = None,
        fred_processor:       Optional[FredDataProcessor]        = None,
        cik_resolver:         Optional[SecCikResolver]           = None,
        filing_fetcher:       Optional[SecFilingFetcher]         = None,
        risk_extractor:       Optional[SecRiskFactorExtractor]   = None,
        job_scraper:          Optional[ApifyJobScraper]          = None,
        sec_8k_fetcher:       Optional[Sec8KFetcher]             = None,
        pr_fetcher:           Optional[PressReleaseFetcher]      = None,
        lit_fetcher:          Optional[LitigationFetcher]        = None,
        sentiment_aggregator: Optional[MultiSourceSentimentAggregator] = None,
        massive_news_fetcher:  Optional[MassiveNewsFetcher]      = None,
        massive_price_fetcher: Optional[MassivePriceFetcher]     = None,
        related_companies_fetcher: Optional[RelatedCompaniesFetcher] = None,
        web_research_service:  Optional[object]                  = None,
    ) -> None:
        self._trends_fetcher      = trends_fetcher      or GoogleTrendsFetcher()
        self._trends_processor    = trends_processor    or GoogleTrendsProcessor()
        self._fred_fetcher        = fred_fetcher        or FredApiFetcher(api_key=fred_api_key)
        self._fred_processor      = fred_processor      or FredDataProcessor()
        self._cik_resolver        = cik_resolver        or SecCikResolver()
        self._filing_fetcher      = filing_fetcher      or SecFilingFetcher()
        self._risk_extractor      = risk_extractor      or SecRiskFactorExtractor()
        self._job_scraper         = job_scraper         or ApifyJobScraper()
        # Share the CIK resolver so the in-memory cache is reused across all SEC calls
        self._sec_8k_fetcher      = sec_8k_fetcher      or Sec8KFetcher(cik_resolver=self._cik_resolver)
        self._pr_fetcher          = pr_fetcher          or PressReleaseFetcher(cik_resolver=self._cik_resolver)
        self._lit_fetcher         = lit_fetcher         or LitigationFetcher(cik_resolver=self._cik_resolver)
        self._sentiment_aggregator = sentiment_aggregator or MultiSourceSentimentAggregator()
        self._massive_news        = massive_news_fetcher  or MassiveNewsFetcher()
        self._massive_price       = massive_price_fetcher or MassivePriceFetcher()
        self._related_companies   = related_companies_fetcher or RelatedCompaniesFetcher()
        # Lazily constructed on first use so the heavy scrapegraphai import only
        # happens when web research is actually requested (and stays optional).
        self._web_research        = web_research_service

    # ── public API ────────────────────────────────────────────────────────────

    def get_trends_signal(self, ticker: str, company_name: Optional[str] = None) -> TrendsSignal:
        keyword = _trends_keyword(ticker, company_name)
        df = self._trends_fetcher.fetch_interest_over_time(keyword)
        return self._trends_processor.compute_signal(ticker, keyword, df)

    def get_related_tickers(self, ticker: str) -> List[str]:
        """Dynamically discover peer tickers for *ticker* (empty list on failure)."""
        return self._related_companies.fetch(ticker).related

    def get_fred_macro(
        self,
        series_id: str = "TLNRESCONS",
        label:     str = "Commercial Construction Spending",
    ) -> FredSeries:
        observations = self._fred_fetcher.fetch_series(series_id)
        result = self._fred_processor.process(series_id, observations)
        result.title = label
        return result

    def get_sec_risk_snippet(self, ticker: str) -> SecRiskSnippet:
        cik = self._cik_resolver.resolve(ticker)
        if not cik:
            return SecRiskSnippet(
                ticker=ticker, cik=None, filing_url=None, risk_factors_snippet=None
            )
        filing_url = self._filing_fetcher.get_latest_10k_url(cik)
        if not filing_url:
            return SecRiskSnippet(
                ticker=ticker, cik=cik, filing_url=None, risk_factors_snippet=None
            )
        snippet = self._risk_extractor.extract(filing_url)
        return SecRiskSnippet(
            ticker=ticker,
            cik=cik,
            filing_url=filing_url,
            risk_factors_snippet=snippet,
        )

    def get_job_market_signal(self, company_name: str) -> ApifyJobsResult:
        return self._job_scraper.get_open_engineering_roles(company_name)

    def get_sec_8k_events(self, ticker: str) -> Sec8KSignal:
        return self._sec_8k_fetcher.fetch(ticker)

    def get_press_releases(self, ticker: str) -> PressReleaseSignal:
        return self._pr_fetcher.fetch(ticker)

    def get_litigation_signal(self, company_name: str, ticker: Optional[str] = None) -> LitigationSignal:
        return self._lit_fetcher.fetch(company_name, ticker=ticker)

    def get_consumer_sentiment(self, ticker: str, company_name: str) -> ConsumerSentimentSignal:
        return self._sentiment_aggregator.get_signal(ticker, company_name)

    def get_massive_news(self, ticker: str) -> MassiveNewsSignal:
        return self._massive_news.fetch(ticker)

    def get_massive_price_metrics(self, ticker: str) -> MassivePriceMetrics:
        return self._massive_price.fetch(ticker)

    def get_web_research(self, ticker: str, company_name: str):
        """
        First-hand web research (news bodies + niche forums) via ScrapeGraphAI.
        The collaborator is imported and built lazily so the heavy scrapegraphai
        dependency is only loaded when this signal is actually requested; it
        degrades to a clearly-marked stub when scrapegraphai/key are absent.
        """
        if self._web_research is None:
            from web_research_service import WebResearchService
            self._web_research = WebResearchService()
        return self._web_research.get_web_research(ticker, company_name)
