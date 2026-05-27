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

sys.path.insert(0, os.path.dirname(__file__))

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

    def test_stub_returns_zero_roles(self):
        scraper = ApifyJobScraper()
        result = scraper.get_open_engineering_roles("Procore")
        self.assertTrue(result.is_stub)
        self.assertEqual(result.total_open_roles, 0)
        self.assertEqual(result.engineering_roles, [])
        self.assertEqual(result.company_name, "Procore")

    def test_headcount_proxy_stub(self):
        scraper = ApifyJobScraper()
        result = scraper.get_headcount_proxy("Procore")
        self.assertTrue(result["is_stub"])
        self.assertIsNone(result["employee_estimate"])


# ─── context_aggregator ───────────────────────────────────────────────────────

from context_aggregator import ContextAggregator, _to_dict, _error_node


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
        self.assertEqual(meta["schema_version"], "1.0")
        self.assertIn("generated_at_utc", meta)

    def test_build_minified_context_is_valid_json(self):
        # Fully mock out both services so no network calls occur
        sample_fin = CompanyFinancials(
            ticker="PCOR", name="Procore", market_cap_mm=10000.0,
            enterprise_value_mm=9500.0, trailing_revenue_mm=1000.0,
            trailing_ebitda_mm=100.0, forward_pe=40.0,
            yoy_revenue_growth_pct=18.0, ev_revenue=9.5, ev_ebitda=95.0,
        )
        from alt_data_service import TrendsSignal, FredSeries, SecRiskSnippet, ApifyJobsResult

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
