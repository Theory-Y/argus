# TheoryY Middle-Market Research Agent

An MCP server and Claude Code skill that generates institutional-grade equity research memos for PropTech & Facilities companies. Point it at a ticker and get a five-section investment memo grounded in live financial data — no fabricated numbers.

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

14 pre-configured PropTech & Facilities names with peer mappings:

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

Any ticker outside this list can still be queried — it will have an empty peers list.

## Setup

**Prerequisites:** Python ≥ 3.10, Node.js, pandoc, Chromium/Chrome (for PDF rendering).

```bash
# macOS / Linux
npm run setup          # or: bash setup.sh

# Windows
npm run setup:win      # or: powershell -ExecutionPolicy Bypass -File setup.ps1
```

The setup script:
1. Installs Node dependencies (`md-to-pdf`)
2. Creates a Python virtual environment and installs `requirements.txt`
3. Installs pandoc if missing
4. Installs Chromium if no compatible browser is found
5. Generates the branded `.dotx` Word template

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
| `build_company_context` | Builds a minified JSON payload for one ticker: fundamentals, 3 peers, Google Trends velocity, FRED macro, SEC 10-K risk snippet, SEC 8-K events, press releases, litigation monitor |
| `generate_sector_sheet` | Exports a CSV of valuation metrics (Market Cap, EV, EV/Revenue, EV/EBITDA, Fwd P/E, YoY Revenue Growth) for a list of tickers |
| `list_supported_tickers` | Returns the pre-configured ticker universe and competitor mappings |

## Data sources

| Source | Signal | Auth |
|--------|--------|------|
| yfinance | Fundamentals, valuation multiples | None |
| FRED API | Commercial construction spending (TLNRESCONS) | Free API key |
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
    TheoryY_Memo_TICKER.md   # five-section investment memo
    TheoryY_Memo_TICKER.pdf  # PDF rendered via CSS or pandoc
    TheoryY_Memo_TICKER.docx # Word doc (if Word format chosen)
  TheoryY_Sector_Sheet.csv   # sector comparables table
  theme/
    reference.dotx           # branded Word style template
```

## Memo structure

Each memo has five sections:

1. **Business Overview** — what the company does, market position, revenue model
2. **Financial Snapshot** — key metrics pulled directly from the context payload
3. **Competitive Landscape** — peer comparison using the pre-configured comparables
4. **Alternative Signal Review** — Google Trends velocity, macro backdrop, SEC filings, litigation, press releases
5. **Investment Considerations** — risks and potential catalysts grounded in the data

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
.venv/bin/python3 -m pytest tests/
```

Tests cover pure-logic components only — no network calls, no external API dependencies.

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
