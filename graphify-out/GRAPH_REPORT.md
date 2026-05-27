# Graph Report - .  (2026-05-27)

## Corpus Check
- Corpus is ~22,505 words - fits in a single context window. You may not need a graph.

## Summary
- 427 nodes · 816 edges · 44 communities (38 shown, 6 thin omitted)
- Extraction: 77% EXTRACTED · 23% INFERRED · 0% AMBIGUOUS · INFERRED: 190 edges (avg confidence: 0.5)
- Token cost: 45,021 input · 1,583 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Alt Data Service Core|Alt Data Service Core]]
- [[_COMMUNITY_Alt Data Processors|Alt Data Processors]]
- [[_COMMUNITY_FRED API Integration|FRED API Integration]]
- [[_COMMUNITY_Financial Data Service|Financial Data Service]]
- [[_COMMUNITY_Context Aggregation Layer|Context Aggregation Layer]]
- [[_COMMUNITY_Agent Orchestration|Agent Orchestration]]
- [[_COMMUNITY_AAPL Valuation Targets|AAPL Valuation Targets]]
- [[_COMMUNITY_ASTS Valuation Targets|ASTS Valuation Targets]]
- [[_COMMUNITY_MCP Server Interface|MCP Server Interface]]
- [[_COMMUNITY_POET Valuation Targets|POET Valuation Targets]]
- [[_COMMUNITY_Claude Configuration|Claude Configuration]]
- [[_COMMUNITY_POET Company Context|POET Company Context]]
- [[_COMMUNITY_AAPL Alt Signals|AAPL Alt Signals]]
- [[_COMMUNITY_AAPL Google Trends|AAPL Google Trends]]
- [[_COMMUNITY_ASTS Alt Signals|ASTS Alt Signals]]
- [[_COMMUNITY_ASTS Google Trends|ASTS Google Trends]]
- [[_COMMUNITY_POET Google Trends|POET Google Trends]]
- [[_COMMUNITY_MCP Client Agent|MCP Client Agent]]
- [[_COMMUNITY_AAPL Macro FRED Data|AAPL Macro FRED Data]]
- [[_COMMUNITY_ASTS Macro FRED Data|ASTS Macro FRED Data]]
- [[_COMMUNITY_POET Macro FRED Data|POET Macro FRED Data]]
- [[_COMMUNITY_AAPL Job Market Data|AAPL Job Market Data]]
- [[_COMMUNITY_AAPL Litigation Data|AAPL Litigation Data]]
- [[_COMMUNITY_AAPL Press Releases|AAPL Press Releases]]
- [[_COMMUNITY_AAPL SEC Risk Filings|AAPL SEC Risk Filings]]
- [[_COMMUNITY_AAPL Context Metadata|AAPL Context Metadata]]
- [[_COMMUNITY_ASTS Job Market Data|ASTS Job Market Data]]
- [[_COMMUNITY_ASTS Litigation Data|ASTS Litigation Data]]
- [[_COMMUNITY_ASTS Press Releases|ASTS Press Releases]]
- [[_COMMUNITY_ASTS SEC Risk Filings|ASTS SEC Risk Filings]]
- [[_COMMUNITY_ASTS Context Metadata|ASTS Context Metadata]]
- [[_COMMUNITY_POET SEC 8K Events|POET SEC 8K Events]]
- [[_COMMUNITY_POET Job Market Data|POET Job Market Data]]
- [[_COMMUNITY_POET Litigation Data|POET Litigation Data]]
- [[_COMMUNITY_POET Press Releases|POET Press Releases]]
- [[_COMMUNITY_POET SEC Risk Filings|POET SEC Risk Filings]]
- [[_COMMUNITY_Fetch Context Script|Fetch Context Script]]
- [[_COMMUNITY_Local Claude Settings|Local Claude Settings]]
- [[_COMMUNITY_MCP Server Config|MCP Server Config]]
- [[_COMMUNITY_Financial Rationale A|Financial Rationale A]]
- [[_COMMUNITY_Financial Rationale B|Financial Rationale B]]
- [[_COMMUNITY_Financial Rationale C|Financial Rationale C]]
- [[_COMMUNITY_Alt Data Rationale|Alt Data Rationale]]
- [[_COMMUNITY_Company Financials Type|Company Financials Type]]

## God Nodes (most connected - your core abstractions)
1. `ContextAggregator` - 41 edges
2. `str` - 29 edges
3. `CompanyFinancials` - 28 edges
4. `FinancialService` - 26 edges
5. `str` - 25 edges
6. `TestFinancialDataTransformer` - 24 edges
7. `TestGoogleTrendsProcessor` - 22 edges
8. `TrendsSignal` - 22 edges
9. `FredSeries` - 22 edges
10. `ApifyJobsResult` - 22 edges

## Surprising Connections (you probably didn't know these)
- `str` --uses--> `CompanyFinancials`  [INFERRED]
  context_aggregator.py → financial_service.py
- `ContextAggregator` --uses--> `CompanyFinancials`  [INFERRED]
  context_aggregator.py → financial_service.py
- `TestApifyJobScraper` --uses--> `CompanyFinancials`  [INFERRED]
  test_all.py → financial_service.py
- `TestContextAggregatorHelpers` --uses--> `CompanyFinancials`  [INFERRED]
  test_all.py → financial_service.py
- `TestFinancialDataTransformer` --uses--> `CompanyFinancials`  [INFERRED]
  test_all.py → financial_service.py

## Communities (44 total, 6 thin omitted)

### Community 0 - "Alt Data Service Core"
Cohesion: 0.07
Nodes (43): DataFrame, float, str, AltDataService, Any, Path, Exception, FinancialService (+35 more)

### Community 1 - "Alt Data Processors"
Cohesion: 0.06
Nodes (26): ApifyJobScraper, FredDataProcessor, GoogleTrendsProcessor, Domain: derives velocity and summary statistics from raw Trends data.     Single, Domain: summarises raw FRED observations into a FredSeries dataclass.     Single, Infrastructure + Domain: downloads a 10-K document and extracts the     opening, STUB implementation for Apify-powered job-listing scraper.      To activate:, STUB: LinkedIn / Glassdoor employee count via an Apify LinkedIn actor.         U (+18 more)

### Community 2 - "FRED API Integration"
Cohesion: 0.10
Nodes (14): int, FredApiFetcher, GoogleTrendsFetcher, PressReleaseFetcher, Infrastructure: wraps pytrends TrendReq.     Single responsibility: issue the HT, Infrastructure: queries the FRED REST API.     API key is read from the FRED_API, Return a list of {date, value} observation dicts, newest first.         Values o, Infrastructure: resolves a ticker symbol → zero-padded 10-digit CIK.     Uses ED (+6 more)

### Community 3 - "Financial Data Service"
Cohesion: 0.15
Nodes (15): bool, DataFrame, float, Path, str, _growth_to_pct(), _ratio(), financial_service.py — Valuation Engine ======================================== (+7 more)

### Community 4 - "Context Aggregation Layer"
Cohesion: 0.27
Nodes (9): str, build_all_contexts(), ContextAggregator, _error_node(), Orchestrates FinancialService and AltDataService to build a single     token-eff, Full pipeline for one ticker:           1. Target company financials           2, Generate context files for every ticker in *tickers*.     Returns a dict of {tic, Convert dataclass instances to plain dicts for JSON serialisation. (+1 more)

### Community 5 - "Agent Orchestration"
Cohesion: 0.18
Nodes (11): AltDataService, run_market_agent, ContextAggregator, _fetch, FinancialDataFetcher, FinancialDataTransformer, FinancialExporter, FinancialService (+3 more)

### Community 6 - "AAPL Valuation Targets"
Cohesion: 0.18
Nodes (11): target, enterprise_value_mm, ev_ebitda, ev_revenue, forward_pe, market_cap_mm, name, ticker (+3 more)

### Community 7 - "ASTS Valuation Targets"
Cohesion: 0.18
Nodes (11): target, enterprise_value_mm, ev_ebitda, ev_revenue, forward_pe, market_cap_mm, name, ticker (+3 more)

### Community 8 - "MCP Server Interface"
Cohesion: 0.25
Nodes (10): Any, str, build_company_context(), generate_sector_sheet(), list_supported_tickers(), Return the set of tickers this server has pre-configured competitor mappings, Validate and normalise a user-supplied ticker list.     Returns a clean list, or, Generate a CSV of valuation metrics (Market Cap, EV, EV/Revenue, EV/EBITDA, (+2 more)

### Community 9 - "POET Valuation Targets"
Cohesion: 0.20
Nodes (10): target, enterprise_value_mm, ev_ebitda, ev_revenue, market_cap_mm, name, ticker, trailing_ebitda_mm (+2 more)

### Community 10 - "Claude Configuration"
Cohesion: 0.22
Nodes (8): enabledMcpjsonServers, enabledPlugins, code-simplifier@claude-plugins-official, context7@claude-plugins-official, security-guidance@claude-plugins-official, windsor-ai@claude-plugins-official, hooks, PreToolUse

### Community 11 - "POET Company Context"
Cohesion: 0.25
Nodes (6): meta, fred_series, generated_at_utc, schema_version, target_ticker, peers

### Community 12 - "AAPL Alt Signals"
Cohesion: 0.29
Nodes (6): alt_signals, sec_8k_events, peers, cik, events, ticker

### Community 13 - "AAPL Google Trends"
Cohesion: 0.29
Nodes (7): google_trends, keyword, latest_interest, peak_interest, ticker, trough_interest, velocity_pct

### Community 14 - "ASTS Alt Signals"
Cohesion: 0.29
Nodes (6): alt_signals, sec_8k_events, peers, cik, events, ticker

### Community 15 - "ASTS Google Trends"
Cohesion: 0.29
Nodes (7): google_trends, keyword, latest_interest, peak_interest, ticker, trough_interest, velocity_pct

### Community 16 - "POET Google Trends"
Cohesion: 0.29
Nodes (7): google_trends, keyword, latest_interest, peak_interest, ticker, trough_interest, velocity_pct

### Community 17 - "MCP Client Agent"
Cohesion: 0.40
Nodes (5): str, _mcp_tools_to_gemini(), Convert MCP tool descriptors to a single Gemini Tool with FunctionDeclarations., run_market_agent(), Tool

### Community 18 - "AAPL Macro FRED Data"
Cohesion: 0.33
Nodes (6): macro_fred, latest_date, latest_value, series_id, title, yoy_change_pct

### Community 19 - "ASTS Macro FRED Data"
Cohesion: 0.33
Nodes (6): macro_fred, latest_date, latest_value, series_id, title, yoy_change_pct

### Community 20 - "POET Macro FRED Data"
Cohesion: 0.33
Nodes (6): macro_fred, latest_date, latest_value, series_id, title, yoy_change_pct

### Community 21 - "AAPL Job Market Data"
Cohesion: 0.40
Nodes (5): job_market, company_name, engineering_roles, is_stub, total_open_roles

### Community 22 - "AAPL Litigation Data"
Cohesion: 0.40
Nodes (5): litigation, cases, company_name, error, source

### Community 23 - "AAPL Press Releases"
Cohesion: 0.40
Nodes (5): press_releases, error, releases, source, ticker

### Community 24 - "AAPL SEC Risk Filings"
Cohesion: 0.40
Nodes (5): sec_risk_snippet, cik, filing_url, risk_factors_snippet, ticker

### Community 25 - "AAPL Context Metadata"
Cohesion: 0.40
Nodes (5): meta, fred_series, generated_at_utc, schema_version, target_ticker

### Community 26 - "ASTS Job Market Data"
Cohesion: 0.40
Nodes (5): job_market, company_name, engineering_roles, is_stub, total_open_roles

### Community 27 - "ASTS Litigation Data"
Cohesion: 0.40
Nodes (5): litigation, cases, company_name, error, source

### Community 28 - "ASTS Press Releases"
Cohesion: 0.40
Nodes (5): press_releases, error, releases, source, ticker

### Community 29 - "ASTS SEC Risk Filings"
Cohesion: 0.40
Nodes (5): sec_risk_snippet, cik, filing_url, risk_factors_snippet, ticker

### Community 30 - "ASTS Context Metadata"
Cohesion: 0.40
Nodes (5): meta, fred_series, generated_at_utc, schema_version, target_ticker

### Community 31 - "POET SEC 8K Events"
Cohesion: 0.40
Nodes (5): alt_signals, sec_8k_events, cik, events, ticker

### Community 32 - "POET Job Market Data"
Cohesion: 0.40
Nodes (5): job_market, company_name, engineering_roles, is_stub, total_open_roles

### Community 33 - "POET Litigation Data"
Cohesion: 0.40
Nodes (5): litigation, cases, company_name, error, source

### Community 34 - "POET Press Releases"
Cohesion: 0.40
Nodes (5): press_releases, error, releases, source, ticker

### Community 35 - "POET SEC Risk Filings"
Cohesion: 0.40
Nodes (5): sec_risk_snippet, cik, filing_url, risk_factors_snippet, ticker

### Community 36 - "Fetch Context Script"
Cohesion: 0.50
Nodes (4): int, str, _fetch(), main()

### Community 37 - "Local Claude Settings"
Cohesion: 0.50
Nodes (3): enabledMcpjsonServers, permissions, allow

## Knowledge Gaps
- **158 isolated node(s):** `DataFrame`, `/home/lunear/theoryy/middlemarket-research-agent/.venv/bin/python3.14`, `target_ticker`, `schema_version`, `generated_at_utc` (+153 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ContextAggregator` connect `Context Aggregation Layer` to `Alt Data Service Core`, `MCP Server Interface`, `Alt Data Processors`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Why does `CompanyFinancials` connect `Alt Data Service Core` to `Alt Data Processors`, `Financial Data Service`, `Context Aggregation Layer`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Why does `TestFinancialDataTransformer` connect `Alt Data Processors` to `Alt Data Service Core`, `Context Aggregation Layer`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `ContextAggregator` (e.g. with `Any` and `str`) actually correct?**
  _`ContextAggregator` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `CompanyFinancials` (e.g. with `AltDataService` and `Any`) actually correct?**
  _`CompanyFinancials` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `FinancialService` (e.g. with `AltDataService` and `Any`) actually correct?**
  _`FinancialService` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `str` (e.g. with `AltDataService` and `ApifyJobsResult`) actually correct?**
  _`str` has 10 INFERRED edges - model-reasoned connections that need verification._