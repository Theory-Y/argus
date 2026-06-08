# Roadmap — TheoryY Middle-Market Research Agent

_Last updated: 2026-06-03_

This document captures the project's current state, the prioritized plan forward,
and the reasoning behind the ordering. It supersedes the loose notes in `TODO.md`
(which is folded into Phase 0 below).

---

## Where the project is today

v1.0.0 is **built** end-to-end:

- **MCP data layer** (`src/mcp_server.py`) — `build_company_context`,
  `generate_sector_sheet`, `list_supported_tickers`.
- **Deterministic data services** (`src/financial_service.py`, alt-data) —
  yfinance, FRED, SEC EDGAR, Google Trends, GlobeNewswire RSS, Stanford SCAC.
- **Memo engine** (`core/`) + the `theory-y-memo` Claude skill that writes the
  five analytical sections from a `context_<TICKER>.json` payload.
- **Charts** (`src/chart_service.py`) — dependency-free inline SVG, embedded via
  `[[chart:NAME]]` tokens, rendered at PDF-export time.
- **Export** (`scripts/export_pdf.py`) — `.dotx` + headless-Chromium → PDF/DOCX.
- **Service layer** (`server/`) — FastAPI, license + SaaS auth, Stripe billing,
  background job queue, SQLAlchemy persistence.
- **Client** — Python CLI + React/Vite web UI, lives in a separate repository (HTTP-only, zero IP).
- **Recent additions** — web research via ScrapeGraphAI, zh/es/fr localization,
  ~40% token optimization, hardened JWT secret handling.
- **Tests** — 64 passing across the chart engine, memo writer, and data services.

### The honest gap

The **core product has never been run once end-to-end against live LLM
extraction.** Tests pass against fixtures, and `output/context/*.json` is
pre-baked. Per `TODO.md`, the live run is blocked on a placeholder
`ANTHROPIC_API_KEY`. Everything shipped after v1.0.0 (billing, localization, web
seeds) sits on top of an unvalidated core.

There is also **no verification of the product's headline promise** —
"institutional-grade, no fabricated numbers." Nothing in the pipeline checks that
the figures the LLM writes actually trace back to the deterministic payload.

---

## Guiding principle for ordering

De-risk the core before expanding it. Validation and grounding come before new
features, because a fabricated number in an investment memo is the failure mode
that kills trust in this product category.

---

## Phase 0 — Unblock the live run _(prerequisite, days)_

Close the gap `TODO.md` already flags. Nothing downstream is trustworthy until
this is done.

- [ ] Set a real `ANTHROPIC_API_KEY` in `.env` (currently `sk-ant-...` placeholder).
- [ ] Install the live stack: `scrapegraphai`, `markdownify`, `python-toon`.
- [ ] Run the full pipeline end-to-end for a real middle-market ticker
      (e.g. `PCOR`, `CSGP`, `APPF`) — context fetch → memo → charts → PDF.
- [ ] Verify twice-run cache hits ("LLM skipped") once a real key is set.
- [ ] Confirm `build_company_context` MCP path surfaces the node live.
- [ ] Populate `WEB_RESEARCH_SEEDS` (per-ticker forum URLs) — ships empty, so the
      ScrapeGraphAI feature is dead weight until seeded.

**Exit criterion:** at least three real memos generated from live data on the
actual middle-market universe — not the AAPL/NVDA fixtures lying in `output/context/`.

---

## Phase 1 — Numeric grounding / fact-faithfulness check _(highest leverage)_

**This is the single most significant step forward.** Turn "no fabricated
numbers" from a marketing claim into an enforced, tested invariant.

- [ ] Extract every numeric claim from the generated memo Markdown
      (revenue, multiples, growth %, price levels, etc.).
- [ ] Assert each figure appears in — or is arithmetically derivable from —
      `context_<TICKER>.json`.
- [ ] Flag/fail any memo containing an ungrounded number; surface the offending
      claim in the failure message.
- [ ] Hook the check into `core/memo/writer.py` (post-generation) and the export
      path (`scripts/export_pdf.py`) so it gates artifacts.
- [ ] Promote the check into the test suite as the first real **eval harness** —
      today there is no way to measure whether a memo is *good*, only whether the
      code runs.

**Why first:** highest leverage, lowest cost. It de-risks everything downstream
and converts the core value proposition into something verifiable.

---

## Phase 2 — Dynamic ticker coverage _(reach)_

`SECTOR_TICKERS` is a hardcoded list of 14 names (`src/financial_service.py:39`).
The product's reach is capped at those names until coverage is data-driven.

- [ ] Replace the static list with a resolver that accepts an arbitrary ticker
      and fetches its sector/peer set on demand.
- [ ] Define peer-group selection for tickers outside the curated universe.
- [ ] Validate that alt-data sources (SEC, Trends, SCAC) degrade gracefully for
      thinly-covered names.
- [ ] Update `list_supported_tickers` semantics — "supported" becomes a
      capability statement, not a fixed allowlist.

**Why after Phase 1:** this expands the core rather than de-risking it; the
grounding check must exist first so new tickers are validated automatically.

---

## Phase 3 — Output quality & evaluation _(maturity)_

Build on the Phase 1 harness to measure memo quality, not just correctness.

- [ ] Define a rubric for institutional-memo quality (structure, analytical
      depth, citation density, hedging).
- [ ] Golden-memo regression set: lock known-good outputs and diff on changes.
- [ ] Chart-coverage check: every `[[chart:NAME]]` token resolves or degrades to
      a visible "unavailable" note (no silent gaps).
- [ ] Localization fidelity: verify zh/es/fr memos preserve all chart/table tokens
      and numeric values (numbers must survive translation unchanged).

---

## Phase 4 — Service hardening & launch readiness _(SaaS path)_

For the hosted offering (`AUTH_MODE=saas`).

- [ ] Confirm the JWT-secret startup guard behaves correctly in deployment
      (raises when unset/placeholder in SaaS mode).
- [ ] Re-audit the Stripe webhook plan-elevation path — derive the plan from the
      paid price ID, not client-supplied `metadata.plan`
      (`server/routes/billing.py`). Medium severity; gate before public launch.
- [ ] Add a bounds check to `LocalStorage.resolve_path` (`server/storage.py`) so
      artifact keys cannot escape the storage root — latent path-traversal hygiene.
- [ ] Load/concurrency test the background job queue (`inprocess` → `rq`).
- [ ] End-to-end billing test in Stripe test mode (checkout → webhook → plan).

---

## Phase 5 — Product surface & docs _(growth)_

- [ ] Operator docs: deployment, env vars, and the SaaS vs license decision.
- [ ] Expand `WEB_RESEARCH_SEEDS` coverage as the ticker universe grows.

---

## Quick reference — recommended order

1. **Phase 0** — get one real run (unblocks everything).
2. **Phase 1** — numeric grounding check (the big one).
3. **Phase 2** — dynamic ticker coverage (reach).
4. **Phase 3** — quality evals (maturity).
5. **Phase 4** — service hardening (SaaS launch gate).
6. **Phase 5** — product surface & docs (growth).
