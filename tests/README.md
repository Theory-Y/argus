# tests/

Unit test suite for TheoryY Argus — pure-logic coverage of the data pipeline, chart
engine, memo writer, and SEC taxonomy that feed the memo-generation workflow.

## Overview

This suite exercises the deterministic building blocks behind the memo pipeline
(`src/`, `scripts/`, `core/memo/`, `mcp_server.py`) without ever touching the
network, a real LLM API, or any external service. All I/O collaborators
(HTTP clients, the Anthropic SDK, scrapers) are mocked or injected as fakes, so
the suite runs fully offline and needs no API keys or credentials.

## Directory Structure

| File | Purpose |
|---|---|
| [test_all.py](./test_all.py) | Broad unittest suite: `financial_service` (transform/audit/peer builders), alt-data processors (Google Trends, FRED, SEC risk factors, Apify job scraper, sentiment aggregation, macro relevance), `context_aggregator` helpers, and `mcp_server` ticker resolution (`_resolve_tickers`). |
| [test_chart_service.py](./test_chart_service.py) | `chart_service` SVG chart builders — asserts every chart emits well-formed XML (via `defusedxml`) even on bad/empty input, plus the `[[chart:name]]` token regex used by the PDF export script. |
| [test_memo_writer.py](./test_memo_writer.py) | `core.memo.prompt` (system prompt structure, seven sections) and `core.memo.writer` (`write_memo`, `write_memos_batch`) against a fake Anthropic streaming/batch client — checks prompt caching, model selection, and text-block concatenation. |
| [test_taxonomy.py](./test_taxonomy.py) | `src.taxonomy` SEC 8-K item taxonomy — label/category/tier validity, byte-for-byte regression guard against the original 17-code label set, and that `alt_data_service._8K_ITEM_LABELS` derives from the same taxonomy. |
| [test_web_research.py](./test_web_research.py) | `web_research_service` — HTML→Markdown cleanup (strips `<script>`/`<style>`/`<nav>`), change-detection caching (304/hash reuse skips re-extraction), ticker-relevance scoring via the shared lexicon helpers, and graceful stub behavior when `scrapegraphai`/API keys are absent. |

## Usage

Run the full suite with pytest (preferred):

```bash
python -m pytest tests/ -q
```

Currently 161 tests, all green. `test_taxonomy.py` uses pytest-style `def test_...()`
functions; the rest use `unittest.TestCase` classes, but both styles run cleanly
under pytest's collector.

Alternatively, run with the stdlib runner:

```bash
python -m unittest discover tests
```

Run a single file or test:

```bash
python -m pytest tests/test_chart_service.py -q
python -m pytest tests/test_all.py::TestMcpServerHelpers -q
```

## Conventions & Good Practices

- **No network calls, ever.** Any HTTP, SEC/EDGAR, Google Trends, FRED, Apify, or
  LLM API interaction is mocked (`unittest.mock`) or replaced with an injectable
  fake client (see `_FakeClient`/`_FakeBatchClient` in
  [test_memo_writer.py](./test_memo_writer.py)). No API keys are read or required.
- Each file adds its own `src/`/`scripts/`/repo-root path via `sys.path.insert(0, ...)`
  at the top rather than relying on a shared `conftest.py` (none exists in this
  directory) or package install — keep new test files consistent with this pattern.
- Test classes/functions are grouped by the module under test, with `# ─── name ───`
  banner comments in `test_all.py` separating sections — follow that layout when
  adding tests for a new module rather than creating a new top-level file, unless
  the module warrants its own file (as chart/memo/taxonomy/web-research do).
- SVG output is parsed with `defusedxml` (not stdlib `xml`/`minidom`) to avoid XXE
  even in tests — keep using it for any new SVG assertions.
- Docstrings at the top of each file state exactly what invariant the file pins
  (e.g. regression guards, degrade-to-stub behavior) — keep this convention when
  extending a file, since it doubles as the spec for why the test exists.

## Dependencies & Relationships

- Exercises modules in `../src/` (`financial_service.py`, `web_research_service.py`,
  `alt_data_service.py`, `taxonomy.py`, `context_aggregator.py`), `../scripts/`
  (`chart_service.py`), `../core/memo/` (`prompt.py`, `writer.py`), and
  `../mcp_server.py`.
- No test in this directory depends on another test file; each is independently
  runnable.
- `__pycache__/` here is build output only — not part of the suite.
