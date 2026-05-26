"""
alt_data_service.py — Macro & Alternative Signal Engine
=========================================================
Sources:
  1. Google Trends (pytrends)  — search-interest velocity as demand proxy
  2. FRED API (requests)       — commercial construction macro indicator
  3. SEC EDGAR API (requests)  — most-recent 10-K + Item 1A risk snippet
  4. Apify (stub)              — job-listing scraper (activate with API key)

Architecture (Clean Architecture + SOLID):
  Each data source has a dedicated Fetcher (I/O) and Processor (pure logic).
  AltDataService is the façade that wires them together.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

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

    def _extract_snippet(self, text: str) -> Optional[str]:
        # Iterate all matches: the first hit is often a TOC entry ("Item 1A...12"),
        # so skip any match whose extracted body is shorter than 100 chars.
        for match in self._ITEM_1A_RE.finditer(text):
            body = text[match.end(): match.end() + _RISK_SNIPPET_CHARS * 3]
            next_item = self._ITEM_NEXT_RE.search(body)
            if next_item:
                body = body[: next_item.start()]
            snippet = re.sub(r"\s+", " ", body).strip()[:_RISK_SNIPPET_CHARS]
            if len(snippet) >= 100:
                return snippet
        logger.debug("Item 1A pattern not found in document")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Apify Stub — activate by injecting APIFY_API_KEY
# ──────────────────────────────────────────────────────────────────────────────

class ApifyJobScraper:
    """
    STUB implementation for Apify-powered job-listing scraper.

    To activate:
      1. Register at https://apify.com and create an API token.
      2. Set env var APIFY_API_KEY=<your_token>.
      3. Choose an actor (e.g. "apify/indeed-scraper" or a LinkedIn Jobs actor).
         Set _ACTOR_ID below to the actor's full ID.
      4. Replace the body of get_open_engineering_roles() with the live call
         pattern shown in the docstring.

    Apify REST docs: https://docs.apify.com/api/v2
    """

    _APIFY_API_KEY: str = os.getenv("APIFY_API_KEY", "YOUR_APIFY_API_KEY_HERE")
    _ACTOR_ID:      str = "REPLACE_WITH_ACTOR_ID"      # e.g. "nFJndFXA5zjCTuudP"
    _BASE_URL:      str = "https://api.apify.com/v2/acts/{actor_id}/runs"

    def get_open_engineering_roles(self, company_name: str) -> ApifyJobsResult:
        """
        STUB — returns zeroed mock data.

        Live call pattern (replace this body):
        ─────────────────────────────────────
        run_url  = self._BASE_URL.format(actor_id=self._ACTOR_ID)
        headers  = {"Authorization": f"Bearer {self._APIFY_API_KEY}"}
        payload  = {"company": company_name, "keywords": ["engineer", "software"]}

        run_resp = requests.post(run_url, json=payload, headers=headers)
        run_id   = run_resp.json()["data"]["id"]

        # Poll until the run finishes
        status_url = f"https://api.apify.com/v2/acts/{self._ACTOR_ID}/runs/{run_id}"
        while True:
            status = requests.get(status_url, headers=headers).json()["data"]["status"]
            if status == "SUCCEEDED":
                break
            time.sleep(5)

        items_url = f"{status_url}/dataset/items"
        items     = requests.get(items_url, headers=headers).json()
        return ApifyJobsResult(company_name=company_name,
                               total_open_roles=len(items),
                               engineering_roles=items,
                               is_stub=False)
        """
        logger.info("[STUB] Apify job scraper called for '%s' — no live data", company_name)
        return ApifyJobsResult(
            company_name=company_name,
            total_open_roles=0,
            engineering_roles=[],
            is_stub=True,
        )

    def get_headcount_proxy(self, company_name: str) -> Dict:
        """
        STUB: LinkedIn / Glassdoor employee count via an Apify LinkedIn actor.
        Useful as a growth/contraction signal alongside job postings.
        Replace body with live Apify call once actor ID is configured.
        """
        logger.info("[STUB] Headcount proxy called for '%s'", company_name)
        return {"company": company_name, "employee_estimate": None, "is_stub": True}


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
        fred_api_key:      str                           = FRED_API_KEY,
        trends_fetcher:    Optional[GoogleTrendsFetcher] = None,
        trends_processor:  Optional[GoogleTrendsProcessor] = None,
        fred_fetcher:      Optional[FredApiFetcher]      = None,
        fred_processor:    Optional[FredDataProcessor]   = None,
        cik_resolver:      Optional[SecCikResolver]      = None,
        filing_fetcher:    Optional[SecFilingFetcher]    = None,
        risk_extractor:    Optional[SecRiskFactorExtractor] = None,
        job_scraper:       Optional[ApifyJobScraper]     = None,
    ) -> None:
        self._trends_fetcher   = trends_fetcher   or GoogleTrendsFetcher()
        self._trends_processor = trends_processor or GoogleTrendsProcessor()
        self._fred_fetcher     = fred_fetcher     or FredApiFetcher(api_key=fred_api_key)
        self._fred_processor   = fred_processor   or FredDataProcessor()
        self._cik_resolver     = cik_resolver     or SecCikResolver()
        self._filing_fetcher   = filing_fetcher   or SecFilingFetcher()
        self._risk_extractor   = risk_extractor   or SecRiskFactorExtractor()
        self._job_scraper      = job_scraper      or ApifyJobScraper()

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
