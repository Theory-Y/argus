# src/

Core data pipeline for TheoryY Argus: an MCP server that fetches, blends, and
minifies financial + alternative data into a single LLM-ready context payload,
which the `theory-y-memo` Claude skill then writes into an institutional
equity research memo. Everything here runs locally over stdio — there is no
HTTP server, no SaaS layer, and no deployment step.

## Overview

`mcp_server.py` is the entry point: it starts a `FastMCP` server exposing
three tools (`build_company_context`, `generate_sector_sheet`,
`list_supported_tickers`) over stdio. `fetch_context.py` is a CLI that
connects to that server as an MCP client, calls `build_company_context`, and
writes the resulting JSON to `output/context/context_TICKER.json`. The Claude
skill invokes `fetch_context.py` to get deterministic data, then writes the
memo prose itself — there is no LLM call inside `src/`.

## Directory Structure

| File | Purpose |
|---|---|
| [mcp_server.py](./mcp_server.py) | FastMCP server. Loads `.env`, wires up shared `FinancialService` / `AltDataService` / `ContextAggregator` instances once, and exposes the three MCP tools. Entry point (`python src/mcp_server.py`, stdio transport). |
| [financial_service.py](./financial_service.py) | Valuation engine on `yfinance` (no API key). Clean-architecture layering: `FinancialDataFetcher` (I/O) → `FinancialDataTransformer` (domain/ratio math) → `FinancialExporter` (CSV/DataFrame) → `FinancialService` façade. Also owns `SECTOR_TICKERS`, the default seed universe. |
| [alt_data_service.py](./alt_data_service.py) | Alternative/macro signal engine: Google Trends, FRED, SEC EDGAR (10-K risk snippet + 8-K feed), Apify job-market stub, and a blended `MultiSourceSentimentAggregator` (Stocktwits, Yahoo RSS, Hacker News, Reddit fallback) plus Massive/Polygon news & price fetchers. Loads `.env` at import time via `load_dotenv`, so consumers must set env vars before importing it. |
| [web_research_service.py](./web_research_service.py) | ScrapeGraphAI-based first-hand web research: full news-article bodies and niche forum discussion, filtered for ticker relevance. Optimized for repeat runs via HTML→Markdown cleaning, a sqlite change-detection cache (conditional GET + content hash), and compact serialization. |
| [taxonomy.py](./taxonomy.py) | Single source of truth for the SEC 8-K item-code taxonomy (label, category, materiality tier S/A/B/C) and the material-event predicate vocabulary. Supersedes the older `_8K_ITEM_LABELS` dict once embedded in `alt_data_service.py`. |
| [chart_service.py](./chart_service.py) | Dependency-free inline SVG chart builders (price history, valuation comps, margins, search trends, sentiment, revenue/valuation history) for the PDF memo. Every builder returns a `<figure class="chart">…</figure>` fragment and never raises — a missing/malformed signal degrades to an "unavailable" figure instead of aborting the memo. Referenced from memo prose via `[[chart:NAME]]` tokens. |
| [context_aggregator.py](./context_aggregator.py) | Composes `FinancialService` + `AltDataService` output into one minified JSON payload (`meta`, `target`, `peers`, `alt_signals`, …) for the LLM. Owns `COMPETITOR_MAP`, the curated hand-tuned peer overrides, and falls back to dynamic Polygon related-companies discovery for any ticker not in the map. |
| [fetch_context.py](./fetch_context.py) | CLI (`python src/fetch_context.py TICKER`). Spawns `mcp_server.py` as an MCP stdio client, calls `build_company_context`, and writes the payload to `output/context/context_TICKER.json`. The only part of the pipeline invoked as a script rather than imported. |

## Usage

```bash
# Start the MCP server directly (stdio transport; normally launched by an MCP client)
.venv/bin/python3 src/mcp_server.py

# Fetch a context payload for a ticker (spawns mcp_server.py as a client)
.venv/bin/python3 src/fetch_context.py PCOR
# → writes output/context/context_PCOR.json

# Generate a sector comps CSV without going through MCP
.venv/bin/python3 -c "
from financial_service import FinancialService
FinancialService().export_sector_sheet(['NVDA', 'XOM', 'JPM'], 'output/TheoryY_Sector_Sheet.csv')
"
```

## Conventions & Good Practices

- **Bare intra-`src` imports.** Modules import siblings as `from financial_service import ...` / `from alt_data_service import ...`, not `from src.financial_service import ...` — `src/` is expected to be importable directly (e.g. on `sys.path`), matching how `mcp_server.py` and `fetch_context.py` run it. `alt_data_service.py` is the one exception, importing the shared taxonomy as `from src.taxonomy import ...`.
- **`.env` loading.** `.env` (project root) is loaded explicitly, not assumed to be pre-sourced: `mcp_server.py` loads it before importing the data services (which read `FRED_API_KEY` / `SEC_USER_AGENT` / `APIFY_API_KEY` at import time), and `alt_data_service.py` also calls `load_dotenv` itself as a safety net for direct/test imports.
- **Graceful degradation over exceptions.** Individual signal fetchers (alt-data sources, chart builders) catch their own failures and return `{"error": "..."}` / an "unavailable" fragment rather than raising, so one bad data source never aborts the whole context payload or memo.
- **Shared service instances.** `mcp_server.py` constructs `FinancialService`, `AltDataService`, and `ContextAggregator` once at module load and reuses them across all tool calls, preserving caches (e.g. SEC CIK resolution) and HTTP sessions.
- **Clean layering in `financial_service.py`.** New yfinance fields go in the `Fetcher`; new ratios/derived metrics go in the `Transformer`; keep I/O out of transform logic.

## Dependencies & Relationships

- **Depends on:** `.env` (root) for `FRED_API_KEY`, `SEC_USER_AGENT`, `APIFY_API_KEY`, `MASSIVE_API_KEY`, `ANTHROPIC_API_KEY`; external services yfinance, FRED, SEC EDGAR, GlobeNewswire RSS, Stanford SCAC, Stocktwits/Yahoo/HN/Reddit, Massive/Polygon, and (for `web_research_service.py`) ScrapeGraphAI against the project's Anthropic key.
- **Depended on by:** `.claude/skills/theory-y-memo/SKILL.md` invokes `fetch_context.py` to obtain the context JSON; `core/memo/writer.py` and `core/memo/prompt.py` consume that payload (and reference `chart_service.py` chart tokens) to write the memo; `scripts/client-mcp.py` is a standalone test client for the MCP tools; `tests/` unit-tests the pure-logic parts of these modules with no network calls.

## Notes / Gotchas

- `generate_sector_sheet` allows unrecognized tickers through with a warning rather than rejecting them — rows for tickers yfinance can't resolve will contain null values, not errors.
- `list_supported_tickers`'s `default_seed_universe` is **not** the set of researchable tickers; `build_company_context` works for any valid ticker, with peers resolved via `COMPETITOR_MAP` or dynamic Polygon discovery.
- Missing `FRED_API_KEY` / `SEC_USER_AGENT` puts the server in a logged "degraded mode" rather than failing startup — affected sections simply come back as errors inside the payload.
