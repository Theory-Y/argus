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


if __name__ == "__main__":
    unittest.main()
