# TheoryY Argus

An MCP server and Claude Code skill that generates institutional-grade equity research memos for **any public company in any sector**. It originated as a PropTech & Facilities tool but is now sector-agnostic: it captures each issuer's sector/industry, discovers peers dynamically, and selects a sector-appropriate macro series automatically. Point it at a ticker and get a seven-section investment memo grounded in live financial data — no fabricated numbers.

## How it works

```
Claude Code  →  /theory-y-memo TICKER
                     │
                     ▼
             fetch_context.py
                     │
                     ▼
          MCP Server (TheoryY Finance Oracle)
          ┌──────────────────────────────────┐
          │  build_company_context           │
          │    ├─ FinancialService (yfinance) │
          │    ├─ AltDataService             │
          │    │   ├─ Google Trends          │
          │    │   ├─ FRED API               │
          │    │   ├─ SEC EDGAR (10-K, 8-K)  │
          │    │   ├─ GlobeNewswire RSS      │
          │    │   └─ Stanford SCAC          │
          │    └─ ContextAggregator          │
          └──────────────────────────────────┘
                     │
                     ▼
          output/context/context_TICKER.json
                     │
                     ▼
          Five-section investment memo
          output/memos/TheoryY_Memo_TICKER.md
          output/memos/TheoryY_Memo_TICKER.pdf
```

Claude writes the memo from the fetched JSON — it never fills in financials from training memory.

## Supported tickers

**Any valid ticker, in any sector, is supported.** Peers are resolved in two tiers:

1. **Dynamic discovery (default)** — for any ticker, peers come from Polygon's
   `related-companies` endpoint (requires `MASSIVE_API_KEY`). This covers every
   sector with no hand-maintained config, and the macro series is auto-selected from
   the issuer's yfinance sector (e.g. Energy → WTI crude, Financials → Fed Funds Rate,
   Real Estate → construction spend, Tech/Industrials → industrial production).
2. **Curated overrides** — a hand-tuned peer set in `COMPETITOR_MAP`
   (`src/context_aggregator.py`) takes precedence over dynamic discovery for these names:

**PropTech & Facilities** (original universe)

| Ticker | Company | Peer Group |
|--------|---------|------------|
| CSGP | CoStar Group | CBRE, PCOR, Z |
| CBRE | CBRE Group | CSGP, HON, ABM |
| CARR | Carrier Global | TT, JCI, LII |
| TT | Trane Technologies | CARR, JCI, LII |
| JCI | Johnson Controls | CARR, TT, HON |
| LII | Lennox International | CARR, TT, JCI |
| ABM | ABM Industries | CTAS, HON, JCI |
| CTAS | Cintas | ABM, HON, ADT |
| ADT | ADT Inc. | ALLE, CTAS, HON |
| ALLE | Allegion | ADT, HON, JCI |
| HON | Honeywell | JCI, CARR, TT |
| PCOR | Procore Technologies | CSGP, APPF, Z |
| APPF | AppFolio | PCOR, CSGP, Z |
| Z | Zillow Group | CSGP, APPF, PCOR |

**Semiconductors & AI infrastructure / mega-cap tech**

| Ticker | Company | Peer Group |
|--------|---------|------------|
| NVDA | NVIDIA | AMD, AVGO, TSM |
| AMD | Advanced Micro Devices | NVDA, AVGO, INTC |
| AVGO | Broadcom | NVDA, AMD, QCOM |
| TSM | Taiwan Semiconductor | NVDA, AVGO, INTC |
| INTC | Intel | AMD, NVDA, TSM |
| MU | Micron | NVDA, AMD, TSM |
| QCOM | Qualcomm | AVGO, NVDA, AMD |
| META | Meta Platforms | GOOGL, MSFT, AMZN |

A ticker outside this list is **not** a coverage gap — its peers are discovered dynamically via Polygon. The `peers` array only comes back empty when dynamic discovery is unavailable (no `MASSIVE_API_KEY`) *and* there is no curated override; in that case the memo skill sources comparables externally. See the peer-comparison rule in `.claude/skills/theory-y-memo/SKILL.md`.

## Setup

**Prerequisites:** none — the setup script bootstraps everything automatically.
Only `curl` (or `wget`) and `bash` are required on macOS/Linux; PowerShell 5.1+ on Windows.

```bash
# macOS / Linux
bash setup.sh

# Windows
powershell -ExecutionPolicy Bypass -File setup.ps1
```

The setup script installs everything from scratch if needed:
1. **Node.js** — via [fnm](https://github.com/Schniz/fnm) (no sudo)
2. **Python 3.12** — via [uv](https://github.com/astral-sh/uv) (no sudo)
3. **pandoc** — standalone binary from GitHub releases (no sudo)
4. **Chromium** — via Playwright if no system browser is found; path written to `.env`
5. **Branded `.dotx` Word template** — generated once from pandoc defaults

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `FRED_API_KEY` | Yes | FRED macro data — free at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `SEC_USER_AGENT` | Yes | SEC EDGAR access — format: `AppName/1.0 your@email.com` |
| `APIFY_API_KEY` | No | Job-market signal (stub until configured) |

Add these to a `.env` file at the project root or export them in your shell. The server starts in degraded mode if they are missing (FRED and SEC data will be unavailable).

## Generating a memo

With Claude Code (recommended):

```
/theory-y-memo PCOR
```

You will be prompted to choose an output format (Markdown or Word), then Claude fetches live data and writes the memo.

Manually:

```bash
# 1. Fetch the context payload
.venv/bin/python3 src/fetch_context.py PCOR

# 2. The JSON is written to output/context/context_PCOR.json
```

## MCP server tools

The server exposes three tools to Claude Code via `.mcp.json`:

| Tool | Description |
|------|-------------|
| `build_company_context` | Builds a minified JSON payload (schema 1.7) for one ticker: fundamentals + sector/industry, up to 3 peers (curated or dynamically discovered), Google Trends velocity, a sector-appropriate FRED macro series (with a `relevance` flag — see below), SEC 10-K risk snippet, SEC 8-K events, press releases, litigation monitor |
| `generate_sector_sheet` | Exports a CSV of valuation metrics (Market Cap, EV, EV/Revenue, EV/EBITDA, Fwd P/E, YoY Revenue Growth) for a list of tickers |
| `list_supported_tickers` | Returns the curated peer overrides + default seed universe (any ticker works via dynamic discovery) |

## Data sources

| Source | Signal | Auth |
|--------|--------|------|
| yfinance | Fundamentals, valuation multiples | None |
| FRED API | A sector-appropriate macro series auto-selected from the issuer's sector (e.g. construction spend for Real Estate, WTI crude for Energy, Fed Funds for Financials, industrial production for Tech/Industrials, real PCE for Consumer; real GDP fallback). Tagged with a `relevance` flag — `high` when the series is a genuine sector driver, `low` (backdrop only) for the GDP fallback | Free API key |
| Polygon related-companies | Dynamic peer discovery for any ticker (used when no curated override exists) | `MASSIVE_API_KEY` |
| Google Trends (pytrends) | 12-month search-interest velocity | None |
| SEC EDGAR | 10-K Item 1A risk snippet, 8-K material events | User-Agent header |
| GlobeNewswire RSS | Last 5 press releases | None |
| Stanford SCAC | Securities class-action litigation monitor | None |
| Apify | Job-market headcount signal (stub) | Optional API key |

## Output

```
output/
  context/
    context_TICKER.json      # raw data payload (minified JSON)
  memos/
    TheoryY_Memo_TICKER.md   # seven-section investment memo
    TheoryY_Memo_TICKER.pdf  # PDF rendered via CSS or pandoc
    TheoryY_Memo_TICKER.docx # Word doc (if Word format chosen)
  TheoryY_Sector_Sheet.csv   # sector comparables table
  theme/
    reference.dotx           # branded Word style template
```

## Memo structure

Each memo has seven sections:

1. **One-Line Thesis & Valuation Snapshot** — the thesis plus multiples vs. growth, including an explicit forward-earnings bridge, a cross-sectional peer comp, and the multi-year valuation re-rating path (FY-end EV/Revenue + trailing P/E)
2. **Business Overview & Operations** — business model, multi-year revenue trajectory (FY-labeled), revenue/segment mix shift across years, cost structure, and where operating leverage sits
3. **Alternative Data & Macro Signals** — Google Trends velocity, macro backdrop, SEC filings, litigation — gated on a stated transmission mechanism
4. **Consumer & Public Opinion** — multi-source sentiment (StockTwits, Yahoo, HackerNews, news, niche forums), weighted, contextualized to the business type, with each community's focus named
5. **Key Risks & Structural Barriers** — concrete, ranked risks tied to the thesis; mandatory coverage of named competitive risk, margin compression, insider-sell clusters, and guidance credibility (8-quarter beat/miss track); never a 10-K Item 1A rehash, filings linked inline
6. **Catalyst Map — Bull & Bear Cases** — exactly 3 bull + 3 bear catalysts, each with probability, magnitude (operating terms), timing window, priced-in judgment, and the public's current reaction; closed with best-case/worst-case composites
7. **Investment Recommendation** — direction + conviction score (N/10), an entry view at the current price (no price targets), and a monitoring list of what would change the call

### Analytical rigor requirements

The memo skill enforces twelve non-negotiable rules (in `.claude/skills/theory-y-memo/SKILL.md`) that exist to prevent recurring failures: (1) bridge every valuation gap with explicit implied-earnings math; (2) always build a peer comp — source externally if `peers` is empty; (3) source segment mix from filings when the payload omits it; (4) run an internal-contradiction check before finalizing; (5) gate each macro/alt-data signal on a stated transmission mechanism (honoring the FRED `relevance` flag); (6) investigate governance/litigation signals or name the next source (proxy, PACER) rather than leaving an unexplained flag; (7) honor `data_quality` flags — never present a flagged figure as fact; (8) calibrate language strength to signal strength; (9) catalyst discipline — every catalyst sized, timed, and judged for being priced in, never via price targets; (10) key risks state the delta beyond the 10-K, with filings linked inline; (11) interpret insider-sell and earnings-surprise patterns rather than reporting them raw; (12) red-team the final call before writing it. External figures are distinguished from payload-derived ones in a closing Sourcing note.

## Project structure

```
src/
  mcp_server.py          # FastMCP server — exposes 3 tools
  financial_service.py   # yfinance layer (fetcher → transformer → exporter → façade)
  alt_data_service.py    # alternative data engine (FRED, Trends, SEC, Apify, etc.)
  context_aggregator.py  # composes both services into a single LLM payload
  fetch_context.py       # CLI script: calls mcp_server via stdio, writes context JSON
scripts/
  build_reference_dotx.py  # generates branded Word .dotx template
  export_pdf.py            # PDF export via md-to-pdf (CSS theme)
  client-mcp.py            # standalone MCP client for testing
tests/
  test_all.py              # unit tests for pure-logic components
```

## Running tests

```bash
.venv/bin/python3 -m unittest tests.test_all -v
```

Tests cover pure-logic components only — no network calls, no external API dependencies. (The venv ships `unittest`, not `pytest`.)

---

## Selling this as a service

The repo can run as a managed service without exposing the research engine. The
design keeps one hard boundary: the **client** speaks only HTTP and contains no
proprietary logic, so it is safe to distribute, while the **engine + memo prompt**
stay behind the server. A single `AUTH_MODE` env var flips the business model.

```
external client (separate repo)  ──HTTP──▶  server/ (FastAPI)  ──▶  core/ + src/ (engine, hidden prompt)
                                                                 └─▶  Anthropic API (writes the memo)
```

The client (CLI + web, zero IP — it speaks only HTTP) lives in its own repository.

| Layer | Path | Role |
|-------|------|------|
| Engine façade, hidden prompt, Anthropic writer, render | `core/` | Proprietary — server-side only in SaaS |
| API (auth, billing, jobs, storage) | `server/` | Run by you (SaaS) or the buyer (self-host) |
| Deploy + packaging | `infra/` | Dockerfile, compose, `PACKAGING.md` |

**Two modes, one codebase** (`AUTH_MODE`):
- `license` — offline license-key check, no billing. For **source-sale / self-host**.
- `saas` — DB-backed API keys + Stripe quota; the memo is written server-side via the
  Anthropic API, so the prompt never leaves your servers.

Run it locally (license mode):

```bash
pip install -r requirements.txt -r server/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # plus FRED_API_KEY / SEC_USER_AGENT
uvicorn server.app:app --reload            # http://localhost:8000
```

Or the whole stack via Docker: `docker compose -f infra/docker-compose.yml up --build`.
See `infra/PACKAGING.md` for exactly what ships in a source sale vs a SaaS deploy.

---

## Additional Features

Planned extensions that are not yet implemented. Contributions welcome.

### Multi-source sentiment aggregator

Replace the single Reddit signal with parallel fetches across Trustpilot, G2, Glassdoor, and news sentiment:

```python
class ConsumerSentimentService:
    def __init__(self):
        self.trustpilot = TrustpilotFetcher()   # general consumer reviews (free API tier)
        self.g2         = G2Fetcher()            # B2B SaaS reviews — relevant for PCOR, APPF, CSGP, Z
        self.glassdoor  = GlassdoorFetcher()     # employee sentiment as a culture/morale signal
        self.news       = NewsSentimentAnalyzer() # press tone from RSS/news APIs

    def get_sentiment_profile(self, ticker: str) -> ConsumerSentimentProfile:
        """Aggregate sentiment across all sources with per-source weighting."""
```

Example payload shape:
```json
{
  "consumer_reviews": {
    "trustpilot": { "rating": 4.1, "review_count": 312, "top_themes": ["support", "pricing"] },
    "g2":         { "rating": 4.4, "review_count": 890, "top_themes": ["ease of use", "integrations"] }
  },
  "employee_sentiment": {
    "glassdoor":  { "rating": 3.8, "review_count": 1200, "culture_score": 3.6 }
  },
  "news_sentiment": {
    "net_sentiment": "positive",
    "tone_trend": "improving",
    "recent_headlines": ["Company beats Q3 estimates", "New partnership announced"]
  },
  "aggregate_sentiment": "mixed"
}
```

Required additions: `TRUSTPILOT_API_KEY` (free), `G2_API_KEY` (free), `GLASSDOOR_API_KEY` env vars.

---

### Reddit + PRAW deep sentiment

Use the official [PRAW](https://praw.readthedocs.io/) library for richer access: threaded comments, upvote ratios, post flair, and subreddit-level volume trends over time. Requires a Reddit app (free OAuth credentials at reddit.com/prefs/apps).

```python
import praw

reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    user_agent="TheoryY-ResearchAgent/1.0",
)

def get_deep_sentiment(ticker: str, lookback_days: int = 90) -> RedditDeepSignal:
    """
    Fetches post + comment data from r/investing, r/stocks, and sector subreddits.
    Returns volume trend, upvote-weighted sentiment, and top comment themes.
    """
```

Advantages over the current public JSON approach:
- Access to comment bodies (not just post titles) for richer sentiment
- Upvote ratio as a quality-weight for each post
- Historical volume trend (mentions per week over 90 days) as a momentum signal
- No rate-limit issues at scale

Required additions: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` env vars.
