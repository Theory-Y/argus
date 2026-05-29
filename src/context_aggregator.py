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
        "consumer_sentiment":  ConsumerSentimentSignal (dict)
    }
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
from typing import Any, Dict, List, Optional

from financial_service import (
    CompanyFinancials,
    FinancialService,
    SECTOR_TICKERS,
)
from alt_data_service import (
    AltDataService,
    ApifyJobsResult,
    ConsumerSentimentSignal,
    FredSeries,
    LitigationSignal,
    PressReleaseSignal,
    Sec8KSignal,
    SecRiskSnippet,
    TrendsSignal,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Competitor Map
# ──────────────────────────────────────────────────────────────────────────────

# For each target ticker, list the 3 closest public-market comparables
# drawn from the same sector universe where possible.
#
# NOTE: A ticker absent from this map yields an empty `peers` list. That is a
# coverage gap, not "no comparables exist" — the memo writer must source comps
# externally in that case rather than declaring relative valuation impossible
# (see the peer-comparison rule in theory-y-memo/SKILL.md). Add new clusters
# here so the gap closes at the source.
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

# CRE-linked universe for which the default FRED macro series (commercial
# construction spend) is a genuine demand proxy. Outside this set the series is
# carried only as a generic backdrop and is flagged low-relevance so the memo
# does not manufacture a spurious correlation (see macro-relevance rule in SKILL.md).
_CRE_LINKED_TICKERS: set = set(SECTOR_TICKERS)

# FRED macro indicator used as the sector-wide CRE backdrop
_FRED_SERIES_ID:  str = "TLNRESCONS"
_FRED_SERIES_LABEL: str = "Commercial Construction Spending (TLNRESCONS, $MM, SA)"
_SCHEMA_VERSION:  str = "1.5"
_OUTPUT_DIR:      Path = Path("output") / "context"


def _macro_relevance(ticker: str) -> Dict[str, str]:
    """
    Classify how directly the default FRED series reads through to *ticker*.

    The pipeline was built for a CRE-linked PropTech/Facilities universe, so the
    commercial-construction series is only a real demand driver for that cohort.
    For any other issuer we say so explicitly, so the memo treats the datapoint
    as backdrop (or omits it) instead of inventing a correlation.
    """
    if ticker.upper() in _CRE_LINKED_TICKERS:
        return {
            "relevance": "high",
            "relevance_note": (
                "Commercial construction spend is a direct demand proxy for this "
                "PropTech/Facilities issuer."
            ),
        }
    return {
        "relevance": "low",
        "relevance_note": (
            "TLNRESCONS is a commercial-real-estate proxy carried as the pipeline's "
            "sector default; it has limited direct read-through to this issuer. Treat "
            "as macro backdrop only — do not assert a demand correlation unless a "
            "transmission mechanism can be stated, otherwise omit it."
        ),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ──────────────────────────────────────────────────────────────────────────────

def _to_dict(obj: Any) -> Dict:
    """Convert dataclass instances to plain dicts for JSON serialisation."""
    return dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _error_node(ticker: str, exc: Exception) -> Dict:
    return {"ticker": ticker, "error": str(exc)}


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
          1. Target company financials
          2. Three peer comparables' financials
          3. Google Trends velocity signal
          4. FRED commercial construction macro
          5. SEC 10-K Item 1A risk-factor snippet
          6. Apify job-market signal (stub)

        Returns the minified JSON string and writes it to
        `context_{target_ticker}.json` in *output_dir*.
        """
        ticker = target_ticker.upper()
        logger.info("═══ Building context for %s ═══", ticker)

        payload = self._assemble_payload(ticker)
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
        return {
            "meta":        self._build_meta(ticker),
            "target":      self._fetch_target(ticker),
            "peers":       self._fetch_peers(ticker),
            "alt_signals": self._fetch_alt_signals(ticker),
        }

    def _build_meta(self, ticker: str) -> Dict:
        return {
            "target_ticker":   ticker,
            "schema_version":  _SCHEMA_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fred_series":     _FRED_SERIES_ID,
        }

    def _get_company_financials_cached(self, ticker: str):
        if not hasattr(self, "_fin_cache"):
            self._fin_cache: Dict = {}
        if ticker not in self._fin_cache:
            self._fin_cache[ticker] = self._fin.get_company_financials(ticker)
        return self._fin_cache[ticker]

    def _fetch_target(self, ticker: str) -> Dict:
        try:
            return _to_dict(self._get_company_financials_cached(ticker))
        except Exception as exc:
            logger.error("Target financials failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_peers(self, ticker: str) -> List[Dict]:
        peers = self._competitors.get(ticker, [])
        results: List[Dict] = []
        for peer in peers:
            try:
                results.append(_to_dict(self._fin.get_company_financials(peer)))
            except Exception as exc:
                logger.error("Peer financials failed for %s: %s", peer, exc)
                results.append(_error_node(peer, exc))
        return results

    def _fetch_alt_signals(self, ticker: str) -> Dict:
        return {
            "google_trends":      self._fetch_trends(ticker),
            "macro_fred":         self._fetch_fred(ticker),
            "sec_risk_snippet":   self._fetch_sec(ticker),
            "job_market":         self._fetch_jobs(ticker),
            "sec_8k_events":      self._fetch_8k_events(ticker),
            "litigation":         self._fetch_litigation(ticker),
            "consumer_sentiment": self._fetch_consumer_sentiment(ticker),
        }

    def _fetch_trends(self, ticker: str) -> Dict:
        try:
            return _to_dict(self._alt.get_trends_signal(ticker))
        except Exception as exc:
            logger.error("Trends signal failed for %s: %s", ticker, exc)
            return _error_node(ticker, exc)

    def _fetch_fred(self, ticker: str) -> Dict:
        relevance = _macro_relevance(ticker)
        try:
            series = self._alt.get_fred_macro(_FRED_SERIES_ID, _FRED_SERIES_LABEL)
            d = _to_dict(series)
            if d.get("latest_value") is None:
                return {"series_id": _FRED_SERIES_ID, "available": False,
                        "reason": "no_data", **relevance}
            d.update(relevance)
            return d
        except Exception as exc:
            logger.error("FRED fetch failed: %s", exc)
            return {"series_id": _FRED_SERIES_ID, "available": False,
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
            print(f"Warning: '{target}' has no competitor mapping — peer section will be empty.")
        result = agg.build_minified_context(target)
        # Print a human-readable preview (pretty-print the first few keys)
        preview = json.loads(result)
        print(json.dumps({
            "meta":   preview["meta"],
            "target": {k: v for k, v in list(preview["target"].items())[:5]},
            "peers_count": len(preview.get("peers", [])),
        }, indent=2))
