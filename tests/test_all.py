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
    PricePoint,
    SECTOR_TICKERS,
    audit_peer_set,
    build_earnings_track,
    build_fundamentals_history,
    build_insider_activity,
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

    def test_captures_sector_and_industry(self):
        r = self.tx.transform("NVDA", {
            "symbol": "NVDA", "sector": "Technology", "industry": " Semiconductors "
        })
        self.assertEqual(r.sector, "Technology")
        self.assertEqual(r.industry, "Semiconductors")   # trimmed

    def test_missing_sector_is_none(self):
        r = self.tx.transform("NVDA", {"symbol": "NVDA"})
        self.assertIsNone(r.sector)
        self.assertIsNone(r.industry)

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

    def test_currency_mismatch_suppresses_ratios(self):
        # An ADR-style payload: USD trading currency, TWD reporting currency. The raw
        # ratios mix units, so the gate must N/M them and record the reason — never
        # emit a wrong-by-FX number (the TSMC 2.1x / 3.1x defect).
        raw = {
            "currency": "USD",
            "financialCurrency": "TWD",
            "enterpriseValue": 9_000_000_000_000,
            "totalRevenue": 4_100_000_000_000,
            "ebitda": 2_900_000_000_000,
        }
        r = self.tx.transform("TSM", raw)
        self.assertEqual(r.ev_revenue, NM)
        self.assertEqual(r.ev_ebitda, NM)
        self.assertEqual(r.currency, "USD")
        self.assertEqual(r.financial_currency, "TWD")
        self.assertTrue(any(f.startswith("currency_mismatch") for f in r.quality_flags))

    def test_matching_currency_keeps_ratios(self):
        raw = {
            "currency": "USD",
            "financialCurrency": "USD",
            "enterpriseValue": 9_500_000_000,
            "totalRevenue": 1_000_000_000,
            "ebitda": 100_000_000,
        }
        r = self.tx.transform("PCOR", raw)
        self.assertEqual(r.ev_revenue, 9.5)
        self.assertEqual(r.ev_ebitda, 95.0)
        self.assertEqual(r.quality_flags, [])


class TestAuditPeerSet(unittest.TestCase):
    """Cross-sectional plausibility audit — sector-agnostic outlier/bounds checks."""

    def _co(self, ticker, ev_rev, ev_ebitda, fwd_pe=20.0):
        return CompanyFinancials(
            ticker=ticker, name=ticker, market_cap_mm=1000.0,
            enterprise_value_mm=1000.0, trailing_revenue_mm=100.0,
            trailing_ebitda_mm=50.0, forward_pe=fwd_pe,
            yoy_revenue_growth_pct=10.0, ev_revenue=ev_rev, ev_ebitda=ev_ebitda,
        )

    def test_flags_cross_sectional_outlier(self):
        # Three peers near ~25x EV/Revenue, one wildly low (a parse/currency artifact
        # that slipped through as a same-currency number) → flagged.
        cohort = [
            self._co("A", 22.0, 30.0),
            self._co("B", 28.0, 26.0),
            self._co("C", 25.0, 28.0),
            self._co("BAD", 2.1, 3.1),
        ]
        summary = audit_peer_set(cohort)
        self.assertIn("BAD", summary)
        self.assertTrue(any("peer_outlier" in f for f in summary["BAD"]))
        # Coherent peers are not flagged.
        self.assertNotIn("A", summary)

    def test_real_but_extreme_value_within_factor_not_flagged(self):
        # A genuinely high EV/EBITDA (depressed-EBITDA cyclical) that stays within the
        # outlier factor of the cohort median must NOT be condemned as an artifact.
        cohort = [
            self._co("N", ev_rev=20.0, ev_ebitda=31.0),
            self._co("V", ev_rev=30.0, ev_ebitda=55.0),
            self._co("M", ev_rev=18.0, ev_ebitda=40.0),
            self._co("A", ev_rev=22.0, ev_ebitda=112.0),  # high but < 4x median
        ]
        summary = audit_peer_set(cohort)
        self.assertNotIn("A", summary)

    def test_flags_absolute_implausible_bound(self):
        cohort = [self._co("X", ev_rev=5000.0, ev_ebitda=20.0)]  # EV/Rev 5000x impossible
        summary = audit_peer_set(cohort)
        self.assertIn("X", summary)
        self.assertTrue(any("implausible" in f for f in summary["X"]))

    def test_nm_ratios_excluded_from_median(self):
        # A currency-suppressed peer (NM) must not poison the median or be flagged on
        # ratios it doesn't have.
        cohort = [
            self._co("A", 22.0, 30.0),
            self._co("B", 28.0, 26.0),
            self._co("C", 25.0, 28.0),
            self._co("TSM", NM, NM),
        ]
        summary = audit_peer_set(cohort)
        self.assertNotIn("TSM", summary)


class TestInsiderActivityBuilder(unittest.TestCase):
    _TODAY = __import__("datetime").date(2026, 6, 11)

    @staticmethod
    def _rec(insider="DOE JANE", position="Chief Executive Officer",
             text="Sale at price 60.00 per share.", shares=1000,
             value=60000, date="2026-05-01", url="https://sec.gov/form4"):
        return {"insider": insider, "position": position, "text": text,
                "shares": shares, "value": value, "date": date, "url": url}

    def test_empty_records_yield_no_data_error(self):
        sig = build_insider_activity("TST", [], today=self._TODAY)
        self.assertEqual(sig.error, "no_data")
        self.assertEqual(sig.sell_count, 0)

    def test_sells_and_buys_classified_and_aggregated(self):
        records = [
            self._rec(value=100000),
            self._rec(insider="ROE RICHARD", position="CFO", value=50000),
            self._rec(text="Purchase at price 55.00 per share.", value=30000),
            self._rec(text="Stock Award(Grant) at price 0.00 per share.", value=0),
        ]
        sig = build_insider_activity("TST", records, today=self._TODAY)
        self.assertEqual(sig.sell_count, 2)
        self.assertEqual(sig.buy_count, 1)
        self.assertEqual(sig.total_sell_value_usd, 150000.0)
        self.assertEqual(sig.total_buy_value_usd, 30000.0)
        # notable sells sorted by value, largest first
        self.assertEqual(sig.notable_sells[0].value_usd, 100000.0)
        self.assertIsNone(sig.error)

    def test_outside_window_and_dateless_rows_excluded(self):
        records = [
            self._rec(date="2024-01-01"),          # outside the 12m window
            self._rec(date=None),                  # dateless
            self._rec(date="2026-06-01"),          # inside
        ]
        sig = build_insider_activity("TST", records, today=self._TODAY)
        self.assertEqual(sig.sell_count, 1)

    def test_awards_never_counted_as_sells(self):
        records = [self._rec(text="Stock Award(Grant) at price 0.00 per share.")]
        sig = build_insider_activity("TST", records, today=self._TODAY)
        self.assertEqual(sig.sell_count, 0)
        self.assertEqual(sig.buy_count, 0)


class TestEarningsTrackBuilder(unittest.TestCase):

    @staticmethod
    def _q(period, surprise, reported=1.0, estimate=1.0):
        return {"period": period, "eps_estimate": estimate,
                "eps_reported": reported, "surprise_pct": surprise}

    def test_no_reported_rows_is_no_data(self):
        future = [{"period": "2026-08-01", "eps_estimate": 0.4,
                   "eps_reported": None, "surprise_pct": None}]
        track = build_earnings_track("TST", future)
        self.assertEqual(track.error, "no_data")

    def test_streak_counts_from_most_recent(self):
        records = [
            self._q("2026-05-01", -6.0),
            self._q("2026-02-01", -2.0),
            self._q("2025-11-01", 30.0),
            self._q("2025-08-01", -1.0),
        ]
        track = build_earnings_track("TST", records)
        self.assertEqual(track.consecutive_misses, 2)
        self.assertEqual(track.beat_count, 1)
        self.assertEqual(track.miss_count, 3)
        self.assertEqual(track.quarters[0].period, "2026-05-01")  # newest first

    def test_caps_at_max_quarters_and_averages(self):
        records = [self._q(f"202{4 + i // 4}-{(i % 4) * 3 + 1:02d}-01", 10.0)
                   for i in range(10)]
        track = build_earnings_track("TST", records, max_quarters=8)
        self.assertEqual(len(track.quarters), 8)
        self.assertEqual(track.avg_surprise_pct, 10.0)
        self.assertEqual(track.consecutive_misses, 0)

    def test_future_rows_filtered_out(self):
        records = [
            {"period": "2026-08-01", "eps_estimate": 0.4,
             "eps_reported": None, "surprise_pct": None},
            self._q("2026-05-01", 5.0),
        ]
        track = build_earnings_track("TST", records)
        self.assertEqual(len(track.quarters), 1)
        self.assertEqual(track.beat_count, 1)


class TestFundamentalsHistoryBuilder(unittest.TestCase):

    _STMTS = {
        "2024-12-31": {"revenue": 1_000_000_000.0, "ebitda": 200_000_000.0,
                       "net_income": 100_000_000.0, "total_debt": 300_000_000.0,
                       "cash": 100_000_000.0, "shares": 100_000_000.0},
        "2025-12-31": {"revenue": 1_200_000_000.0, "ebitda": 260_000_000.0,
                       "net_income": 150_000_000.0, "total_debt": 300_000_000.0,
                       "cash": 200_000_000.0, "shares": 100_000_000.0},
    }
    _PRICES = [PricePoint(date="2024-12-30", close=20.0),
               PricePoint(date="2025-12-30", close=30.0)]

    def test_empty_statements_is_no_data(self):
        hist = build_fundamentals_history("TST", {}, [])
        self.assertEqual(hist.error, "no_data")

    def test_years_ordered_with_growth_and_ratios(self):
        hist = build_fundamentals_history("TST", self._STMTS, self._PRICES)
        self.assertEqual([y.fiscal_year for y in hist.years], ["FY2024", "FY2025"])
        fy24, fy25 = hist.years
        self.assertEqual(fy24.revenue_mm, 1000.0)
        self.assertIsNone(fy24.yoy_revenue_growth_pct)   # no prior year
        self.assertEqual(fy25.yoy_revenue_growth_pct, 20.0)
        # FY2025: mktcap = 30 × 100M = 3,000M; EV = 3,000 + 300 − 200 = 3,100M
        self.assertEqual(fy25.ev_mm_approx, 3100.0)
        self.assertAlmostEqual(fy25.ev_revenue_approx, 2.58, places=2)
        self.assertEqual(fy25.pe_trailing_approx, 20.0)  # 3,000 / 150
        self.assertTrue(hist.approximate)

    def test_missing_price_or_shares_degrades_ratios_to_nm(self):
        hist = build_fundamentals_history("TST", self._STMTS, [])  # no prices
        for y in hist.years:
            self.assertEqual(y.ev_revenue_approx, NM)
            self.assertEqual(y.pe_trailing_approx, NM)
            self.assertIsNotNone(y.revenue_mm)           # statements still carried

    def test_negative_net_income_gives_nm_pe(self):
        stmts = {k: dict(v) for k, v in self._STMTS.items()}
        for v in stmts.values():
            v["net_income"] = -50_000_000.0
        hist = build_fundamentals_history("TST", stmts, self._PRICES)
        self.assertTrue(all(y.pe_trailing_approx == NM for y in hist.years))

    def test_all_empty_statement_year_dropped(self):
        stmts = dict(self._STMTS)
        stmts["2023-12-31"] = {"revenue": None, "ebitda": None, "net_income": None,
                               "total_debt": None, "cash": None, "shares": None}
        hist = build_fundamentals_history("TST", stmts, self._PRICES)
        self.assertEqual([y.fiscal_year for y in hist.years], ["FY2024", "FY2025"])


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
    RelatedCompaniesFetcher,
    _RawSourceResult,
    _score_texts,
    _trends_keyword,
    normalize_company_name,
)


class TestTrendsKeyword(unittest.TestCase):
    """Trends keyword: curated wins, else cleaned company name, else ticker."""

    def test_curated_keyword_wins(self):
        self.assertEqual(_trends_keyword("PCOR", "Procore Technologies Inc"),
                         "Procore construction software")

    def test_company_name_cleaned_of_suffix(self):
        self.assertEqual(_trends_keyword("INTC", "Intel Corporation"), "Intel")
        self.assertEqual(_trends_keyword("XYZ", "Acme Holdings, Inc."), "Acme")

    def test_falls_back_to_ticker(self):
        self.assertEqual(_trends_keyword("XYZ"), "XYZ")
        self.assertEqual(_trends_keyword("XYZ", ""), "XYZ")


class TestRelatedCompaniesFetcher(unittest.TestCase):
    """Dynamic peer discovery degrades gracefully and sanitises results."""

    def test_not_configured_returns_empty_with_error(self):
        sig = RelatedCompaniesFetcher(api_key="").fetch("XOM")
        self.assertEqual(sig.related, [])
        self.assertIn("MASSIVE_API_KEY", sig.error or "")

    def test_parses_and_excludes_self_and_dupes(self):
        fetcher = RelatedCompaniesFetcher(api_key="key")
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"results": [
            {"ticker": "CVX"}, {"ticker": "xom"},      # self (case-insensitive)
            {"ticker": "BP"}, {"ticker": "CVX"},        # dup
            {"ticker": ""},                             # empty
        ]}
        fetcher._session = MagicMock()
        fetcher._session.get.return_value = resp
        sig = fetcher.fetch("XOM")
        self.assertEqual(sig.related, ["CVX", "BP"])
        self.assertIsNone(sig.error)

    def test_request_failure_returns_empty(self):
        import requests
        fetcher = RelatedCompaniesFetcher(api_key="key")
        fetcher._session = MagicMock()
        fetcher._session.get.side_effect = requests.RequestException("boom")
        sig = fetcher.fetch("XOM")
        self.assertEqual(sig.related, [])
        self.assertIn("boom", sig.error or "")


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
        score, freq, signal = _score_texts(["strong growth and a solid beat", "bullish momentum"])
        self.assertIsNotNone(score)
        self.assertGreater(score, 0)
        self.assertIn("growth", freq)
        self.assertEqual(signal, 6)  # strong, growth, solid, beat, bullish, momentum

    def test_no_lexicon_hits_returns_none(self):
        score, _, signal = _score_texts(["the quick brown fox jumps"])
        self.assertIsNone(score)
        self.assertEqual(signal, 0)

    def test_empty_input(self):
        score, freq, signal = _score_texts([])
        self.assertIsNone(score)
        self.assertEqual(freq, {})
        self.assertEqual(signal, 0)

    def test_thin_sample_shrinks_toward_neutral(self):
        # One negative word among 25 otherwise-neutral texts must NOT saturate to
        # -1.0 (the HackerNews artifact). With smoothing K=4 it lands near -0.2.
        texts = ["the company posted a loss"] + ["neutral filler text here"] * 24
        score, _, signal = _score_texts(texts)
        self.assertEqual(signal, 1)
        self.assertAlmostEqual(score, round(-1 / (1 + 4), 2))   # -0.2
        self.assertGreater(score, -0.5)                         # nowhere near -1.0

    def test_deep_signal_can_approach_extreme(self):
        # Confidence is earned: many matched words let the score grow in magnitude.
        score, _, signal = _score_texts(["loss miss weak"] * 20)
        self.assertEqual(signal, 60)
        self.assertLess(score, -0.9)


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

    def test_thin_signal_source_gets_low_weight_and_confidence(self):
        # 25 HackerNews messages but only one negative lexicon word: must be marked
        # low confidence with a near-zero weight, so it cannot dominate or anchor the
        # blend the way the raw -1.0 / n=25 reading did.
        hn_texts = ["the company posted a loss"] + ["neutral filler text here"] * 24
        agg = self._agg(
            st=_RawSourceResult("stocktwits", ["great strong buy beat win"], 30,
                                native_score=0.6, signal_count=20),
            hn=_RawSourceResult("hackernews", hn_texts, 25),
        )
        sig = agg.get_signal("NVDA", "NVIDIA")
        hn = next(s for s in sig.sources if s.source == "hackernews")
        self.assertEqual(hn.signal_count, 1)
        self.assertEqual(hn.confidence, "low")
        self.assertGreater(hn.sentiment_score, -0.5)   # smoothed, not -1.0
        st = next(s for s in sig.sources if s.source == "stocktwits")
        self.assertGreater(st.weight, hn.weight * 3)   # deep source dominates thin one
        self.assertEqual(sig.sentiment, "positive")    # not dragged down by the 1-word HN

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
    _macro_for_ticker, SECTOR_MACRO_MAP, _MAX_PEERS,
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


class TestSectorAwareMacro(unittest.TestCase):
    """`_macro_for_ticker` must pick a sector-appropriate FRED series."""

    def test_cre_universe_keeps_construction_series(self):
        m = _macro_for_ticker("PCOR")
        self.assertEqual(m["series_id"], "TLNRESCONS")
        self.assertEqual(m["relevance"], "high")

    def test_cre_override_wins_over_sector(self):
        # HON is classified Industrials by yfinance but is in the CRE-linked set,
        # so the construction series must still win.
        m = _macro_for_ticker("HON", "Industrials")
        self.assertEqual(m["series_id"], "TLNRESCONS")

    def test_known_sector_maps_to_specific_series(self):
        self.assertEqual(_macro_for_ticker("NVDA", "Technology")["series_id"], "INDPRO")
        self.assertEqual(_macro_for_ticker("XOM", "Energy")["series_id"], "DCOILWTICO")
        self.assertEqual(_macro_for_ticker("JPM", "Financial Services")["series_id"], "FEDFUNDS")
        for sector in SECTOR_MACRO_MAP:
            self.assertEqual(_macro_for_ticker("ZZZZ", sector)["relevance"], "high")

    def test_unknown_sector_falls_back_to_gdp_low_relevance(self):
        m = _macro_for_ticker("ZZZZ", "Some New Sector")
        self.assertEqual(m["series_id"], "GDPC1")
        self.assertEqual(m["relevance"], "low")

    def test_no_sector_falls_back_to_gdp(self):
        self.assertEqual(_macro_for_ticker("ZZZZ")["series_id"], "GDPC1")


class TestPeerResolution(unittest.TestCase):
    """Peers resolve via curated override first, then dynamic discovery."""

    def _aggregator(self, related):
        mock_alt = MagicMock()
        mock_alt.get_related_tickers.return_value = related
        return ContextAggregator(financial_service=MagicMock(), alt_data_service=mock_alt), mock_alt

    def test_curated_override_wins(self):
        agg, mock_alt = self._aggregator(["AAA", "BBB", "CCC"])
        # NVDA has a curated cluster — dynamic discovery must NOT be consulted.
        self.assertEqual(agg._resolve_peers("NVDA"), COMPETITOR_MAP["NVDA"])
        mock_alt.get_related_tickers.assert_not_called()

    def test_dynamic_discovery_for_uncurated_ticker(self):
        agg, mock_alt = self._aggregator(["AAA", "BBB", "CCC", "DDD"])
        peers = agg._resolve_peers("XYZ")
        self.assertEqual(peers, ["AAA", "BBB", "CCC"])      # capped at _MAX_PEERS
        self.assertEqual(len(peers), _MAX_PEERS)
        mock_alt.get_related_tickers.assert_called_once_with("XYZ")

    def test_dynamic_discovery_failure_returns_empty(self):
        mock_alt = MagicMock()
        mock_alt.get_related_tickers.side_effect = RuntimeError("api down")
        agg = ContextAggregator(financial_service=MagicMock(), alt_data_service=mock_alt)
        self.assertEqual(agg._resolve_peers("XYZ"), [])

    def test_no_peers_anywhere_returns_empty(self):
        agg, _ = self._aggregator([])
        self.assertEqual(agg._resolve_peers("XYZ"), [])


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
        self.assertEqual(meta["schema_version"], "1.9")
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
