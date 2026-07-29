# core/

The proprietary memo engine for TheoryY Argus — the IP boundary of the project.

## Overview

`core/` holds the hidden system prompt and the Anthropic API glue that turns a
company data payload into a finished investment memo. Per its package
docstring, this code "is shipped to source-sale buyers, but it is NEVER
bundled into any distributable client." Anything under this directory should
be treated as sensitive: it is the thing customers are paying for, not a
generic app layer.

Note: the HTTP server, SaaS, and deployment layers were removed from this
project, and with them `core/engine.py` and `core/render.py` (server-only glue
that called into this package) were deleted as dangling. What remains is the
memo-generation core itself — currently exercised only by
`tests/test_memo_writer.py`; the primary memo path is the Claude Code skill
(`.claude/skills/theory-y-memo/SKILL.md`).

## Directory Structure

```
core/
├── __init__.py           # package docstring: states the IP-boundary rule
└── memo/
    ├── __init__.py       # "memo generation (hidden prompt + Anthropic API)"
    ├── prompt.py          # the proprietary system prompt + SECTIONS spec
    └── writer.py          # Anthropic API calls: streaming + batch, caching
```

## Key Components

- **[`memo/prompt.py`](./memo/prompt.py)** — `SYSTEM_PROMPT`, the seven-section
  memo-writing instructions (thesis, business overview, alt-data/macro,
  consumer opinion, risks, catalyst map, recommendation), plus `SECTIONS`
  (heading/word-budget pairs) and `user_message(ticker, context_json)` which
  builds the per-request user turn.
- **[`memo/writer.py`](./memo/writer.py)** — `write_memo(ticker, context_json, ...)`
  for a single streamed memo, and `write_memos_batch(items, ...)` for
  many-at-once generation via the Message Batches API (50% cheaper). Both
  share `_request_params()` so a batched request is byte-for-byte identical
  to a single one (same model/prompt/thinking/effort). The system prompt is
  sent with `cache_control` (default TTL `1h`, override via
  `ANTHROPIC_CACHE_TTL`) so its cost amortizes across memos. `client` is
  injectable on both functions for testing; production defaults to
  `anthropic.Anthropic()` reading `ANTHROPIC_API_KEY`.

## Usage

```python
from core.memo.writer import write_memo

memo_markdown = write_memo("PCOR", context_json_string)
```

For a stub client in tests, pass any object exposing `messages.stream(...)`
(single) or `messages.batches.create/retrieve/results` (batch) — see
[`tests/test_memo_writer.py`](../tests/test_memo_writer.py).

## Conventions & Good Practices

- **IP boundary**: never import from `core/` into anything destined for a
  distributable/client bundle. This package is source-sale only.
- **Prompt/SKILL.md sync**: `core/memo/prompt.py`'s `SYSTEM_PROMPT` is the
  machine-sent version of the same instructions documented for human/
  Claude-Code buyers in
  [`.claude/skills/theory-y-memo/SKILL.md`](../.claude/skills/theory-y-memo/SKILL.md).
  When editing one, update the other — they must describe the same seven
  sections, word budgets, and writing rules.
- Env vars `ANTHROPIC_MODEL`, `ANTHROPIC_EFFORT`, `ANTHROPIC_MAX_TOKENS`,
  `ANTHROPIC_CACHE_TTL` configure `writer.py` defaults per-deployment.

## Dependencies & Relationships

- Depends on the `anthropic` SDK (lazily imported inside `write_memo` /
  `write_memos_batch` so a test client can be injected without the package
  installed).
- Currently consumed only by `tests/test_memo_writer.py`; the former caller
  (`core/engine.py`) was deleted with the server layer.
