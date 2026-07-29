"""
test_web_research.py — Unit tests for the ScrapeGraphAI web-research source.

No network and no LLM are touched: HTTP and the SmartScraperGraph extractor are
mocked. These tests pin the token-optimization guarantees that justify the feature:
  1. HTML→Markdown drops <script>/<style>/<nav> before anything reaches the LLM.
  2. Change detection (304 and content-hash match) reuses the cached extraction
     and skips the LLM entirely.
  3. Scraped text is scored through the SAME lexicon helpers as every other source.
  4. The whole thing degrades to a clean stub when scrapegraphai/key are absent.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import web_research_service as wr
from web_research_service import (
    CleanMarkdownConverter,
    ChangeDetectionCache,
    ScrapeGraphExtractor,
    ScrapedPage,
    WebResearchProcessor,
    WebResearchService,
)


# ── 1. HTML filtering & Markdown conversion ──────────────────────────────────

class TestCleanMarkdown(unittest.TestCase):
    HTML = """
    <html><head><style>.x{color:red}</style></head>
    <body>
      <nav>Home | About | Contact</nav>
      <header>SITE BANNER</header>
      <script>tracker('spy');</script>
      <article><h1>Acme beats estimates</h1>
        <p>Revenue grew and margins expanded.</p></article>
      <footer>copyright junk</footer>
    </body></html>
    """

    def test_strips_non_content_tags(self):
        md = CleanMarkdownConverter.html_to_markdown(self.HTML)
        low = md.lower()
        for noise in ("tracker(", "color:red", "site banner", "home | about", "copyright junk"):
            self.assertNotIn(noise, low)

    def test_keeps_real_content(self):
        md = CleanMarkdownConverter.html_to_markdown(self.HTML)
        self.assertIn("Acme beats estimates", md)
        self.assertIn("margins expanded", md)


# ── 2. Change detection ──────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status, text="", etag=None, last_modified=None):
        self.status_code = status
        self.text = text
        self.headers = {}
        if etag:
            self.headers["ETag"] = etag
        if last_modified:
            self.headers["Last-Modified"] = last_modified

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.RequestException(f"HTTP {self.status_code}")


class TestChangeDetection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = ChangeDetectionCache(Path(self._tmp.name) / "c.sqlite")

    def tearDown(self):
        self._tmp.cleanup()

    def _service(self, resp, extractor):
        conv = CleanMarkdownConverter(session=mock.Mock(get=mock.Mock(return_value=resp)))
        return WebResearchService(
            converter=conv, cache=self.cache, extractor=extractor,
            news_fetcher=mock.Mock(),  # unused; we call _scrape_one directly
        )

    def test_304_reuses_extraction_and_skips_llm(self):
        self.cache.put("u", "h1", "etag-1", None, [{"text": "cached row"}])
        extractor = mock.Mock()
        svc = self._service(_FakeResp(304), extractor)
        page = svc._scrape_one("u", "forum", use_llm=True)
        self.assertTrue(page.from_cache)
        self.assertEqual(page.extracted, [{"text": "cached row"}])
        extractor.extract.assert_not_called()

    def test_hash_match_reuses_extraction_and_skips_llm(self):
        html = "<html><body><p>same body</p></body></html>"
        md = CleanMarkdownConverter.html_to_markdown(html)
        self.cache.put("u", ChangeDetectionCache.hash_text(md), None, None, [{"text": "old"}])
        extractor = mock.Mock()
        svc = self._service(_FakeResp(200, text=html), extractor)
        page = svc._scrape_one("u", "forum", use_llm=True)
        self.assertTrue(page.from_cache)
        extractor.extract.assert_not_called()

    def test_changed_content_runs_extraction(self):
        html = "<html><body><p>brand new content</p></body></html>"
        extractor = mock.Mock()
        extractor.extract.return_value = [{"text": "fresh"}]
        svc = self._service(_FakeResp(200, text=html, etag="e2"), extractor)
        page = svc._scrape_one("u", "forum", use_llm=True)
        self.assertFalse(page.from_cache)
        extractor.extract.assert_called_once()
        # Persisted for next run.
        self.assertEqual(self.cache.get("u")["extracted"], [{"text": "fresh"}])


# ── 3. Processor reuses the shared lexicon scorer ────────────────────────────

class TestProcessor(unittest.TestCase):
    def test_scores_and_labels_like_shared_helpers(self):
        pages = [
            ScrapedPage("u1", "forum", False, [
                {"author": "a", "date": None, "text": "strong growth, bullish, great momentum"},
                {"author": "b", "date": None, "text": "solid beat and improving margins"},
            ]),
            ScrapedPage("u2", "news", False, [
                {"headline": "Acme outperforms", "stance": "positive",
                 "key_points": ["record profit", "upside to guidance"]},
            ]),
        ]
        sig = WebResearchProcessor().process("ACME", "Acme Inc", pages)
        self.assertTrue(sig.available)
        self.assertEqual(sig.sentiment, "positive")
        self.assertGreater(sig.sentiment_score, 0)
        self.assertEqual(len(sig.forum_posts), 2)
        self.assertEqual(len(sig.news_extracts), 1)
        self.assertIn("from_cache", sig.sources_scraped[0])

    def test_empty_pages_yield_unavailable(self):
        sig = WebResearchProcessor().process("ACME", "Acme Inc",
                                             [ScrapedPage("u", "forum", False, [], error="boom")])
        self.assertFalse(sig.available)
        self.assertIsNotNone(sig.error)


# ── 4. Stub degradation ──────────────────────────────────────────────────────

class TestStubFallback(unittest.TestCase):
    def test_stub_when_no_targets(self):
        # No seeds + a news fetcher that yields no URLs → nothing to scrape.
        news = mock.Mock()
        news.fetch.return_value = mock.Mock(articles=[])
        extractor = mock.Mock(); extractor.is_available = False
        svc = WebResearchService(extractor=extractor, news_fetcher=news)
        sig = svc.get_web_research("ACME", "Acme Inc")
        self.assertFalse(sig.available)
        self.assertIn("no web-research targets", sig.error)

    def test_stub_when_disabled(self):
        with mock.patch.object(wr, "WEB_RESEARCH_ENABLED", False):
            svc = WebResearchService(extractor=mock.Mock(), news_fetcher=mock.Mock())
            sig = svc.get_web_research("ACME", "Acme Inc")
        self.assertFalse(sig.available)
        self.assertIn("disabled", sig.error)


# ── No-key lexical fallback ──────────────────────────────────────────────────

class TestLexicalFallback(unittest.TestCase):
    def test_real_key_check_rejects_placeholder(self):
        self.assertFalse(wr._is_real_key(""))
        self.assertFalse(wr._is_real_key("sk-ant-..."))      # .env.example placeholder
        self.assertTrue(wr._is_real_key("sk-ant-api03-" + "x" * 40))

    def test_lexical_extraction_without_key(self):
        html = ("<html><body><article>"
                "<p>Acme posted strong growth and a solid earnings beat this quarter.</p>"
                "<p>Margins are improving and momentum looks bullish into next year.</p>"
                "</article></body></html>")
        news = mock.Mock()
        news.fetch.return_value = mock.Mock(articles=[mock.Mock(url="http://x/news")])
        conv = CleanMarkdownConverter(
            session=mock.Mock(get=mock.Mock(return_value=_FakeResp(200, text=html)))
        )
        extractor = mock.Mock(); extractor.is_available = False   # no key → lexical path
        with tempfile.TemporaryDirectory() as tmp:
            svc = WebResearchService(
                converter=conv, cache=ChangeDetectionCache(Path(tmp) / "c.sqlite"),
                extractor=extractor, news_fetcher=news,
            )
            sig = svc.get_web_research("ACME", "Acme Inc")
        self.assertTrue(sig.available)
        self.assertEqual(sig.extraction_mode, "lexical")
        self.assertEqual(sig.sentiment, "positive")
        extractor.extract.assert_not_called()   # the LLM was never invoked


# ── 5. TOON encoding (aggregator helper) ─────────────────────────────────────

class TestToonEncode(unittest.TestCase):
    def test_encode_or_json_fallback_is_nonempty(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        from context_aggregator import _toon_encode
        rows = [{"author": "a", "text": "hi"}, {"author": "b", "text": "yo"}]
        out = _toon_encode(rows)
        self.assertTrue(out)                 # TOON string or JSON fallback, never empty
        self.assertEqual(_toon_encode([]), "")  # empty array → empty string


# ── 6. Ticker-relevance filtering (drops multi-stock roundup noise) ───────────

class TestRelevanceTerms(unittest.TestCase):
    def test_strips_corporate_suffixes(self):
        terms = wr._relevance_terms("MU", "Micron Technology, Inc.")
        self.assertIn("micron", terms)
        self.assertIn("mu", terms)
        self.assertNotIn("technology", terms)   # generic → would match every tech article
        self.assertNotIn("inc", terms)

    def test_mentions_is_word_boundary(self):
        terms = wr._relevance_terms("MU", "Micron Technology, Inc.")
        self.assertTrue(wr._mentions("Micron's HBM revenue grew", terms))
        self.assertTrue(wr._mentions("shares of $MU jumped", terms))      # bare ticker hits "$MU"
        self.assertFalse(wr._mentions("The S&P 500 rose 0.30%", terms))
        self.assertFalse(wr._mentions("museum attendance climbed", terms))  # no spurious "mu" match

    def test_common_word_ticker_dropped_leans_on_name(self):
        terms = wr._relevance_terms("ON", "ON Semiconductor Corporation")
        self.assertNotIn("on", terms)            # bare "on" would match every sentence
        self.assertIn("semiconductor", terms)    # discriminator retained
        # The bare ticker no longer makes a generic sentence "relevant".
        self.assertFalse(wr._mentions("Markets turned higher on Monday", terms))

    def test_single_char_ticker_dropped(self):
        terms = wr._relevance_terms("F", "Ford Motor Company")
        self.assertNotIn("f", terms)
        self.assertIn("ford", terms)
        self.assertIn("motor", terms)


class TestRelevanceFilter(unittest.TestCase):
    NEWS = [ScrapedPage("u", "news", False, [
        {"headline": "Micron surges on HBM demand", "stance": "positive",
         "key_points": ["Micron's HBM revenue grew sharply", "Datacenter pricing firmed"]},
        {"headline": "Eli Lilly gains on weight-loss data", "stance": "positive",
         "key_points": ["The S&P 500 rose 0.30%", "Broadcom slipped on guidance"]},
    ])]

    def test_drops_offtopic_extract_entirely(self):
        sig = WebResearchProcessor().process("MU", "Micron Technology, Inc.", self.NEWS)
        self.assertEqual(len(sig.news_extracts), 1)              # off-issuer extract removed
        self.assertIn("Micron", sig.news_extracts[0]["headline"])
        blob = repr(sig.news_extracts) + repr(sig.top_quotes) + repr(sig.top_themes)
        self.assertNotIn("Eli Lilly", blob)
        self.assertNotIn("Broadcom", blob)

    def test_offtopic_headline_blanked_but_relevant_points_kept(self):
        page = [ScrapedPage("u", "news", False, [
            {"headline": "Markets shake off Friday's rout", "stance": "neutral",
             "key_points": ["Micron rebounded 9% intraday", "Marvell also jumped"]},
        ])]
        sig = WebResearchProcessor().process("MU", "Micron Technology, Inc.", page)
        self.assertEqual(len(sig.news_extracts), 1)
        self.assertEqual(sig.news_extracts[0]["headline"], "")  # off-topic headline not stored
        self.assertEqual(sig.news_extracts[0]["key_points"], ["Micron rebounded 9% intraday"])

    def test_require_ticker_off_keeps_everything(self):
        with mock.patch.object(wr, "WEB_RESEARCH_REQUIRE_TICKER", False):
            sig = WebResearchProcessor().process("MU", "Micron Technology, Inc.", self.NEWS)
        self.assertEqual(len(sig.news_extracts), 2)             # nothing dropped

    def test_no_discriminating_terms_is_safe_noop(self):
        # Ambiguous ticker + all-generic name → no terms → filter must NOT drop everything.
        page = [ScrapedPage("u", "news", False, [
            {"headline": "Some unrelated market news", "stance": None,
             "key_points": ["A line that names no issuer"]},
        ])]
        sig = WebResearchProcessor().process("IT", "IT Inc", page)   # terms come out empty
        self.assertEqual(wr._relevance_terms("IT", "IT Inc"), [])
        self.assertEqual(len(sig.news_extracts), 1)            # kept (no-op, not over-dropped)


class TestResolutionPrioritizes(unittest.TestCase):
    def _articles(self):
        return [
            mock.Mock(url="http://x/roundup",    title="Stock Market Today: tech rebounds"),
            mock.Mock(url="http://x/micron",     title="Micron stock could have massive upside"),
            mock.Mock(url="http://x/supermicro", title="Supermicro is up 70% in 30 days"),
        ]

    def test_ticker_in_headline_wins_the_budget(self):
        news = mock.Mock(); news.fetch.return_value = mock.Mock(articles=self._articles())
        svc = WebResearchService(extractor=mock.Mock(), news_fetcher=news, max_urls=1)
        targets = svc._resolve_targets("MU", "Micron Technology, Inc.")
        self.assertEqual(targets, [("http://x/micron", "news")])

    def test_backfill_when_no_headline_matches(self):
        # None of the titles name the issuer → still return targets (don't starve to stub).
        arts = [mock.Mock(url="http://x/a", title="Markets mixed"),
                mock.Mock(url="http://x/b", title="Chip sector wobbles")]
        news = mock.Mock(); news.fetch.return_value = mock.Mock(articles=arts)
        svc = WebResearchService(extractor=mock.Mock(), news_fetcher=news, max_urls=5)
        targets = svc._resolve_targets("MU", "Micron Technology, Inc.")
        self.assertEqual(len(targets), 2)


# ── 7. _normalize unwraps provider envelopes (guards news extraction) ─────────

class TestNormalizeEnvelope(unittest.TestCase):
    def test_unwraps_content_envelope_news(self):
        wrapped = {"content": {"headline": "H", "key_points": ["p"], "stance": "positive"}}
        out = ScrapeGraphExtractor._normalize(wrapped, "news")
        self.assertEqual(out, [{"headline": "H", "key_points": ["p"], "stance": "positive"}])

    def test_flat_news_object_is_single_row(self):
        # Regression: the old code hit key_points (a list) and returned [] for flat news.
        flat = {"headline": "H", "key_points": ["p1", "p2"], "stance": "neutral"}
        out = ScrapeGraphExtractor._normalize(flat, "news")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["headline"], "H")

    def test_forum_posts_list(self):
        out = ScrapeGraphExtractor._normalize({"posts": [{"text": "a"}, {"text": "b"}]}, "forum")
        self.assertEqual(out, [{"text": "a"}, {"text": "b"}])

    def test_forum_content_envelope(self):
        out = ScrapeGraphExtractor._normalize({"content": {"posts": [{"text": "a"}]}}, "forum")
        self.assertEqual(out, [{"text": "a"}])


if __name__ == "__main__":
    unittest.main()
