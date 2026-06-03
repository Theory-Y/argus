"""
web_research_service.py — ScrapeGraphAI First-Hand Web Research
================================================================
Adds a *first-hand discussion* signal that the existing alt-data sources miss:
full news-article bodies and niche/industry forums, extracted into a structured
sentiment/themes signal by ScrapeGraphAI's LLM scraper pointed at the project's
existing Claude key (no paid scraping API).

Three token optimizations are baked in so recurring runs stay cheap:

  1. HTML filtering & Markdown conversion (CleanMarkdownConverter)
       <script>/<style>/<nav>/<header>/<footer>/<aside>/<svg> are stripped and the
       remaining structural HTML is converted to Markdown *before* the LLM sees the
       page — typically 50–70% fewer input tokens than raw HTML.
  2. Incremental runs / change detection (ChangeDetectionCache)
       A conditional GET (If-None-Match / If-Modified-Since) plus a sha256 of the
       cleaned Markdown lets unchanged pages reuse the prior extraction and skip the
       LLM entirely — 85–95% off the recurring cost on pages that did not change.
  3. Compact serialization (applied by the caller)
       The uniform output arrays (forum_posts / news_extracts) are TOON-encoded by
       ContextAggregator rather than emitted as nested JSON.

Architecture (mirrors alt_data_service.py): each concern is a small collaborator
(Fetcher/Converter/Cache/Extractor/Processor) wired together by the WebResearchService
façade. Everything degrades to a clearly-marked stub when scrapegraphai is not
installed or no Claude key is present, so the existing pipeline is never blocked —
the same contract as ApifyJobScraper.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Comment

# Reuse the lexicon scorer and news-URL source from the existing alt-data engine so
# scraped text is scored identically to every other free-text source (consistent
# sentiment_score / themes / confidence across the whole payload).
from alt_data_service import (  # noqa: E402  (src is on sys.path, same as context_aggregator)
    _HTTP_TIMEOUT,
    _confidence_from_signal,
    _pick_quotes,
    _score_texts,
    MassiveNewsFetcher,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Configuration — all overridable via environment; no new API key required.
# ──────────────────────────────────────────────────────────────────────────────

# Reused from the memo writer — the anthropic SDK reads ANTHROPIC_API_KEY itself.
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

_TRUTHY = {"1", "true", "yes", "on"}
WEB_RESEARCH_ENABLED: bool = os.getenv("WEB_RESEARCH_ENABLED", "true").lower() in _TRUTHY
WEB_RESEARCH_MAX_URLS: int = int(os.getenv("WEB_RESEARCH_MAX_URLS", "5"))
# Haiku is plenty for bulk extraction; the memo writer keeps Opus. scrapegraphai
# uses provider/model strings, so anthropic models are prefixed "anthropic/".
_EXTRACTION_MODEL: str = os.getenv("WEB_RESEARCH_MODEL", "anthropic/claude-haiku-4-5")

_CACHE_PATH: Path = Path("output") / "cache" / "web_research.sqlite"
_USER_AGENT: str = "TheoryY-ResearchAgent/1.0 (web-research)"

# Structural / non-content tags stripped before Markdown conversion — they carry
# zero analytical signal but a large share of the tokens in a raw page.
_STRIP_TAGS: List[str] = [
    "script", "style", "nav", "header", "footer", "aside",
    "svg", "noscript", "form", "iframe", "button",
]

# Per-ticker forum / message-board seed URLs. EXTENSION POINT: list only public
# sources you are authorized to scrape. The change-detection cache keeps the
# request volume against any listed site minimal on recurring runs.
WEB_RESEARCH_SEEDS: Dict[str, List[str]] = {}


def _is_real_key(key: str) -> bool:
    """
    True only for a usable Anthropic key. Rejects the empty default AND the
    `sk-ant-...` placeholder shipped in .env.example, so a project that never set a
    real key falls back to the zero-cost lexical extractor instead of firing doomed
    API calls on every memo run.
    """
    return bool(key) and "..." not in key and len(key) >= 20


# ──────────────────────────────────────────────────────────────────────────────
# Domain models
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ScrapedPage:
    """One scraped URL: its extracted rows plus whether the LLM was skipped."""
    url:        str
    kind:       str               # "news" | "forum"
    from_cache: bool              # True → extraction reused, LLM skipped this run
    extracted:  List[Dict] = field(default_factory=list)
    error:      Optional[str] = None


@dataclass
class WebResearchSignal:
    """
    First-hand web-research sentiment for one ticker, blended across all scraped
    forum posts and news article bodies. `available=False` + `error` marks a stub
    (scrapegraphai/key absent, disabled, or no targets) so the memo writer can hedge.
    """
    ticker:          str
    company_name:    str
    sources_scraped: List[Dict[str, object]]      # [{url, kind, from_cache}]
    post_count:      int                          # scored text fragments across pages
    sentiment:       Optional[str]                # "positive" | "mixed" | "negative" | None
    sentiment_score: Optional[float]              # -1.0 … 1.0 (smoothed lexicon blend)
    top_themes:      List[str]
    top_quotes:      List[Dict[str, str]]         # [{"source": ..., "text": ...}]
    confidence:      Optional[str]                # "low" | "medium" | "high" | None
    extraction_mode: Optional[str] = None         # "llm" (scrapegraphai) | "lexical" | None
    forum_posts:     List[Dict] = field(default_factory=list)   # uniform → TOON-encoded by caller
    news_extracts:   List[Dict] = field(default_factory=list)   # uniform → TOON-encoded by caller
    available:       bool = True
    error:           Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# 1. HTML filtering & Markdown conversion
# ──────────────────────────────────────────────────────────────────────────────

class CleanMarkdownConverter:
    """
    Fetches a page with a conditional GET and converts the structural HTML to
    Markdown after stripping non-content tags. `markdownify` is used when present;
    otherwise it degrades to BeautifulSoup text extraction (bs4 is already a dep).
    """

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    def fetch_clean(
        self,
        url: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> Tuple[Optional[str], Dict[str, Optional[str]]]:
        """
        Conditional GET for *url*. Returns (markdown, meta).

        markdown is None when the server replies 304 Not Modified (meta["status"] ==
        "304") or on any network/HTTP error (meta["error"] set). meta carries the
        fresh ETag / Last-Modified for the cache to persist.
        """
        headers: Dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        try:
            resp = self._session.get(url, headers=headers, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("web_research fetch failed for %s: %s", url, exc)
            return None, {"status": None, "error": str(exc), "etag": etag, "last_modified": last_modified}

        meta: Dict[str, Optional[str]] = {
            "status": str(resp.status_code),
            "etag": resp.headers.get("ETag", etag),
            "last_modified": resp.headers.get("Last-Modified", last_modified),
            "error": None,
        }
        if resp.status_code == 304:
            return None, meta
        try:
            resp.raise_for_status()
        except requests.RequestException as exc:
            meta["error"] = str(exc)
            return None, meta
        return self.html_to_markdown(resp.text), meta

    @staticmethod
    def html_to_markdown(html: str) -> str:
        """Strip non-content tags + comments, then convert remaining HTML to Markdown."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(_STRIP_TAGS):
            tag.decompose()
        for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
            comment.extract()
        root = soup.body or soup
        try:
            from markdownify import markdownify as _markdownify
            md = _markdownify(str(root), heading_style="ATX", strip=["img"])
        except Exception:  # markdownify missing or chokes → plain-text fallback
            md = root.get_text(separator="\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", md).strip()


# ──────────────────────────────────────────────────────────────────────────────
# 2. Incremental runs / change detection
# ──────────────────────────────────────────────────────────────────────────────

class ChangeDetectionCache:
    """
    SQLite-backed page cache (stdlib sqlite3, no new dependency). Stores the last
    content hash, validators (ETag / Last-Modified), and the extracted rows so an
    unchanged page can reuse its extraction and skip the LLM entirely.
    """

    def __init__(self, path: Path = _CACHE_PATH) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                    url            TEXT PRIMARY KEY,
                    content_hash   TEXT,
                    etag           TEXT,
                    last_modified  TEXT,
                    extracted_json TEXT,
                    fetched_at     TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._path))

    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, url: str) -> Optional[Dict]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT content_hash, etag, last_modified, extracted_json, fetched_at "
                "FROM pages WHERE url = ?",
                (url,),
            ).fetchone()
        if not row:
            return None
        return {
            "content_hash": row[0],
            "etag": row[1],
            "last_modified": row[2],
            "extracted": json.loads(row[3]) if row[3] else [],
            "fetched_at": row[4],
        }

    def put(
        self,
        url: str,
        content_hash: str,
        etag: Optional[str],
        last_modified: Optional[str],
        extracted: List[Dict],
    ) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO pages (url, content_hash, etag, last_modified, extracted_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    content_hash   = excluded.content_hash,
                    etag           = excluded.etag,
                    last_modified  = excluded.last_modified,
                    extracted_json = excluded.extracted_json,
                    fetched_at     = excluded.fetched_at
                """,
                (
                    url,
                    content_hash,
                    etag,
                    last_modified,
                    json.dumps(extracted, default=str),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


# ──────────────────────────────────────────────────────────────────────────────
# 3. LLM extraction via ScrapeGraphAI (degrades to stub when unavailable)
# ──────────────────────────────────────────────────────────────────────────────

class ScrapeGraphExtractor:
    """
    Wraps scrapegraphai's SmartScraperGraph with a fixed extraction prompt. The
    *pre-cleaned Markdown* is passed as the graph source, so scrapegraphai runs only
    its LLM extraction step and skips its own browser fetch (no Playwright needed for
    static pages — JS-heavy forums are a documented extension point).
    """

    _FORUM_PROMPT = (
        "This is a discussion forum or message board page. Extract the individual "
        "user posts or comments that discuss the company, its products, hiring, or "
        "outlook. Return a JSON object with a 'posts' array; each post has: "
        "'author' (or null), 'date' (or null), and 'text' (the post body). "
        "Ignore navigation, advertisements, signatures, and unrelated chatter."
    )
    _NEWS_PROMPT = (
        "This is a news article about a company. Return a JSON object with: "
        "'headline' (string), 'key_points' (array of the main factual statements), "
        "and 'stance' (one of 'positive', 'neutral', 'negative' toward the company)."
    )

    def __init__(self, api_key: str = ANTHROPIC_API_KEY, model: str = _EXTRACTION_MODEL) -> None:
        self._api_key = api_key
        self._model = model

    @property
    def is_available(self) -> bool:
        """True only when a real Claude key is set AND scrapegraphai is importable."""
        if not _is_real_key(self._api_key):
            return False
        try:
            import scrapegraphai  # noqa: F401
            return True
        except ImportError:
            return False

    def extract(self, markdown: str, kind: str) -> List[Dict]:
        """Run the scraper over pre-cleaned *markdown*; return a list of row dicts."""
        from scrapegraphai.graphs import SmartScraperGraph

        prompt = self._FORUM_PROMPT if kind == "forum" else self._NEWS_PROMPT
        config = {
            # NB: keep this dict to keys scrapegraphai consumes — unknown keys (e.g.
            # model_tokens) are forwarded to the Anthropic client and raise TypeError.
            # The "default token size 8192" warning is benign for our small inputs.
            "llm": {"api_key": self._api_key, "model": self._model, "max_tokens": 2000},
            "headless": False,
            "verbose": False,
        }
        graph = SmartScraperGraph(prompt=prompt, source=markdown, config=config)
        return self._normalize(graph.run(), kind)

    @staticmethod
    def _normalize(result: object, kind: str) -> List[Dict]:
        """Coerce scrapegraphai's heterogeneous output into a list of row dicts."""
        if isinstance(result, dict):
            # Forum prompt returns {"posts": [...]}; news returns a single object.
            for value in result.values():
                if isinstance(value, list):
                    return [r for r in value if isinstance(r, dict)]
            return [result] if kind == "news" else []
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict)]
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Processor — blends scraped text using the shared lexicon scorer
# ──────────────────────────────────────────────────────────────────────────────

class WebResearchProcessor:
    """Pure logic: turn scraped pages into a WebResearchSignal via the shared scorer."""

    def process(
        self, ticker: str, company_name: str, pages: List[ScrapedPage]
    ) -> WebResearchSignal:
        forum_posts: List[Dict] = []
        news_extracts: List[Dict] = []
        texts: List[str] = []
        sources_scraped: List[Dict[str, object]] = []

        for page in pages:
            sources_scraped.append(
                {"url": page.url, "kind": page.kind, "from_cache": page.from_cache}
            )
            if page.error:
                continue
            for row in page.extracted:
                if page.kind == "forum":
                    body = str(row.get("text") or "").strip()
                    if body:
                        texts.append(body)
                        # Score on full text above; store a trimmed copy to keep the
                        # token-optimized payload small.
                        forum_posts.append({
                            "author": row.get("author"),
                            "date": row.get("date"),
                            "text": body[:300],
                        })
                else:
                    headline = str(row.get("headline") or "").strip()
                    points = row.get("key_points") or []
                    if not isinstance(points, list):
                        points = [str(points)]
                    if headline:
                        texts.append(headline)
                    texts.extend(str(p) for p in points)        # full points feed the score
                    news_extracts.append({                       # …only a capped slice is stored
                        "headline": headline[:200],
                        "stance": row.get("stance"),
                        "key_points": [str(p)[:200] for p in points[:4]],
                    })

        score, freq, signal_count = _score_texts(texts)
        # Same thresholds the consumer-sentiment blender uses (alt_data_service._blend).
        if score is None:
            label: Optional[str] = None
        elif score > 0.2:
            label = "positive"
        elif score < -0.2:
            label = "negative"
        else:
            label = "mixed"

        name_tokens = set(re.findall(r"[a-z]{3,}", company_name.lower()))
        name_tokens.add(ticker.lower())
        themes = [
            w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])
            if w not in name_tokens
        ][:5]
        quotes = [{"source": "web_research", "text": q} for q in _pick_quotes(texts, n=5)]

        return WebResearchSignal(
            ticker=ticker,
            company_name=company_name,
            sources_scraped=sources_scraped,
            post_count=len(texts),
            sentiment=label,
            sentiment_score=score,
            top_themes=themes,
            top_quotes=quotes,
            confidence=_confidence_from_signal(signal_count),
            forum_posts=forum_posts,
            news_extracts=news_extracts,
            available=bool(texts),
            error=None if texts else "no web-research content extracted",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Façade
# ──────────────────────────────────────────────────────────────────────────────

class WebResearchService:
    """
    High-level orchestrator. Resolves target URLs (curated forum seeds + the news
    article URLs Massive/Polygon already returns), then for each: conditional fetch
    → Markdown clean → change-detection → LLM extraction (only when changed) →
    blended signal. All collaborators are constructor-injected for testability.
    """

    def __init__(
        self,
        converter:    Optional[CleanMarkdownConverter] = None,
        cache:        Optional[ChangeDetectionCache]   = None,
        extractor:    Optional[ScrapeGraphExtractor]   = None,
        processor:    Optional[WebResearchProcessor]   = None,
        news_fetcher: Optional[MassiveNewsFetcher]     = None,
        seeds:        Dict[str, List[str]]             = WEB_RESEARCH_SEEDS,
        max_urls:     int                              = WEB_RESEARCH_MAX_URLS,
    ) -> None:
        self._conv      = converter    or CleanMarkdownConverter()
        self._cache     = cache        or ChangeDetectionCache()
        self._extractor = extractor    or ScrapeGraphExtractor()
        self._processor = processor    or WebResearchProcessor()
        self._news      = news_fetcher or MassiveNewsFetcher()
        self._seeds     = seeds
        self._max_urls  = max_urls

    def get_web_research(self, ticker: str, company_name: str) -> WebResearchSignal:
        if not WEB_RESEARCH_ENABLED:
            return self._stub(ticker, company_name, "web research disabled (WEB_RESEARCH_ENABLED=false)")
        targets = self._resolve_targets(ticker, company_name)
        if not targets:
            return self._stub(ticker, company_name, "no web-research targets resolved for this ticker")
        # LLM extraction (scrapegraphai) when a real key is present; otherwise fall
        # back to zero-cost lexical scoring of the cleaned page text — the feature
        # still works (full article bodies + forums) without any API key or cost.
        use_llm = self._extractor.is_available
        pages = [self._scrape_one(url, kind, use_llm) for url, kind in targets]
        signal = self._processor.process(ticker, company_name, pages)
        signal.extraction_mode = "llm" if use_llm else "lexical"
        return signal

    # ── private ───────────────────────────────────────────────────────────────

    def _resolve_targets(self, ticker: str, company_name: str) -> List[Tuple[str, str]]:
        targets: List[Tuple[str, str]] = [
            (url, "forum") for url in self._seeds.get(ticker.upper(), [])
        ]
        try:
            news = self._news.fetch(ticker)
            for article in news.articles:
                url = getattr(article, "url", None)
                if url:
                    targets.append((url, "news"))
        except Exception as exc:
            logger.warning("news target resolution failed for %s: %s", ticker, exc)

        seen: set = set()
        deduped: List[Tuple[str, str]] = []
        for url, kind in targets:
            if url in seen:
                continue
            seen.add(url)
            deduped.append((url, kind))
            if len(deduped) >= self._max_urls:
                break
        return deduped

    @staticmethod
    def _lexical_rows(markdown: str, kind: str) -> List[Dict]:
        """
        No-LLM extraction: split cleaned Markdown into prose rows for the lexicon
        scorer. Scoring full article bodies / forum text is richer signal than the
        RSS-headline sources the engine already has, at zero API cost.
        """
        def _scrub(line: str) -> str:
            line = re.sub(r"[#>*_`\[\]()|-]+", " ", line)
            line = re.sub(r"\b\w{25,}\b", " ", line)          # long tracking tokens / URL gibberish
            # Mixed digit+letter tokens (IDs like "6j4b", "n0ANQri9nUE"); keeps pure
            # numbers ("2025", "192") and plain words.
            line = re.sub(r"\b(?=\w*\d)(?=\w*[A-Za-z])\w{4,}\b", " ", line)
            return re.sub(r"\s+", " ", line).strip()

        chunks = [_scrub(line) for line in re.split(r"\n{2,}|\n", markdown)]
        chunks = [c for c in chunks if len(c) >= 40][:25]
        if not chunks:
            return []
        if kind == "forum":
            return [{"author": None, "date": None, "text": c} for c in chunks]
        return [{"headline": chunks[0], "stance": None, "key_points": chunks[1:13] or chunks}]

    def _scrape_one(self, url: str, kind: str, use_llm: bool) -> ScrapedPage:
        cached = self._cache.get(url)
        etag = cached.get("etag") if cached else None
        last_modified = cached.get("last_modified") if cached else None

        markdown, meta = self._conv.fetch_clean(url, etag, last_modified)

        # 304 Not Modified → reuse the stored extraction, skip the LLM.
        if meta.get("status") == "304" and cached:
            logger.info("web_research: 304 unchanged, reused extraction (LLM skipped): %s", url)
            return ScrapedPage(url, kind, from_cache=True, extracted=cached["extracted"])

        if markdown is None:
            return ScrapedPage(url, kind, from_cache=False, extracted=[],
                               error=meta.get("error") or "fetch failed")

        content_hash = ChangeDetectionCache.hash_text(markdown)
        if cached and cached.get("content_hash") == content_hash:
            logger.info("web_research: content hash unchanged, reused extraction (LLM skipped): %s", url)
            # Refresh validators so the next run can use a 304 short-circuit.
            self._cache.put(url, content_hash, meta.get("etag"), meta.get("last_modified"), cached["extracted"])
            return ScrapedPage(url, kind, from_cache=True, extracted=cached["extracted"])

        try:
            rows = (
                self._extractor.extract(markdown, kind) if use_llm
                else self._lexical_rows(markdown, kind)
            )
        except Exception as exc:
            logger.error("web_research extraction failed for %s: %s", url, exc)
            return ScrapedPage(url, kind, from_cache=False, extracted=[], error=str(exc))

        self._cache.put(url, content_hash, meta.get("etag"), meta.get("last_modified"), rows)
        return ScrapedPage(url, kind, from_cache=False, extracted=rows)

    @staticmethod
    def _stub(ticker: str, company_name: str, reason: str) -> WebResearchSignal:
        return WebResearchSignal(
            ticker=ticker,
            company_name=company_name,
            sources_scraped=[],
            post_count=0,
            sentiment=None,
            sentiment_score=None,
            top_themes=[],
            top_quotes=[],
            confidence=None,
            available=False,
            error=reason,
        )
