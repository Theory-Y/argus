# scripts/

Standalone helper scripts that support the memo pipeline but sit outside the
importable `src/` package: theming, PDF/DOCX export, and MCP client tooling
for local testing. Everything here runs locally — there is no HTTP server or
deployment step; scripts are invoked directly from the repo root.

## Contents

| File | Purpose |
|---|---|
| [`build_reference_dotx.py`](./build_reference_dotx.py) | Regenerates `output/theme/reference.dotx`, the branded Word template (Theory Y navy/gold palette, Garamond/Calibri typography) that `export_pdf.py` and pandoc use for DOCX export. |
| [`export_pdf.py`](./export_pdf.py) | Converts a rendered memo Markdown file to DOCX + PDF: pandoc `.md → .docx` (via `reference.dotx`), pandoc `.md → .html`, injects `output/theme/theme.css`-equivalent institutional CSS, resolves `[[chart:…]]`/`[[table:…]]` tokens and figure numbering, then rasterizes to PDF via headless Chromium (Playwright, or a probed browser binary). |
| [`client-mcp.py`](./client-mcp.py) | Standalone MCP client used to smoke-test `src/mcp_server.py` directly over stdio (bypassing the `argus` skill), by asking Claude to call the server's tools for a given ticker. Not part of the production memo flow. |
| [`run_massive_mcp.sh`](./run_massive_mcp.sh) | Launcher shim referenced by `.mcp.json`'s `massive` server entry — puts `~/.local/bin` on `PATH`, sources the repo's `.env`, and `exec`s the `mcp_massive` uv-tool binary. |

## Usage

### Rebuild the DOCX reference template

```bash
.venv/bin/python3 scripts/build_reference_dotx.py
```

Unzips the existing `output/theme/reference.dotx`, rewrites the OOXML
`styles.xml` (heading/body/table/quote styles, palette, fonts) and page
margins, then repacks it in place. Run this after changing the palette or
typography constants at the top of the file; a backup of the previous
`.dotx` is written to `/tmp/ref_backup.dotx` before overwriting.

### Export a memo to PDF / DOCX

```bash
.venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_MU.md
.venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_MU.md --skip-docx
```

Key flags: `--lang {en,zh,es,fr}` (CJK font fallback + localized header
chrome), `--no-charts` (strip `[[chart:…]]` tokens instead of rendering
SVGs), `--context <path>` (override the `output/context/context_<TICKER>.json`
payload used for chart data), `--date` (override the header date).

Requires `pandoc` on `PATH` and a Chromium-family browser for the final
render step — Playwright's bundled Chromium is used if installed, otherwise
the script probes `chromium`, `google-chrome`, `msedge`, etc., or honors
`CHROMIUM_BIN` / `CHROME_BIN` env vars if set.

### Smoke-test the MCP server

```bash
.venv/bin/python3 scripts/client-mcp.py PCOR
```

Spawns `src/mcp_server.py` as a stdio subprocess, lists its tools, and drives
one agentic Claude tool-use loop to fetch the ticker's context payload and
produce a one-line thesis. Useful for verifying the MCP server responds
correctly without going through the full memo skill.

### `run_massive_mcp.sh`

Not invoked directly — Claude Code launches it as the `massive` entry in
[`.mcp.json`](../.mcp.json) (root). It exists only to fix `PATH` and load
`.env` before handing off to the `mcp_massive` binary.

## Notes

- `build_reference_dotx.py` and `export_pdf.py` both assume repo-relative
  paths (`output/theme/reference.dotx`, `output/context/`) and should be run
  from the project root.
- `export_pdf.py` imports `chart_service` from `src/` via a relative
  `sys.path` insert — it is not meant to be moved out of `scripts/` without
  updating that path.
- `client-mcp.py` requires `ANTHROPIC_API_KEY` (used implicitly by
  `anthropic.AsyncAnthropic()`) and is a developer utility, not part of the
  `theory-y-memo` skill's runtime path.
