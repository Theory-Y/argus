# Changelog

All notable changes to TheoryY Argus are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 2026-07-29

Reverted to the pre-pivot architecture and stripped the project back to a
local-only engine: MCP data layer + memo engine + Claude skill + PDF export.

### Removed
- **Claim-store pivot**: all post-pivot work (claim store, ingestion pipeline,
  verify routes, embeddings, trust jobs, SPA) stays on `main`; this branch
  resumes from the last pre-pivot commit with non-pivot improvements
  cherry-picked (web-research filtering, financial aggregation, memo format,
  8-K taxonomy).
- **SaaS mode**: Stripe billing, accounts, JWT sessions, and their DB tables.
- **HTTP service + deployment**: `server/` (FastAPI), `infra/` (Docker,
  packaging, Cloudflare gateway docs), `SERVICE_ARCHITECTURE.md`.
- **Dangling engine glue**: `core/engine.py`, `core/render.py` (server-only);
  `core/memo` (prompt + Anthropic writer) remains.

### Changed
- README rewritten for the local-only layout; per-folder READMEs added
  (`src/`, `core/`, `scripts/`, `tests/`).
- `.env.example` trimmed to engine/data-source/export variables.
- `output/cache/` is no longer tracked in git.

## [1.2.0] — 2026-06-03

Adds first-hand web research, full memo localization (zh/es/fr) with CJK
rendering, and a ~40% cut in subagent token cost.

### Added
- **First-hand web research** (`src/web_research_service.py`): ScrapeGraphAI-backed
  retrieval with a persistent SQLite cache (`output/cache/web_research.sqlite`) and
  API-key management, feeding live qualitative evidence into the memo pipeline.
- **Memo localization**: the `theory-y-localize` skill and `theory-y-translator`
  agent translate finished English memos into Mandarin, Spanish, and French, backed
  by per-language institutional glossaries (`localization/glossary.{zh,es,fr}.md`).
  Ships localized memos for CVX (es/fr/zh) and NVDA (es/zh).
- **CJK language support** in PDF export and chart rendering.
- **`.env.example`** documenting all configuration and API keys for setup.

### Changed
- **~40% token reduction** by sanitizing subagent context windows, model, and tools
  (`theory-y-memo` skill and memo prompt).
- Reworked `setup.sh` / `setup.ps1` for a more robust install and dependency flow.
- Enhanced PDF export and chart-rendering pipeline.

### Security
- JWT secret validation for SaaS mode in server settings (`server/config.py`),
  failing fast on missing/weak secrets.

### Tests
- 105 passing test functions, including a new `tests/test_web_research.py` suite.

## [1.1.0] — 2026-06-01

### Added
- **Massive/Polygon MCP integration** (`.mcp.json`, `scripts/run_massive_mcp.sh`)
  for real-time and historical news sentiment and price metrics.
- Investment memo and context data for **Chevron (CVX)**.

### Changed
- Generalized market-research sector coverage beyond B2B Proptech.
- Improved sentiment analysis and data-quality checks across the data services.
- Memo formatting: numbered table captions and PDF-export refinements.

## [1.0.1] — 2026-05-29

### Changed
- Enhanced investment-memo formatting (numbered table captions) and PDF export.

## [1.0.0] — 2026-05-29

First stable release. Generates institutional-grade, six-section equity research
memos for a given ticker from live financial data and alternative signals — no
fabricated numbers.

### Added
- **MCP server** (`src/mcp_server.py`) exposing `build_company_context`,
  `generate_sector_sheet`, and `list_supported_tickers`.
- **Deterministic data layer**: `FinancialService` (yfinance), `AltDataService`
  (Google Trends, FRED, SEC EDGAR 10-K/8-K, GlobeNewswire RSS, Stanford SCAC),
  multi-source consumer-sentiment aggregation, and `ContextAggregator` with
  per-sector peer mappings.
- **Memo engine** (`core/`) and the `theory-y-memo` Claude Code skill that writes
  the five analytical sections from the fetched JSON payload.
- **Data-driven SVG charts** (`src/chart_service.py`): dependency-free, inline-SVG
  figures for price history (with moving average), valuation comps, margins &
  growth, search-interest gauge, and per-source sentiment. Embedded in memos via
  `[[chart:NAME]]` tokens and rendered at PDF-export time; every builder degrades
  gracefully to an "unavailable" note rather than failing the export.
- **PDF/DOCX export** (`scripts/export_pdf.py`) via a `.dotx` + headless-Chromium
  pipeline, with `--context`, `--no-charts`, and `--skip-docx` flags.
- **Service layer** (`server/`): FastAPI app with auth (license + SaaS), Stripe
  billing, background job queue, and SQLAlchemy persistence.
- **Clients**: Python CLI (`client/python`) and React/Vite web UI (`client/web`).
- **Infra**: Docker Compose, server Dockerfile, and packaging docs (`infra/`).

### Changed
- Reorganized generated context payloads under `output/context/`.

### Tests
- 64 passing tests across the chart engine, memo writer, and core data services.
