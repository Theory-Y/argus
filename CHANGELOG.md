# Changelog

All notable changes to the TheoryY Middle-Market Research Agent are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
