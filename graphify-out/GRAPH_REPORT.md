# Graph Report - .  (2026-05-28)

## Corpus Check
- 30 files · ~33,890 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 928 nodes · 1774 edges · 48 communities (34 shown, 14 thin omitted)
- Extraction: 77% EXTRACTED · 23% INFERRED · 0% AMBIGUOUS · INFERRED: 410 edges (avg confidence: 0.52)
- Token cost: 99,682 input · 3,312 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Context Aggregation & Financial Data|Context Aggregation & Financial Data]]
- [[_COMMUNITY_Alt Data Service Core|Alt Data Service Core]]
- [[_COMMUNITY_AAPL Alt Signals Context|AAPL Alt Signals Context]]
- [[_COMMUNITY_ASTS Alt Signals Context|ASTS Alt Signals Context]]
- [[_COMMUNITY_AAPL Context Data|AAPL Context Data]]
- [[_COMMUNITY_ASTS Context Data|ASTS Context Data]]
- [[_COMMUNITY_Financial Data Transformation|Financial Data Transformation]]
- [[_COMMUNITY_POET Alt Signals Context|POET Alt Signals Context]]
- [[_COMMUNITY_CRDO Alt Signals Context|CRDO Alt Signals Context]]
- [[_COMMUNITY_MU Alt Signals Context|MU Alt Signals Context]]
- [[_COMMUNITY_RKLB Alt Signals Context|RKLB Alt Signals Context]]
- [[_COMMUNITY_Package Configuration|Package Configuration]]
- [[_COMMUNITY_PDF Export Scripts|PDF Export Scripts]]
- [[_COMMUNITY_Alt Data Processor Design|Alt Data Processor Design]]
- [[_COMMUNITY_MCP Client & Context Fetch|MCP Client & Context Fetch]]
- [[_COMMUNITY_Context Aggregator Classes|Context Aggregator Classes]]
- [[_COMMUNITY_External Data Fetchers|External Data Fetchers]]
- [[_COMMUNITY_Alt Data Service Methods|Alt Data Service Methods]]
- [[_COMMUNITY_Litigation Data Signal|Litigation Data Signal]]
- [[_COMMUNITY_Job Market Signal|Job Market Signal]]
- [[_COMMUNITY_MCP Server Tools|MCP Server Tools]]
- [[_COMMUNITY_Claude Plugin Settings|Claude Plugin Settings]]
- [[_COMMUNITY_POET Google Trends Data|POET Google Trends Data]]
- [[_COMMUNITY_POET Valuation Targets|POET Valuation Targets]]
- [[_COMMUNITY_POET Litigation Data|POET Litigation Data]]
- [[_COMMUNITY_Google Trends Tests|Google Trends Tests]]
- [[_COMMUNITY_Local Claude Settings|Local Claude Settings]]
- [[_COMMUNITY_POET FRED Macro Data|POET FRED Macro Data]]
- [[_COMMUNITY_SEC Risk Factor Tests|SEC Risk Factor Tests]]
- [[_COMMUNITY_Project Dependencies|Project Dependencies]]
- [[_COMMUNITY_POET Job Market Data|POET Job Market Data]]
- [[_COMMUNITY_POET Context Metadata|POET Context Metadata]]
- [[_COMMUNITY_SEC 8-K Events Data|SEC 8-K Events Data]]
- [[_COMMUNITY_MCP Client Scripts|MCP Client Scripts]]
- [[_COMMUNITY_Fetch Context Module|Fetch Context Module]]
- [[_COMMUNITY_POET Research Output|POET Research Output]]
- [[_COMMUNITY_MCP Server Config|MCP Server Config]]
- [[_COMMUNITY_Setup Scripts|Setup Scripts]]
- [[_COMMUNITY_AAPL Research Output|AAPL Research Output]]
- [[_COMMUNITY_Financial Rationale A|Financial Rationale A]]
- [[_COMMUNITY_Financial Rationale B|Financial Rationale B]]
- [[_COMMUNITY_Financial Rationale C|Financial Rationale C]]
- [[_COMMUNITY_Alt Data Rationale|Alt Data Rationale]]
- [[_COMMUNITY_Src Financial Rationale A|Src Financial Rationale A]]
- [[_COMMUNITY_Src Financial Rationale B|Src Financial Rationale B]]
- [[_COMMUNITY_Src Financial Rationale C|Src Financial Rationale C]]
- [[_COMMUNITY_Src Alt Data Rationale|Src Alt Data Rationale]]

## God Nodes (most connected - your core abstractions)
1. `AltDataService` - 56 edges
2. `FinancialService` - 49 edges
3. `SecRiskSnippet` - 40 edges
4. `ContextAggregator` - 39 edges
5. `CompanyFinancials` - 28 edges
6. `CompanyFinancials` - 26 edges
7. `TestFinancialDataTransformer` - 26 edges
8. `str` - 25 edges
9. `str` - 25 edges
10. `str` - 25 edges

## Surprising Connections (you probably didn't know these)
- `TestGoogleTrendsProcessor` --uses--> `FinancialService`  [INFERRED]
  test_all.py → context_aggregator.py
- `TestGoogleTrendsProcessor` --uses--> `ApifyJobsResult`  [INFERRED]
  test_all.py → alt_data_service.py
- `TestGoogleTrendsProcessor` --uses--> `GoogleTrendsProcessor`  [INFERRED]
  test_all.py → alt_data_service.py
- `TestGoogleTrendsProcessor` --uses--> `SecRiskFactorExtractor`  [INFERRED]
  test_all.py → alt_data_service.py
- `TestGoogleTrendsProcessor` --uses--> `TrendsSignal`  [INFERRED]
  test_all.py → alt_data_service.py

## Communities (48 total, 14 thin omitted)

### Community 0 - "Context Aggregation & Financial Data"
Cohesion: 0.05
Nodes (43): str, CompanyFinancials, FinancialDataFetcher, FinancialDataTransformer, FinancialExporter, DataFrame, Path, ApifyJobScraper (+35 more)

### Community 1 - "Alt Data Service Core"
Cohesion: 0.05
Nodes (62): DataFrame, int, str, AltDataService, Any, Path, Exception, FinancialService (+54 more)

### Community 2 - "AAPL Alt Signals Context"
Cohesion: 0.05
Nodes (47): alt_signals, google_trends, job_market, litigation, macro_fred, press_releases, sec_8k_events, sec_risk_snippet (+39 more)

### Community 3 - "ASTS Alt Signals Context"
Cohesion: 0.05
Nodes (47): alt_signals, google_trends, job_market, litigation, macro_fred, press_releases, sec_8k_events, sec_risk_snippet (+39 more)

### Community 4 - "AAPL Context Data"
Cohesion: 0.05
Nodes (47): alt_signals, google_trends, job_market, litigation, macro_fred, press_releases, sec_8k_events, sec_risk_snippet (+39 more)

### Community 5 - "ASTS Context Data"
Cohesion: 0.05
Nodes (47): alt_signals, google_trends, job_market, litigation, macro_fred, press_releases, sec_8k_events, sec_risk_snippet (+39 more)

### Community 6 - "Financial Data Transformation"
Cohesion: 0.09
Nodes (33): bool, float, str, _growth_to_pct(), _ratio(), _safe_float(), _to_mm(), object (+25 more)

### Community 7 - "POET Alt Signals Context"
Cohesion: 0.05
Nodes (46): alt_signals, google_trends, job_market, litigation, macro_fred, press_releases, sec_8k_events, sec_risk_snippet (+38 more)

### Community 8 - "CRDO Alt Signals Context"
Cohesion: 0.05
Nodes (44): alt_signals, google_trends, job_market, litigation, macro_fred, sec_8k_events, sec_risk_snippet, keyword (+36 more)

### Community 9 - "MU Alt Signals Context"
Cohesion: 0.05
Nodes (44): alt_signals, google_trends, job_market, litigation, macro_fred, sec_8k_events, sec_risk_snippet, keyword (+36 more)

### Community 10 - "RKLB Alt Signals Context"
Cohesion: 0.05
Nodes (40): alt_signals, google_trends, job_market, litigation, macro_fred, sec_8k_events, sec_risk_snippet, keyword (+32 more)

### Community 11 - "Package Configuration"
Cohesion: 0.08
Nodes (29): author, bugs, url, dependencies, md-to-pdf, description, homepage, arch (+21 more)

### Community 12 - "PDF Export Scripts"
Cohesion: 0.14
Nodes (25): border_el(), clear_children(), color_el(), el(), find_style(), get_or_create(), ind_el(), Build output/theme/reference.dotx — Theory Y institutional equity research templ (+17 more)

### Community 13 - "Alt Data Processor Design"
Cohesion: 0.10
Nodes (10): FredDataProcessor, GoogleTrendsProcessor, Domain: derives velocity and summary statistics from raw Trends data.     Single, Domain: summarises raw FRED observations into a FredSeries dataclass.     Single, Infrastructure + Domain: downloads a 10-K document and extracts the     opening, SecRiskFactorExtractor, test_all.py — Unit tests for all pure-logic components across the project. No ex, TestFinancialDataTransformer (+2 more)

### Community 14 - "MCP Client & Context Fetch"
Cohesion: 0.10
Nodes (23): str, run_market_agent, _fetch, int, str, TheoryY_Finance_Oracle MCP, str, _mcp_tools_to_gemini() (+15 more)

### Community 15 - "Context Aggregator Classes"
Cohesion: 0.24
Nodes (10): build_all_contexts(), ContextAggregator, _error_node(), str, context_aggregator.py — LLM Payload Builder ====================================, Orchestrates FinancialService and AltDataService to build a single     token-eff, Full pipeline for one ticker:           1. Target company financials           2, Generate context files for every ticker in *tickers*.     Returns a dict of {tic (+2 more)

### Community 16 - "External Data Fetchers"
Cohesion: 0.12
Nodes (18): FredApiFetcher, GoogleTrendsFetcher, _label_items(), PressRelease, PressReleaseFetcher, int, alt_data_service.py — Macro & Alternative Signal Engine ========================, Single press release headline from GlobeNewswire RSS. (+10 more)

### Community 17 - "Alt Data Service Methods"
Cohesion: 0.18
Nodes (7): AltDataService, _html_to_text(), DataFrame, str, Fetch weekly interest-over-time for *keyword*.         Returns an empty DataFram, Returns the direct HTTPS URL of the most recent 10-K primary document,         o, High-level orchestrator for all alternative data sources.     All collaborators

### Community 18 - "Litigation Data Signal"
Cohesion: 0.29
Nodes (6): LitigationCase, LitigationFetcher, LitigationSignal, Single securities class-action case from Stanford SCAC., Active or recent class-action cases for one company., Securities litigation monitor with two-stage strategy:       1. Stanford SCAC fu

### Community 19 - "Job Market Signal"
Cohesion: 0.23
Nodes (7): ApifyJobScraper, ApifyJobsResult, Job-listing scrape result (stub until Apify actor is configured)., STUB implementation for Apify-powered job-listing scraper.      To activate:, STUB — returns zeroed mock data.          Live call pattern (replace this body):, STUB: LinkedIn / Glassdoor employee count via an Apify LinkedIn actor.         U, TestApifyJobScraper

### Community 20 - "MCP Server Tools"
Cohesion: 0.25
Nodes (10): build_company_context(), generate_sector_sheet(), list_supported_tickers(), Any, str, Return the set of tickers this server has pre-configured competitor mappings, Validate and normalise a user-supplied ticker list.     Returns a clean list, or, Generate a CSV of valuation metrics (Market Cap, EV, EV/Revenue, EV/EBITDA, (+2 more)

### Community 21 - "Claude Plugin Settings"
Cohesion: 0.22
Nodes (8): enabledMcpjsonServers, enabledPlugins, code-simplifier@claude-plugins-official, context7@claude-plugins-official, security-guidance@claude-plugins-official, windsor-ai@claude-plugins-official, hooks, PreToolUse

### Community 22 - "POET Google Trends Data"
Cohesion: 0.22
Nodes (9): float, google_trends, keyword, latest_interest, peak_interest, trough_interest, Series, float (+1 more)

### Community 23 - "POET Valuation Targets"
Cohesion: 0.22
Nodes (9): target, enterprise_value_mm, ev_ebitda, ev_revenue, market_cap_mm, name, trailing_ebitda_mm, trailing_revenue_mm (+1 more)

### Community 24 - "POET Litigation Data"
Cohesion: 0.33
Nodes (7): litigation, press_releases, cases, error, source, releases, ticker

### Community 26 - "Local Claude Settings"
Cohesion: 0.33
Nodes (5): enabledMcpjsonServers, enabledPlugins, frontend-design@claude-plugins-official, permissions, allow

### Community 27 - "POET FRED Macro Data"
Cohesion: 0.33
Nodes (6): macro_fred, latest_date, latest_value, series_id, title, yoy_change_pct

### Community 29 - "Project Dependencies"
Cohesion: 0.40
Nodes (5): Template Builder, Package Configuration, Python Dependencies, Windows Setup Script, Unix Setup Script

### Community 30 - "POET Job Market Data"
Cohesion: 0.40
Nodes (5): job_market, company_name, engineering_roles, is_stub, total_open_roles

### Community 31 - "POET Context Metadata"
Cohesion: 0.40
Nodes (5): meta, fred_series, generated_at_utc, schema_version, target_ticker

### Community 32 - "SEC 8-K Events Data"
Cohesion: 0.40
Nodes (5): Single 8-K filing — metadata only, no document download., cik, events, Single 8-K filing — metadata only, no document download., Sec8KEvent

### Community 33 - "MCP Client Scripts"
Cohesion: 0.50
Nodes (4): _mcp_tools_to_claude(), str, Convert MCP tool descriptors to Claude tool format., run_market_agent()

### Community 34 - "Fetch Context Module"
Cohesion: 0.50
Nodes (4): _fetch(), main(), int, str

## Knowledge Gaps
- **328 isolated node(s):** `DataFrame`, `/home/lunear/theoryy/middlemarket-research-agent/.venv/bin/python3.14`, `target_ticker`, `schema_version`, `generated_at_utc` (+323 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SecRiskSnippet` connect `Context Aggregation & Financial Data` to `SEC 8-K Events Data`, `Alt Data Service Core`, `POET Research Output`, `Financial Data Transformation`, `Alt Data Processor Design`, `Context Aggregator Classes`, `External Data Fetchers`, `Alt Data Service Methods`, `Job Market Signal`, `POET Litigation Data`, `Google Trends Tests`, `SEC Risk Factor Tests`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `AltDataService` connect `Alt Data Service Core` to `Context Aggregation & Financial Data`, `SEC 8-K Events Data`, `Financial Data Transformation`, `MCP Client & Context Fetch`, `Alt Data Service Methods`, `Litigation Data Signal`, `Job Market Signal`, `POET Google Trends Data`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Why does `FinancialService` connect `Alt Data Service Core` to `Context Aggregation & Financial Data`, `Financial Data Transformation`, `MCP Client & Context Fetch`, `Alt Data Service Methods`, `Litigation Data Signal`, `Job Market Signal`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 25 inferred relationships involving `AltDataService` (e.g. with `CompanyFinancials` and `ApifyJobsResult`) actually correct?**
  _`AltDataService` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `FinancialService` (e.g. with `context_aggregator.py` and `Any`) actually correct?**
  _`FinancialService` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 28 inferred relationships involving `SecRiskSnippet` (e.g. with `AltDataService` and `context_aggregator.py`) actually correct?**
  _`SecRiskSnippet` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `ContextAggregator` (e.g. with `AltDataService` and `ApifyJobsResult`) actually correct?**
  _`ContextAggregator` has 22 INFERRED edges - model-reasoned connections that need verification._