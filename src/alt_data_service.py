"""
alt_data_service.py — Macro & Alternative Signal Engine
=========================================================
Sources:
  1. Google Trends (pytrends)  — search-interest velocity as demand proxy
  2. FRED API (requests)       — commercial construction macro indicator
  3. SEC EDGAR API (requests)  — most-recent 10-K + Item 1A risk snippet
  4. Apify REST API (requests) — job-listing scraper (live when APIFY_API_KEY set)
  5. Consumer sentiment        — blended across three key-free public sources,
       uniformly for any ticker (MultiSourceSentimentAggregator):
         • Stocktwits  — per-ticker investors, native Bull/Bear labels (primary)
         • HackerNews  — tech / B2B discussion via the Algolia search API
         • Reddit      — investing subreddits, public JSON (best-effort)

Architecture (Clean Architecture + SOLID):
  Each data source has a dedicated Fetcher (I/O) and Processor (pure logic).
  AltDataService is the façade that wires them together.
"""

from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from pytrends.request import TrendReq
import pandas as pd

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration — inject credentials via environment variables
# ──────────────────────────────────────────────────────────────────────────────

# FRED API key — free registration at https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY: str = os.getenv("FRED_API_KEY", "YOUR_FRED_API_KEY_HERE")
FRED_BASE_URL: str = "https://api.stlouisfed.org/fred/series/observations"

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
    sentiment_score: Optional[float]  # -1.0 … 1.0 for this source alone
    weight:          float            # contribution weight in the blend (0 if unused)
    error:           Optional[str] = None


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
    error:           Optional[str] = None


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
# per-ticker investor Bull/Bear labels, so it is the most trustworthy; Reddit and
# HackerNews are lexicon-scored from free text and weighted lower.
_SOURCE_WEIGHTS: Dict[str, float] = {
    "stocktwits": 1.0,
    "reddit":     0.7,
    "hackernews": 0.6,
}
# Message count at which a source reaches its full credibility weight. Fewer
# messages scale the weight down linearly so thin samples can't dominate.
_FULL_WEIGHT_AT: int = 10


# ──────────────────────────────────────────────────────────────────────────────
# Shared lexicon scorer — pure logic, reused by every free-text source
# ──────────────────────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
# Web/markup tokens that survive URL stripping and add no thematic signal.
_WEB_NOISE = frozenset({"https", "http", "www", "com", "amp", "href"})


def _score_texts(texts: List[str]) -> Tuple[Optional[float], Dict[str, int]]:
    """
    Lexicon-score a list of short texts (post titles, message bodies).
    Returns (sentiment_score in [-1, 1] or None, token-frequency map for themes).
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
    total = pos + neg
    score = round((pos - neg) / total, 2) if total > 0 else None
    return score, word_freq


@dataclass
class _RawSourceResult:
    """Internal: one source's raw contribution before blending."""
    source:        str
    texts:         List[str]            # free text used for theme extraction
    message_count: int
    native_score:  Optional[float] = None  # explicit-label score (Stocktwits); else None
    error:         Optional[str]   = None


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

        labeled = bull + bear
        native = round((bull - bear) / labeled, 2) if labeled > 0 else None
        return _RawSourceResult(
            source="stocktwits",
            texts=texts,
            message_count=len(messages),
            native_score=native,
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
        return _RawSourceResult(
            source="hackernews",
            texts=texts,
            message_count=len(texts),
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
        )


# ──────────────────────────────────────────────────────────────────────────────
# Multi-source aggregator — blends the three sources into one signal
# ──────────────────────────────────────────────────────────────────────────────

class MultiSourceSentimentAggregator:
    """
    Domain + orchestration: fetches all three sources for a ticker and blends them
    into a single ConsumerSentimentSignal. The blend is a weighted mean of each
    source's score (native where available, else lexicon), weighted by source
    credibility scaled by sample size. Themes are pooled across all sources.
    """

    def __init__(
        self,
        stocktwits: Optional[StocktwitsSentimentFetcher] = None,
        hackernews: Optional[HackerNewsSentimentFetcher] = None,
        reddit:     Optional[RedditSentimentFetcher]     = None,
    ) -> None:
        self._stocktwits = stocktwits or StocktwitsSentimentFetcher()
        self._hackernews = hackernews or HackerNewsSentimentFetcher()
        self._reddit     = reddit     or RedditSentimentFetcher()

    def get_signal(self, ticker: str, company_name: str) -> ConsumerSentimentSignal:
        raws = [
            self._stocktwits.fetch(ticker),
            self._hackernews.fetch(company_name),
            self._reddit.fetch(ticker, company_name),
        ]
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
            score = raw.native_score
            if score is None:
                score, freq = _score_texts(raw.texts)
            else:
                _, freq = _score_texts(raw.texts)  # still pool themes from text

            for tok, n in freq.items():
                pooled_freq[tok] = pooled_freq.get(tok, 0) + n
            total_messages += raw.message_count

            # Sample-scaled credibility weight; only counts if we have a score.
            weight = 0.0
            if score is not None and raw.message_count > 0:
                sample_factor = min(raw.message_count, _FULL_WEIGHT_AT) / _FULL_WEIGHT_AT
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
            ))

        blended: Optional[float] = None
        label:   Optional[str]   = None
        if weight_total > 0:
            blended = round(weighted_sum / weight_total, 2)
            label = "positive" if blended > 0.2 else "negative" if blended < -0.2 else "mixed"

        # Pooled top-5 themes, excluding the ticker/company name tokens.
        name_tokens = set(re.findall(r"[a-z]{3,}", company_name.lower()))
        name_tokens.add(ticker.lower())
        themes = [
            w for w, _ in sorted(pooled_freq.items(), key=lambda x: -x[1])
            if w not in name_tokens
        ][:5]

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
            error=error,
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
        fred_api_key:        str                               = FRED_API_KEY,
        trends_fetcher:      Optional[GoogleTrendsFetcher]     = None,
        trends_processor:    Optional[GoogleTrendsProcessor]   = None,
        fred_fetcher:        Optional[FredApiFetcher]          = None,
        fred_processor:      Optional[FredDataProcessor]       = None,
        cik_resolver:        Optional[SecCikResolver]          = None,
        filing_fetcher:      Optional[SecFilingFetcher]        = None,
        risk_extractor:      Optional[SecRiskFactorExtractor]  = None,
        job_scraper:         Optional[ApifyJobScraper]         = None,
        sec_8k_fetcher:      Optional[Sec8KFetcher]            = None,
        pr_fetcher:          Optional[PressReleaseFetcher]     = None,
        lit_fetcher:         Optional[LitigationFetcher]       = None,
        sentiment_aggregator: Optional[MultiSourceSentimentAggregator] = None,
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

    # ── public API ────────────────────────────────────────────────────────────

    def get_trends_signal(self, ticker: str) -> TrendsSignal:
        keyword = TICKER_KEYWORDS.get(ticker.upper(), ticker)
        df = self._trends_fetcher.fetch_interest_over_time(keyword)
        return self._trends_processor.compute_signal(ticker, keyword, df)

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
