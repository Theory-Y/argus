"""
test_all.py — Unit tests for all pure-logic components across the project.
No external API calls are made; all I/O collaborators are injected as mocks.
"""
import sys
import os
import json
import unittest
import pandas as pd
from dataclasses import asdict
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# ─── financial_service ────────────────────────────────────────────────────────

from financial_service import (
    CompanyFinancials,
    FinancialDataTransformer,
    FinancialDataFetcher,
    FinancialExporter,
    FinancialService,
    NM,
    SECTOR_TICKERS,
)


class TestFinancialDataTransformer(unittest.TestCase):

    def setUp(self):
        self.tx = FinancialDataTransformer()

    def test_full_valid_payload(self):
        raw = {
            "symbol": "PCOR",
            "longName": "Procore Technologies Inc",
            "marketCap": 10_000_000_000,
            "enterpriseValue": 9_500_000_000,
            "totalRevenue": 1_000_000_000,
            "ebitda": 100_000_000,
            "forwardPE": 40.5,
            "revenueGrowth": 0.18,
        }
        r = self.tx.transform("PCOR", raw)
        self.assertEqual(r.ticker, "PCOR")
        self.assertEqual(r.name, "Procore Technologies Inc")
        self.assertAlmostEqual(r.market_cap_mm, 10_000.0)
        self.assertAlmostEqual(r.enterprise_value_mm, 9_500.0)
        self.assertAlmostEqual(r.trailing_revenue_mm, 1_000.0)
        self.assertAlmostEqual(r.trailing_ebitda_mm, 100.0)
        self.assertAlmostEqual(r.forward_pe, 40.5)
        self.assertAlmostEqual(r.yoy_revenue_growth_pct, 18.0)
        self.assertEqual(r.ev_revenue, 9.5)
        self.assertEqual(r.ev_ebitda, 95.0)

    def test_empty_payload_returns_nm_ratios(self):
        r = self.tx.transform("PCOR", {})
        self.assertEqual(r.ticker, "PCOR")
        self.assertEqual(r.name, "PCOR")
        self.assertIsNone(r.market_cap_mm)
        self.assertEqual(r.ev_revenue, NM)
        self.assertEqual(r.ev_ebitda, NM)

    def test_negative_ebitda_gives_nm_ev_ebitda(self):
        raw = {
            "enterpriseValue": 5_000_000_000,
            "totalRevenue": 500_000_000,
            "ebitda": -50_000_000,
        }
        r = self.tx.transform("X", raw)
        self.assertEqual(r.ev_ebitda, NM)
        self.assertNotEqual(r.ev_revenue, NM)  # ev_revenue is fine with negative denom

    def test_zero_revenue_gives_nm_ev_revenue(self):
        raw = {"enterpriseValue": 1_000_000_000, "totalRevenue": 0}
        r = self.tx.transform("X", raw)
        self.assertEqual(r.ev_revenue, NM)

    def test_negative_forward_pe_returns_none(self):
        raw = {"forwardPE": -5.0}
        r = self.tx.transform("X", raw)
        self.assertIsNone(r.forward_pe)

    def test_fallback_name_to_shortname(self):
        raw = {"shortName": "Procore"}
        r = self.tx.transform("PCOR", raw)
        self.assertEqual(r.name, "Procore")

    def test_to_mm_non_numeric_returns_none(self):
        r = self.tx.transform("X", {"marketCap": "n/a"})
        self.assertIsNone(r.market_cap_mm)

    def test_revenue_growth_decimal_to_pct(self):
        raw = {"revenueGrowth": 0.15}
        r = self.tx.transform("X", raw)
        self.assertAlmostEqual(r.yoy_revenue_growth_pct, 15.0)


class TestFinancialService(unittest.TestCase):

    def test_get_company_financials_uses_injected_fetcher(self):
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_ticker_info.return_value = {
            "symbol": "PCOR",
            "longName": "Procore Technologies Inc",
            "marketCap": 10_000_000_000,
            "enterpriseValue": 9_500_000_000,
            "totalRevenue": 1_000_000_000,
            "ebitda": 100_000_000,
        }
        svc = FinancialService(fetcher=mock_fetcher)
        result = svc.get_company_financials("PCOR")
        self.assertEqual(result.ticker, "PCOR")
        mock_fetcher.fetch_ticker_info.assert_called_once_with("PCOR")

    def test_exporter_to_dataframe_column_count(self):
        sample = CompanyFinancials(
            ticker="PCOR", name="Procore", market_cap_mm=10000.0,
            enterprise_value_mm=9500.0, trailing_revenue_mm=1000.0,
            trailing_ebitda_mm=100.0, forward_pe=40.0,
            yoy_revenue_growth_pct=18.0, ev_revenue=9.5, ev_ebitda=95.0,
        )
        exporter = FinancialExporter()
        df = exporter.to_dataframe([sample])
        self.assertEqual(len(df.columns), 10)
        self.assertEqual(len(df), 1)
        self.assertIn("Ticker", df.columns)
        self.assertIn("EV / EBITDA", df.columns)


# ─── alt_data_service ─────────────────────────────────────────────────────────

from alt_data_service import (
    GoogleTrendsProcessor,
    FredDataProcessor,
    SecRiskFactorExtractor,
    ApifyJobScraper,
    TrendsSignal,
    FredSeries,
    MultiSourceSentimentAggregator,
    _RawSourceResult,
    _score_texts,
    normalize_company_name,
)


class TestGoogleTrendsProcessor(unittest.TestCase):

    def setUp(self):
        self.proc = GoogleTrendsProcessor()

    def _make_series(self, values):
        return pd.Series(values, dtype=float)

    def test_velocity_positive_trend(self):
        # 8 values: first four low, last four high
        series = self._make_series([10, 10, 10, 10, 50, 50, 50, 50])
        df = pd.DataFrame({"Procore construction software": series})
        sig = self.proc.compute_signal("PCOR", "Procore construction software", df)
        self.assertAlmostEqual(sig.velocity_pct, 400.0)
        self.assertEqual(sig.peak_interest, 50)
        self.assertEqual(sig.trough_interest, 10)
        self.assertEqual(sig.latest_interest, 50)

    def test_velocity_flat(self):
        series = self._make_series([30] * 8)
        df = pd.DataFrame({"kw": series})
        sig = self.proc.compute_signal("X", "kw", df)
        self.assertAlmostEqual(sig.velocity_pct, 0.0)

    def test_insufficient_data_returns_none_velocity(self):
        series = self._make_series([10, 20, 30])  # < 8 points
        df = pd.DataFrame({"kw": series})
        sig = self.proc.compute_signal("X", "kw", df)
        self.assertIsNone(sig.velocity_pct)

    def test_empty_df_returns_null_signal(self):
        sig = self.proc.compute_signal("X", "kw", pd.DataFrame())
        self.assertIsNone(sig.velocity_pct)
        self.assertIsNone(sig.peak_interest)

    def test_zero_baseline_returns_none(self):
        series = self._make_series([0, 0, 0, 0, 10, 10, 10, 10])
        df = pd.DataFrame({"kw": series})
        sig = self.proc.compute_signal("X", "kw", df)
        self.assertIsNone(sig.velocity_pct)


class TestFredDataProcessor(unittest.TestCase):

    def setUp(self):
        self.proc = FredDataProcessor()

    def _obs(self, value, date="2024-01-01"):
        return {"date": date, "value": str(value)}

    def test_yoy_change_computed(self):
        # valid[0]=110 (latest), valid[1..11]=intermediate, valid[12]=100 (same month last year)
        # expected YoY = (110 - 100) / 100 * 100 = 10.0
        obs = (
            [self._obs(110, "2024-01-01")]
            + [self._obs(90, f"2023-{12 - i:02d}-01") for i in range(11)]
            + [self._obs(100, "2023-01-01")]
        )
        result = self.proc.process("TLNRESCONS", obs)
        self.assertAlmostEqual(result.latest_value, 110.0)
        self.assertIsNotNone(result.yoy_change_pct)
        self.assertAlmostEqual(result.yoy_change_pct, 10.0)

    def test_missing_sentinel_filtered(self):
        obs = [{"date": "2024-01-01", "value": "."},
               {"date": "2023-01-01", "value": "100"}]
        result = self.proc.process("X", obs)
        self.assertAlmostEqual(result.latest_value, 100.0)
        self.assertIsNone(result.yoy_change_pct)  # only 1 valid obs, no YoY

    def test_all_missing_returns_nulls(self):
        obs = [{"date": "2024-01-01", "value": "."}]
        result = self.proc.process("X", obs)
        self.assertIsNone(result.latest_value)
        self.assertIsNone(result.yoy_change_pct)

    def test_empty_observations(self):
        result = self.proc.process("X", [])
        self.assertIsNone(result.latest_value)


class TestSecRiskFactorExtractor(unittest.TestCase):

    def setUp(self):
        self.extractor = SecRiskFactorExtractor()

    def _make_text(self, prefix="", body=""):
        return (
            prefix
            + "Item 1A. Risk Factors "
            + body
        )

    def test_extracts_snippet_from_plain_text(self):
        long_body = "This is a risk sentence. " * 50
        text = self._make_text(body=long_body)
        snippet = self.extractor._extract_snippet(text)
        self.assertIsNotNone(snippet)
        self.assertLessEqual(len(snippet), 800)
        self.assertGreaterEqual(len(snippet), 100)

    def test_skips_toc_entry_too_short(self):
        # Typical TOC line: "Item 1A. Risk Factors...14" followed by real section
        toc = "Item 1A. Risk Factors 14 "   # only 26 chars after heading — skipped
        real = "Item 1A. Risk Factors " + ("Real risk content here. " * 50)
        text = toc + real
        snippet = self.extractor._extract_snippet(text)
        self.assertIsNotNone(snippet)
        self.assertIn("Real risk content", snippet)

    def test_stops_at_next_item(self):
        text = (
            "Item 1A. Risk Factors "
            + ("Risk content. " * 30)
            + " Item 2. Properties blah blah"
        )
        snippet = self.extractor._extract_snippet(text)
        self.assertIsNotNone(snippet)
        self.assertNotIn("Properties", snippet)

    def test_no_item_1a_returns_none(self):
        snippet = self.extractor._extract_snippet("Some filing with no risk section.")
        self.assertIsNone(snippet)


class TestApifyJobScraper(unittest.TestCase):

    def test_stub_returns_zero_roles_when_unconfigured(self):
        # Explicit empty creds → deterministic stub regardless of env vars.
        scraper = ApifyJobScraper(api_key="", actor_id="")
        self.assertFalse(scraper.is_configured)
        result = scraper.get_open_engineering_roles("Procore")
        self.assertTrue(result.is_stub)
        self.assertEqual(result.total_open_roles, 0)
        self.assertEqual(result.engineering_roles, [])
        self.assertEqual(result.company_name, "Procore")

    def test_headcount_proxy_stub(self):
        scraper = ApifyJobScraper(api_key="", actor_id="")
        result = scraper.get_headcount_proxy("Procore")
        self.assertTrue(result["is_stub"])
        self.assertIsNone(result["employee_estimate"])

    def test_is_configured_requires_both_key_and_actor(self):
        self.assertFalse(ApifyJobScraper(api_key="k", actor_id="").is_configured)
        self.assertFalse(ApifyJobScraper(api_key="", actor_id="a").is_configured)
        self.assertTrue(ApifyJobScraper(api_key="k", actor_id="a").is_configured)

    def test_normalize_coerces_heterogeneous_items(self):
        scraper = ApifyJobScraper(api_key="k", actor_id="a")
        items = [
            {"title": "Senior Software Engineer", "location": "NYC", "url": "u1"},
            {"positionName": "Account Executive"},          # not engineering
            {"jobTitle": "Backend Developer", "jobUrl": "u2"},
        ]
        result = scraper._normalize("Acme", items)
        self.assertFalse(result.is_stub)
        self.assertEqual(result.total_open_roles, 3)
        self.assertEqual(len(result.engineering_roles), 2)
        self.assertEqual(result.engineering_roles[0]["title"], "Senior Software Engineer")


class TestNormalizeCompanyName(unittest.TestCase):

    def test_strips_corporate_suffixes(self):
        self.assertEqual(normalize_company_name("Procore Technologies, Inc."), "Procore Technologies")
        self.assertEqual(normalize_company_name("Apple Inc."), "Apple")
        self.assertEqual(normalize_company_name("Carrier Global Corporation"), "Carrier Global")

    def test_empty_falls_back_to_input(self):
        # An all-suffix name must not collapse to an empty query.
        self.assertEqual(normalize_company_name("Inc"), "Inc")


# ─── multi-source sentiment ───────────────────────────────────────────────────


class TestScoreTexts(unittest.TestCase):

    def test_positive_dominates(self):
        score, freq = _score_texts(["strong growth and a solid beat", "bullish momentum"])
        self.assertIsNotNone(score)
        self.assertGreater(score, 0)
        self.assertIn("growth", freq)

    def test_no_lexicon_hits_returns_none(self):
        score, _ = _score_texts(["the quick brown fox jumps"])
        self.assertIsNone(score)

    def test_empty_input(self):
        score, freq = _score_texts([])
        self.assertIsNone(score)
        self.assertEqual(freq, {})


class _FakeSource:
    """Test double returning a preset _RawSourceResult."""
    def __init__(self, result):
        self._result = result
    def fetch(self, *args, **kwargs):
        return self._result


class TestMultiSourceSentimentAggregator(unittest.TestCase):

    def _agg(self, st=None, hn=None, yh=None, gn=None, bn=None, rd=None):
        """Inject fakes for every source. Unspecified sources default to empty so a
        test only declares the sources it cares about."""
        empty = lambda name: _RawSourceResult(name, [], 0)
        return MultiSourceSentimentAggregator(
            stocktwits=_FakeSource(st or empty("stocktwits")),
            hackernews=_FakeSource(hn or empty("hackernews")),
            yahoo=_FakeSource(yh or empty("yahoo_finance")),
            google_news=_FakeSource(gn or empty("google_news")),
            bing_news=_FakeSource(bn or empty("bing_news")),
            reddit=_FakeSource(rd or empty("reddit")),
        )

    def test_blends_and_records_each_source(self):
        agg = self._agg(
            st=_RawSourceResult("stocktwits", ["great buy"], 12, native_score=0.8),
            hn=_RawSourceResult("hackernews", ["solid product growth"], 10),
            gn=_RawSourceResult("google_news", ["strong earnings beat"], 8),
        )
        sig = agg.get_signal("AAPL", "Apple")
        self.assertEqual(sig.source, "multi_source")
        # Primary sources are well above the fallback threshold → Reddit is skipped,
        # so 5 primary sources are recorded (not 6).
        self.assertEqual(sig.post_count, 30)
        self.assertEqual(len(sig.sources), 5)
        self.assertNotIn("reddit", [s.source for s in sig.sources])
        self.assertIsNotNone(sig.sentiment_score)
        self.assertEqual(sig.sentiment, "positive")
        # Stocktwits native score is used and weighted highest.
        st_src = next(s for s in sig.sources if s.source == "stocktwits")
        self.assertEqual(st_src.sentiment_score, 0.8)
        self.assertTrue(st_src.available)

    def test_reddit_fallback_fires_when_primary_thin(self):
        # Only StockTwits returns a handful of messages (< threshold) → Reddit fires.
        agg = self._agg(
            st=_RawSourceResult("stocktwits", ["ok"], 3, native_score=0.4),
            rd=_RawSourceResult("reddit", ["bullish on this one"], 8),
        )
        sig = agg.get_signal("MU", "Micron")
        self.assertIn("reddit", [s.source for s in sig.sources])
        self.assertEqual(len(sig.sources), 6)
        self.assertEqual(sig.post_count, 11)

    def test_reddit_skipped_when_primary_sufficient(self):
        agg = self._agg(
            st=_RawSourceResult("stocktwits", ["strong beat"], 15, native_score=0.6),
            rd=_RawSourceResult("reddit", ["should not be fetched"], 8),
        )
        sig = agg.get_signal("INTC", "Intel")
        self.assertIsNotNone(sig.sentiment_score)
        self.assertIsNone(sig.error)            # at least one source had data
        self.assertNotIn("reddit", [s.source for s in sig.sources])
        self.assertEqual(sig.post_count, 15)    # reddit's 8 not counted

    def test_all_sources_empty_sets_error(self):
        agg = self._agg(
            st=_RawSourceResult("stocktwits", [], 0, error="404"),
            rd=_RawSourceResult("reddit", [], 0, error="403"),
        )
        sig = agg.get_signal("XYZ", "Nonexistent")
        self.assertEqual(sig.post_count, 0)
        self.assertIsNone(sig.sentiment_score)
        self.assertIsNone(sig.sentiment)
        self.assertIsNotNone(sig.error)

    def test_quotes_pooled_across_sources(self):
        agg = self._agg(
            st=_RawSourceResult(
                "stocktwits", [], 12, native_score=0.8,
                quotes=["Cintas reports a strong earnings beat this quarter"],
            ),
            gn=_RawSourceResult(
                "google_news", [], 6,
                quotes=["Cintas raises full-year guidance on solid demand"],
            ),
        )
        sig = agg.get_signal("CTAS", "Cintas")
        srcs = {q["source"] for q in sig.top_quotes}
        self.assertIn("stocktwits", srcs)
        self.assertIn("google_news", srcs)


# ─── context_aggregator ───────────────────────────────────────────────────────

from context_aggregator import (
    ContextAggregator, COMPETITOR_MAP, _to_dict, _error_node, _macro_relevance,
)


class TestCompetitorCoverage(unittest.TestCase):
    """Tickers that previously fell through to an empty peers list must now map."""

    def test_semiconductor_cluster_has_three_peers(self):
        for tkr in ("NVDA", "AMD", "AVGO", "TSM"):
            self.assertIn(tkr, COMPETITOR_MAP, f"{tkr} missing from competitor map")
            self.assertEqual(len(COMPETITOR_MAP[tkr]), 3)
            self.assertNotIn(tkr, COMPETITOR_MAP[tkr], "a ticker must not be its own peer")


class TestMacroRelevance(unittest.TestCase):
    """The CRE construction series must self-flag low relevance outside its universe."""

    def test_cre_linked_ticker_is_high_relevance(self):
        r = _macro_relevance("PCOR")
        self.assertEqual(r["relevance"], "high")

    def test_non_cre_ticker_is_low_relevance(self):
        r = _macro_relevance("NVDA")
        self.assertEqual(r["relevance"], "low")
        self.assertIn("relevance_note", r)

    def test_case_insensitive(self):
        self.assertEqual(_macro_relevance("nvda")["relevance"], "low")


class TestContextAggregatorHelpers(unittest.TestCase):

    def test_to_dict_on_dataclass(self):
        fin = CompanyFinancials(
            ticker="PCOR", name="Procore", market_cap_mm=10000.0,
            enterprise_value_mm=9500.0, trailing_revenue_mm=1000.0,
            trailing_ebitda_mm=100.0, forward_pe=40.0,
            yoy_revenue_growth_pct=18.0, ev_revenue=9.5, ev_ebitda=95.0,
        )
        d = _to_dict(fin)
        self.assertIsInstance(d, dict)
        self.assertEqual(d["ticker"], "PCOR")

    def test_error_node_structure(self):
        node = _error_node("PCOR", ValueError("fetch failed"))
        self.assertEqual(node["ticker"], "PCOR")
        self.assertIn("fetch failed", node["error"])

    def test_build_meta_keys(self):
        mock_fin = MagicMock()
        mock_alt = MagicMock()
        agg = ContextAggregator(financial_service=mock_fin, alt_data_service=mock_alt)
        meta = agg._build_meta("PCOR")
        self.assertEqual(meta["target_ticker"], "PCOR")
        self.assertEqual(meta["schema_version"], "1.5")
        self.assertIn("generated_at_utc", meta)

    def test_build_minified_context_is_valid_json(self):
        # Fully mock out both services so no network calls occur
        sample_fin = CompanyFinancials(
            ticker="PCOR", name="Procore", market_cap_mm=10000.0,
            enterprise_value_mm=9500.0, trailing_revenue_mm=1000.0,
            trailing_ebitda_mm=100.0, forward_pe=40.0,
            yoy_revenue_growth_pct=18.0, ev_revenue=9.5, ev_ebitda=95.0,
        )
        from alt_data_service import (
            TrendsSignal, FredSeries, SecRiskSnippet, ApifyJobsResult,
            Sec8KSignal, LitigationSignal,
        )

        mock_fin_svc = MagicMock()
        mock_fin_svc.get_company_financials.return_value = sample_fin

        mock_alt_svc = MagicMock()
        mock_alt_svc.get_trends_signal.return_value = TrendsSignal(
            ticker="PCOR", keyword="Procore", velocity_pct=5.0,
            peak_interest=80, trough_interest=40, latest_interest=75,
        )
        mock_alt_svc.get_fred_macro.return_value = FredSeries(
            series_id="TLNRESCONS", title="Commercial Construction",
            latest_value=95000.0, latest_date="2024-01-01", yoy_change_pct=3.2,
        )
        mock_alt_svc.get_sec_risk_snippet.return_value = SecRiskSnippet(
            ticker="PCOR", cik="0001611787",
            filing_url="https://example.com/10k.htm",
            risk_factors_snippet="Competition and market risk...",
        )
        mock_alt_svc.get_job_market_signal.return_value = ApifyJobsResult(
            company_name="Procore", total_open_roles=0, is_stub=True,
        )
        mock_alt_svc.get_sec_8k_events.return_value = Sec8KSignal(
            ticker="PCOR", cik="0001611787",
        )
        mock_alt_svc.get_litigation_signal.return_value = LitigationSignal(
            company_name="Procore", source="Stanford SCAC",
        )

        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            agg = ContextAggregator(
                financial_service=mock_fin_svc,
                alt_data_service=mock_alt_svc,
                output_dir=pathlib.Path(tmp),
            )
            result = agg.build_minified_context("PCOR")

        parsed = json.loads(result)
        self.assertIn("meta", parsed)
        self.assertIn("target", parsed)
        self.assertIn("peers", parsed)
        self.assertIn("alt_signals", parsed)
        self.assertEqual(parsed["meta"]["target_ticker"], "PCOR")
        self.assertEqual(parsed["target"]["ticker"], "PCOR")


# ─── mcp_server — tool helpers (no server start) ─────────────────────────────

class TestMcpServerHelpers(unittest.TestCase):

    def test_resolve_tickers_empty_list_returns_all(self):
        # Import private helper directly
        import importlib, types
        # Patch service constructors so module-level inits don't hit network
        with patch("financial_service.FinancialDataFetcher.fetch_ticker_info", return_value={}), \
             patch("alt_data_service.GoogleTrendsFetcher.fetch_interest_over_time", return_value=pd.DataFrame()):
            import mcp_server
            result = mcp_server._resolve_tickers([])
            self.assertEqual(sorted(result), sorted(mcp_server.SECTOR_TICKERS))

    def test_resolve_tickers_normalises_case(self):
        import mcp_server
        result = mcp_server._resolve_tickers(["pcor", "cbre"])
        self.assertIn("PCOR", result)
        self.assertIn("CBRE", result)

    def test_resolve_tickers_rejects_all_empty_strings(self):
        import mcp_server
        result = mcp_server._resolve_tickers(["", "  "])
        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("Error:"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
