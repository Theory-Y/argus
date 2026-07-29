---
name: theoryy-argus-src-structure
description: theoryy-argus/src/ layout, local-only (no HTTP/SaaS) framing, and root README's existing "Project structure" section to keep in sync
metadata:
  type: project
---

theoryy-argus is currently in a reverted, pre-pivot, **local-only** state: no HTTP server, no SaaS, no deployment layer. `src/` is a local MCP server (stdio transport, `mcp_server.py`) + data pipeline that `fetch_context.py` calls to produce `output/context/context_TICKER.json`, consumed by the `.claude/skills/theory-y-memo` skill and `core/memo/{prompt,writer}.py`. Do not describe this directory as having any deployed/HTTP component even if `PIVOT_ARCHITECTURE.md` (repo root, authoritative per CLAUDE.md) describes a future stateful platform — that pivot is not the current code state; verify current state before trusting the pivot doc's framing.

Root [README.md](../../README.md) already has a "Project structure" section (~line 190) listing `src/`, `core/`, `scripts/`, `localization/`, `tests/` at a high level — when writing `src/README.md`, checked it for consistency but did not need to edit it.

`src/agents/` and `src/store/` (with `store/migrations/`) exist but are empty (only `__pycache__`) — leftover pivot scaffolding, not used by any current tool. No `pyproject.toml` at repo root despite an editable-install finder script surviving in `.venv/site-packages` — stale artifact, not a live convention.

**Why:** avoids re-deriving this by re-reading all of `src/` next time, and avoids being misled by `PIVOT_ARCHITECTURE.md`'s aspirational architecture into documenting features that don't exist yet.
**How to apply:** when documenting other subdirs of theoryy-argus (e.g. `core/`, `scripts/`, `tests/`), assume the same local-only stdio-MCP framing unless the code shows otherwise, and cross-check against the root README's structure section for consistency rather than duplicating it wholesale.
