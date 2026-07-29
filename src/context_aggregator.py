"""
context_aggregator.py — LLM Payload Builder
=============================================
Composes FinancialService + AltDataService outputs into a single, minified
JSON context payload optimised for injection into an LLM system prompt.

Output contract:
  {
    "meta":        { target_ticker, schema_version, generated_at },
    "target":      CompanyFinancials (dict),
    "peers":       [ CompanyFinancials (dict), … ],     ← 3 comparables
    "alt_signals": {
        "google_trends":       TrendsSignal (dict),
        "macro_fred":          FredSeries   (dict),
        "sec_risk_snippet":    SecRiskSnippet (dict),
        "job_market":          ApifyJobsResult (dict),
        "consumer_sentiment":  ConsumerSentimentSignal (dict),
        "insider_activity":    InsiderActivitySignal (dict) — trailing-12m Form 4
                               buy/sell aggregate + notable sells (risk signal)
        "earnings_track":      EarningsTrack (dict) — last 8 reported quarters,
                               beat/miss pattern (guidance-credibility proxy)
        "web_research":        WebResearchSignal (dict) — first-hand news/forum
                               scrape; its uniform forum_posts / news_extracts
                               arrays are TOON-encoded into *_toon strings to cut
                               output tokens (the rest of the payload stays JSON)
    },
    "fundamentals_history": FundamentalsHistory (dict) — ≤5 FYs of revenue/EBITDA/
                            NI with approximate year-end EV/Revenue + trailing P/E
                            (feeds the revenue_history / valuation_history charts),
    "data_quality": { flagged_comparables, has_flags, directive }  ← coherence audit
  }

Token economy:
  • json.dumps(…, separators=(',',':')) strips all whitespace → ~30 % smaller.
  • Null fields are preserved so the LLM can infer data-quality gaps.

Architecture:
  ContextAggregator is a pure orchestrator — it delegates all fetching and
  processing to the injected services, keeping this module free of I/O logic.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from financial_service import (
    CompanyFinancials,
    FinancialService,
    SECTOR_TICKERS,
    audit_peer_set,
)
from alt_data_service import (
    AltDataService,
    ApifyJobsResult,
    ConsumerSentimentSignal,
    FredSeries,
    LitigationSignal,
    MassiveNewsSignal,
    MassivePriceMetrics,
    PressReleaseSignal,
    Sec8KSignal,
    SecRiskSnippet,
    TrendsSignal,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Competitor Map
# ──────────────────────────────────────────────────────────────────────────────

# Curated peer overrides: for a target ticker, the 3 closest public-market
# comparables, hand-picked for the original universe(s).
#
# These are OVERRIDES, not the only supported names. A ticker absent from this
# map no longer yields an empty `peers` list — PeerResolver falls back to dynamic
# discovery (Polygon related-companies) so any sector gets live comparables.
# Add a cluster here only when you want to pin a specific, higher-quality peer set
# that overrides the dynamic result (see PeerResolver below).
COMPETITOR_MAP: Dict[str, List[str]] = {
    # ── PropTech & Facilities (original universe) ──
    "CSGP": ["CBRE", "PCOR",  "Z"   ],
    "CBRE": ["CSGP", "HON",   "ABM" ],
    "CARR": ["TT",   "JCI",   "LII" ],
    "TT":   ["CARR", "JCI",   "LII" ],
    "JCI":  ["CARR", "TT",    "HON" ],
    "LII":  ["CARR", "TT",    "JCI" ],
    "ABM":  ["CTAS", "HON",   "JCI" ],
    "CTAS": ["ABM",  "HON",   "ADT" ],
    "ADT":  ["ALLE", "CTAS",  "HON" ],
    "ALLE": ["ADT",  "HON",   "JCI" ],
    "HON":  ["JCI",  "CARR",  "TT"  ],
    "PCOR": ["CSGP", "APPF",  "Z"   ],
    "APPF": ["PCOR", "CSGP",  "Z"   ],
    "Z":    ["CSGP", "APPF",  "PCOR"],
    # ── Semiconductors & AI infrastructure ──
    "NVDA": ["AMD",  "AVGO",  "TSM" ],
    "AMD":  ["NVDA", "AVGO",  "INTC"],
    "AVGO": ["NVDA", "AMD",   "QCOM"],
    "TSM":  ["NVDA", "AVGO",  "INTC"],
    "INTC": ["AMD",  "NVDA",  "TSM" ],
    "MU":   ["NVDA", "AMD",   "TSM" ],
    "QCOM": ["AVGO", "NVDA",  "AMD" ],
    # ── Hyperscalers / mega-cap tech ──
    "META": ["GOOGL","MSFT",  "AMZN"],
}

# The original CRE-linked universe always reads through the commercial-construction
# series, regardless of how yfinance classifies a given name (HON is "Industrials",
# CSGP is "Real Estate", etc., but all are CRE-demand-linked). This preserves the
# project's founding behaviour exactly while the sector map generalises everything else.
_CRE_LINKED_TICKERS: set = set(SECTOR_TICKERS)

# Commercial-construction series + label, retained for the CRE-linked cohort.
_FRED_SERIES_ID:    str = "TLNRESCONS"
_FRED_SERIES_LABEL: str = "Commercial Construction Spending (TLNRESCONS, $MM, SA)"

# Broad fallback when an issuer's sector has no specific demand proxy configured.
_DEFAULT_FRED: Tuple[str, str] = ("GDPC1", "U.S. Real GDP (GDPC1, chained $B, SAAR)")

# yfinance sector → (FRED series id, label). Each series is a genuine
# demand / price / rate driver for that sector, so the memo can argue a real
# transmission mechanism instead of carrying a generic backdrop. Sector strings
# match yfinance's GICS-style `sector` field.
SECTOR_MACRO_MAP: Dict[str, Tuple[str, str]] = {
    "Real Estate":            ("TLNRESCONS", "Nonresidential Construction Spending (TLNRESCONS, $MM, SA)"),
    "Technology":             ("INDPRO",     "Industrial Production Index (INDPRO, 2017=100, SA)"),
    "Industrials":            ("DGORDER",    "Durable Goods New Orders (DGORDER, $MM, SA)"),
    "Energy":                 ("DCOILWTICO", "Crude Oil WTI Spot Price (DCOILWTICO, $/bbl)"),
    "Basic Materials":        ("INDPRO",     "Industrial Production Index (INDPRO, 2017=100, SA)"),
    "Utilities":              ("INDPRO",     "Industrial Production Index (INDPRO, 2017=100, SA)"),
    "Financial Services":     ("FEDFUNDS",   "Effective Federal Funds Rate (FEDFUNDS, %)"),
    "Healthcare":             ("CPIMEDSL",   "CPI: Medical Care Services (CPIMEDSL, index, SA)"),
    "Consumer Cyclical":      ("PCEC96",     "Real Personal Consumption Expenditures (PCEC96, chained $B, SA)"),
    "Consumer Defensive":     ("PCEC96",     "Real Personal Consumption Expenditures (PCEC96, chained $B, SA)"),
    "Communication Services": ("PCEC96",     "Real Personal Consumption Expenditures (PCEC96, chained $B, SA)"),
}

_SCHEMA_VERSION:  str = "1.10"
_OUTPUT_DIR:      Path = Path("output") / "context"

# How many comparables to carry when peers are discovered dynamically.
_MAX_PEERS: int = 3


def _macro_for_ticker(ticker: str, sector: Optional[str] = None) -> Dict[str, str]:
    """
    Pick the FRED series + relevance framing for *ticker*, given its sector.

    Resolution order:
      1. The original CRE-linked universe always gets the commercial-construction
         series (preserves founding behaviour).
      2. A known sector maps to its sector-specific demand/price/rate driver,
         tagged `high` relevance with a stated transmission mechanism.
      3. Anything else falls back to broad real GDP, tagged `low` relevance so the
         memo treats it as backdrop only and never invents a correlation.
    """
    if ticker.upper() in _CRE_LINKED_TICKERS:
        return {
            "series_id": _FRED_SERIES_ID,
            "series_label": _FRED_SERIES_LABEL,
            "relevance": "high",
            "relevance_note": (
                "Commercial construction spend is a direct demand proxy for this "
                "PropTech/Facilities issuer."
            ),
        }
    if sector and sector in SECTOR_MACRO_MAP:
        series_id, label = SECTOR_MACRO_MAP[sector]
        return {
            "series_id": series_id,
            "series_label": label,
            "relevance": "high",
            "relevance_note": (
                f"{label} is a sector-level demand/price driver for {sector} issuers; "
                "treat it as the macro read-through for this name and state the "
                "transmission mechanism explicitly."
            ),
        }
    series_id, label = _DEFAULT_FRED
    sector_clause = f" (sector: {sector})" if sector else ""
    return {
        "series_id": series_id,
        "series_label": label,
        "relevance": "low",
        "relevance_note": (
            f"No sector-specific demand proxy is configured for this issuer{sector_clause}; "
            "real GDP is carried as a generic macro backdrop only. Do not assert a demand "
            "correlation unless a transmission mechanism can be stated, otherwise omit it."
        ),
    }


def _macro_relevance(ticker: str, sector: Optional[str] = None) -> Dict[str, str]:
    """Back-compat shim: the {relevance, relevance_note} subset of _macro_for_ticker."""
    macro = _macro_for_ticker(ticker, sector)
    return {"relevance": macro["relevance"], "relevance_note": macro["relevance_note"]}


# ──────────────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ──────────────────────────────────────────────────────────────────────────────

def _to_dict(obj: Any) -> Dict:
    """Convert dataclass instances to plain dicts for JSON serialisation."""
    return dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _error_node(ticker: str, exc: Exception) -> Dict:
    return {"ticker": ticker, "error": str(exc)}


def _toon_encode(rows: List[Dict]) -> str:
    """
    Encode a uniform array of row dicts as a compact TOON string (indentation +
    CSV-style tabular layout → ~40–60% fewer tokens than nested JSON for this shape).
    Tries the maintained `python-toon` / `toon_py` packages; falls back to minified
    JSON if neither is installed so the payload is always well-formed.
    """
    if not rows:
        return ""
    compact_json = json.dumps(rows, separators=(",", ":"), default=str)
    try:
        try:
            from toon import encode as _encode          # python-toon
        except ImportError:
            from toon_py import encode as _encode        # toon-py
        toon = _encode(rows)
    except Exception as exc:
        logger.warning("TOON encode failed (%s); falling back to JSON", exc)
        return compact_json
    # TOON's tabular header only pays off on dense, flat, uniform arrays; on tiny,
    # sparse, or nested rows it can be larger than JSON. Never emit the bigger form —
    # the whole point is fewer tokens, so keep whichever is smaller.
    return toon if len(toon) <= len(compact_json) else compact_json


# Keys that are diagnostic or derivable and never inform the memo: `items_raw`
# duplicates `items_labeled` on 8-K events; `from_cache` is a scrape-cache flag.
# The producing dataclasses keep these fields — they are dropped only at this
# LLM boundary, so the ingest pipeline and caches are unaffected.
_LLM_DROP_KEYS = frozenset({"items_raw", "from_cache"})

# Attribution-only query params; stripping them keeps every URL resolvable.
_TRACKING_PARAM_NAMES = frozenset({"source", "fbclid", "gclid", "cmpid", "mc_cid", "mc_eid"})


def _clean_url(url: str) -> str:
    """Strip tracking query params (utm_*, source, click IDs) from *url*."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _TRACKING_PARAM_NAMES and not k.startswith("utm_")
    ]
    return urlunsplit(parts._replace(query=urlencode(kept)))


def _prune_for_llm(obj: Any) -> Any:
    """
    Final pass before serialisation: drop content that costs tokens but cannot
    inform the memo. Removes `_LLM_DROP_KEYS`, None / empty-string leaves (an
    absent key reads the same as null to the model), tracking params from URL
    fields, and casts integral floats to ints. Meaningful falsy values
    (False, 0, [], {}) are kept — "no flags" is information, a null is not.
    """
    if isinstance(obj, dict):
        out: Dict = {}
        for k, v in obj.items():
            if k in _LLM_DROP_KEYS:
                continue
            v = _prune_for_llm(v)
            if v is None or v == "":
                continue
            if isinstance(v, str) and k.endswith("url"):
                v = _clean_url(v)
            out[k] = v
        return out
    if isinstance(obj, list):
        return [_prune_for_llm(v) for v in obj]
    if isinstance(obj, float) and obj.is_integer() and abs(obj) < 1e15:
        return int(obj)
    return obj


# ──────────────────────────────────────────────────────────────────────────────
# Context Aggregator
# ──────────────────────────────────────────────────────────────────────────────

class ContextAggregator:
    """
    Orchestrates FinancialService and AltDataService to build a single
    token-efficient JSON payload for LLM equity research memo generation.

    All collaborators are constructor-injected → easy to swap or mock in tests.
    """

    def __init__(
        self,
        financial_service: Optional[FinancialService] = None,
        alt_data_service:  Optional[AltDataService]   = None,
        competitor_map:    Dict[str, List[str]]        = COMPETITOR_MAP,
        output_dir:        Path                        = _OUTPUT_DIR,
    ) -> None:
        self._fin         = financial_service or FinancialService()
        self._alt         = alt_data_service  or AltDataService()
        self._competitors = competitor_map
        self._output_dir  = output_dir

    # ── public API ────────────────────────────────────────────────────────────

    def build_minified_context(self, target_ticker: str) -> str:
        """
        Full pipeline for one ticker:
          1. Target company financials (incl. sector/industry)
          2. Up to three peer comparables (curated override or dynamic discovery)
          3. Google Trends velocity signal
          4. Sector-appropriate FRED macro series (CRE / industrial / energy / …)
          5. SEC 10-K Item 1A risk-factor snippet
          6. Apify job-market signal (stub)
          7. Massive/Polygon: recent news with per-ticker sentiment + reasoning
          8. Massive/Polygon: 52W price metrics (high/low, 1Y/30D return)

        Returns the minified JSON string and writes it to
        `context_{target_ticker}.json` in *output_dir*.
        """
        ticker = target_ticker.upper()
        logger.info("═══ Building context for %s ═══", ticker)

        payload = _prune_for_llm(self._assemble_payload(ticker))
        minified = json.dumps(payload, separators=(",", ":"), default=str)

        output_path = self._output_dir / f"context_{ticker}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(minified, encoding="utf-8")
        logger.info(
            "Context saved → %s  (%d chars, %d KB)",
            output_path.resolve(),
            len(minified),
            len(minified.encode()) // 1024,
        )
        return minified

    # ── private pipeline stages ───────────────────────────────────────────────

    def _assemble_payload(self, ticker: str) -> Dict:
        # Fetch target + peers as objects first so the cross-sectional data-quality
        # auditor can see the whole cohort, then serialise the (now-annotated)
        # objects. A fetch failure yields (None, error_node) and is excluded from
        # the audit but still rendered in its slot.
        target_obj, target_err = self._fetch_company_obj(ticker)

        # Classification drives both peer discovery and macro selection; read it off
        # the target once fetched (None-safe — peers/macro degrade gracefully).
        sector       = getattr(target_obj, "sector", None) if target_obj is not None else None
        company_name = getattr(target_obj, "name", None) if target_obj is not None else None

        peer_tickers = self._resolve_peers(ticker)
        peer_pairs   = [self._fetch_company_obj(p) for p in peer_tickers]

        cohort = [c for c in [target_obj, *(o for o, _ in peer_pairs)] if c is not None]
        quality_summary = audit_peer_set(cohort) if cohort else {}

        target_node = _to_dict(target_obj) if target_obj is not None else target_err
        peer_nodes = [
            _to_dict(obj) if obj is not None else err for obj, err in peer_pairs
        ]

        return {
            "meta":                 self._build_meta(ticker, sector),
            "target":               target_node,
            "peers":                peer_nodes,
            "alt_signals":          self._fetch_alt_signals(ticker, sector, company_name),
            "fundamentals_history": self._fetch_fundamentals_history(ticker),
            "data_quality":         self._build_data_quality(quality_summary),
        }

    def _resolve_peers(self, ticker: str) -> List[str]:
        """
        Resolve up to `_MAX_PEERS` comparables for *ticker*.

        Order: curated COMPETITOR_MAP override → dynamic discovery via the alt-data
        service (Polygon related-companies) → empty list. Dynamic discovery is what
        lets the engine cover every sector instead of only the curated universe; the
        curated map remains an override for hand-tuned, higher-quality peer sets.
        """
        curated = self._competitors.get(ticker)
        if curated:
            return list(curated)
        try:
            dynamic = self._alt.get_related_tickers(ticker)
        except Exception as exc:
            logger.error("Dynamic peer discovery failed for %s: %s", ticker, exc)
            dynamic = []
        if dynamic:
            logger.info("Discovered %d dynamic peers for %s: %s",
                        min(len(dynamic), _MAX_PEERS), ticker, dynamic[:_MAX_PEERS])
        return dynamic[:_MAX_PEERS]

    def _fetch_company_obj(self, ticker: str):
        """Fetch one company's financials as an object, or (None, error_node)."""
        try:
            return self._get_company_financials_cached(ticker), None
        except Exception as exc:
            logger.error("Financials failed for %s: %s", ticker, exc)
            return None, _error_node(ticker, exc)

    def _build_data_quality(self, summary: Dict[str, List[str]]) -> Dict:
        """
        Machine-readable summary of every coherence flag raised over the cohort,
        plus a directive instructing the memo writer how to treat flagged figures.
        The writer is told to treat the payload as ground truth, so the guardrail
        must travel *with* the data — flags here are honored by SKILL.md rigor rules.
        """
        return {
            "flagged_comparables": summary,
            "has_flags": bool(summary),
            "directive": (
                "Each flag marks a figure that failed an automated coherence check. "
                "Do NOT present a flagged comparable's affected ratio as fact: exclude "
                "it from any peer median or 'cheap/expensive vs peers' argument, and "
                "either omit it or footnote it as suspect with the stated reason. "
                "'currency_mismatch' — the issuer reports in a currency other than its "
                "trading currency (e.g. an ADR); the yfinance ratio is not certifiable, "
                "so source that comp's multiples externally per the peer-comp rigor "
                "rule. 'peer_outlier'/'implausible' — verify against the primary filing "
                "before citing; it may be real-but-extreme or a data artifact."
            ) if summary else (
                "No data-quality flags were raised for this cohort; comparables passed "
                "the currency-coherence and cross-sectional plausibility checks."
            ),
        }

    def _build_meta(self, ticker: str, sector: Optional[str] = None) -> Dict:
        return {
            "target_ticker":   ticker,
            "schema_version":  _SCHEMA_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fred_series":     _macro_for_ticker(ticker, sector)["series_id"],
        }

    def _get_company_financials_cached(self, ticker: str):
        if not hasattr(self, "_fin_cache"):
            self._fin_cache: Dict = {}
        if ticker not in self._fin_cache:
            self._fin_cache[ticker] = self._fin.get_company_financials(ticker)
        return self._fin_cache[ticker]

    def _fetch_alt_signals(
        self, ticker: str, sector: Optional[str] = None, company_name: Optional[str] = None
    ) -> Dict:
        return {
            "google_trends":        self._fetch_trends(ticker, company_name),
            "macro_fred":           self._fetch_fred(ticker, sector),
            "sec_risk_snippet":     self._fetch_sec(ticker),
            "job_market":           self._fetch_jobs(ticker),
            "sec_8k_events":        self._fetch_8k_events(ticker),
            "litigation":           self._fetch_litigation(ticker),
            "consumer_sentiment":   self._fetch_consumer_sentiment(ticker),
            "insider_activity":     self._fetch_insider_activity(ticker),
            "earnings_track":       self._fetch_earnings_track(ticker),
            "massive_news":         self._fetch_massive_news(ticker),
            "massive_price_metrics": self._fetch_massive_price_metrics(ticker),
            "web_research":         self._fetch_web_research(ticker, company_name),
        }

    def _fetch_trends(self, ticker: str, company_name: Optional[str] = None) -> Dict:
        try:
            return _to_dict(self._alt.get_trends_signal(ticker, company_name))
        except Exception as exc:
            logger.error("Trends signal failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_fred(self, ticker: str, sector: Optional[str] = None) -> Dict:
        macro = _macro_for_ticker(ticker, sector)
        series_id, series_label = macro["series_id"], macro["series_label"]
        relevance = {"relevance": macro["relevance"], "relevance_note": macro["relevance_note"]}
        try:
            series = self._alt.get_fred_macro(series_id, series_label)
            d = _to_dict(series)
            if d.get("latest_value") is None:
                return {"series_id": series_id, "available": False,
                        "reason": "no_data", **relevance}
            d.update(relevance)
            return d
        except Exception as exc:
            logger.error("FRED fetch failed for %s (%s): %s", ticker, series_id, exc)
            return {"series_id": series_id, "available": False,
                    "reason": str(exc), **relevance}

    def _fetch_sec(self, ticker: str) -> Dict:
        try:
            return _to_dict(self._alt.get_sec_risk_snippet(ticker))
        except Exception as exc:
            logger.error("SEC fetch failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_8k_events(self, ticker: str) -> Dict:
        try:
            return _to_dict(self._alt.get_sec_8k_events(ticker))
        except Exception as exc:
            logger.error("8-K events fetch failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_litigation(self, ticker: str) -> Dict:
        try:
            raw_target = self._get_company_financials_cached(ticker)
            company_name = raw_target.name or ticker
        except Exception:
            company_name = ticker
        try:
            return _to_dict(self._alt.get_litigation_signal(company_name, ticker=ticker))
        except Exception as exc:
            logger.error("Litigation fetch failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_consumer_sentiment(self, ticker: str) -> Dict:
        try:
            raw_target = self._get_company_financials_cached(ticker)
            company_name = raw_target.name or ticker
        except Exception:
            company_name = ticker
        try:
            return _to_dict(self._alt.get_consumer_sentiment(ticker, company_name))
        except Exception as exc:
            logger.error("Consumer sentiment failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_insider_activity(self, ticker: str) -> Dict:
        try:
            return _to_dict(self._fin.get_insider_activity(ticker))
        except Exception as exc:
            logger.error("Insider activity fetch failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_earnings_track(self, ticker: str) -> Dict:
        try:
            return _to_dict(self._fin.get_earnings_track(ticker))
        except Exception as exc:
            logger.error("Earnings track fetch failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_fundamentals_history(self, ticker: str) -> Dict:
        try:
            return _to_dict(self._fin.get_fundamentals_history(ticker))
        except Exception as exc:
            logger.error("Fundamentals history fetch failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_massive_news(self, ticker: str) -> Dict:
        try:
            return _to_dict(self._alt.get_massive_news(ticker))
        except Exception as exc:
            logger.error("Massive news fetch failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_web_research(self, ticker: str, company_name: Optional[str] = None) -> Dict:
        try:
            signal = self._alt.get_web_research(ticker, company_name or ticker)
            d = _to_dict(signal)
            # Compact the two uniform arrays into TOON strings; drop the raw arrays
            # so the node carries each row exactly once (TOON form only).
            d["forum_posts_toon"]   = _toon_encode(d.pop("forum_posts", []))
            d["news_extracts_toon"] = _toon_encode(d.pop("news_extracts", []))
            return d
        except Exception as exc:
            logger.error("Web research failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_massive_price_metrics(self, ticker: str) -> Dict:
        try:
            return _to_dict(self._alt.get_massive_price_metrics(ticker))
        except Exception as exc:
            logger.error("Massive price metrics failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_jobs(self, ticker: str) -> Dict:
        # Company name is taken from the target financials dict when available
        try:
            raw_target = self._get_company_financials_cached(ticker)
            company_name = raw_target.name or ticker
        except Exception:
            company_name = ticker

        try:
            result = _to_dict(self._alt.get_job_market_signal(company_name))
            if result.get("is_stub"):
                return {"company": company_name, "available": False}
            return result
        except Exception as exc:
            logger.error("Job market signal failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)


# ──────────────────────────────────────────────────────────────────────────────
# Batch convenience helper
# ──────────────────────────────────────────────────────────────────────────────

def build_all_contexts(
    tickers:   List[str]           = SECTOR_TICKERS,
    aggregator: Optional[ContextAggregator] = None,
) -> Dict[str, str]:
    """
    Generate context files for every ticker in *tickers*.
    Returns a dict of {ticker: minified_json_string}.
    """
    agg = aggregator or ContextAggregator()
    return {t: agg.build_minified_context(t) for t in tickers}


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if not args:
        print("Usage: python context_aggregator.py <TICKER|ALL>")
        print(f"       Valid tickers: {', '.join(SECTOR_TICKERS)}")
        sys.exit(1)

    target = args[0].upper()
    agg    = ContextAggregator()

    if target == "ALL":
        results = build_all_contexts(aggregator=agg)
        print(f"\nGenerated {len(results)} context files.")
    else:
        if target not in COMPETITOR_MAP:
            print(f"Note: '{target}' has no curated peer override — peers will be discovered dynamically.")
        result = agg.build_minified_context(target)
        # Print a human-readable preview (pretty-print the first few keys)
        preview = json.loads(result)
        print(json.dumps({
            "meta":   preview["meta"],
            "target": {k: v for k, v in list(preview["target"].items())[:5]},
            "peers_count": len(preview.get("peers", [])),
        }, indent=2))
