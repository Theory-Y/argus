---
name: theory-y-memo
description: Generate a Theory Y institutional equity research memo for a given stock ticker. Use this whenever the user asks for an investment memo, equity research write-up, or "Theory Y memo" for a company or ticker (e.g. "write the memo for PCOR", "draft an investment memo on Procore"). The skill fetches deterministic company data from the local MCP server, then writes a five-section institutional memo as a Markdown file. Trigger it even when the user just names a ticker and asks for "the memo" or "the write-up", since that is the core deliverable this skill produces.
---

# Theory Y Investment Memo

Produce a five-section institutional equity research memo for a stock ticker. The
workflow has two phases: **(1)** fetch hard company data deterministically via the
local MCP server, then **(2)** write the memo yourself, section by section, grounded
strictly in that data.

> **Why there is no LLM API call here.** The original pipeline ran on the Gemini API
> and had to re-feed a compressed running summary into every section because each API
> call was stateless. You are *not* stateless — you hold the whole memo and the data
> payload in context as you write. So skip the summary-compression machinery entirely.
> Just keep the sections coherent and non-repetitive (see Writing rules). The only
> code that still needs to run is the data fetch.

## Phase 0 — Ask the user for output format

Before fetching any data, use the `AskUserQuestion` tool to ask:

> **Which output format do you want for this memo?**
> - **Markdown (.md)** — plain markdown file; PDF rendered via CSS theme
> - **Word (.docx)** — formatted Word document using the branded `.dotx` style template; PDF also generated

Store the answer as `FORMAT` (either `md` or `docx`) and proceed.

---

## Phase 1 — Fetch the data payload

Run the fetch script, which connects to `mcp_server.py` over stdio and calls the
`build_company_context` tool. Use the project's virtual environment (it has the `mcp`
package and can launch the server):

```bash
.venv/bin/python3 src/fetch_context.py <TICKER>
```

This writes `output/context/context_<TICKER>.json` and prints its path.
If the venv lives elsewhere or the server file is not `./src/mcp_server.py`, pass
`--server-python` and `--server` (run with `--help` for all options).

Then **read `output/context/context_<TICKER>.json`**. This JSON is your single source of truth.

**If the fetch fails** (server missing, tool error), stop and report the exact error
to the user rather than writing a memo from memory — fabricated financials are worse
than no memo. Do not substitute your own training knowledge about the company.

## Phase 2 — Write the memo

Write to `output/memos/TheoryY_Memo_<TICKER>.md`. Start the file with:

```markdown
# Investment Memo: <TICKER>
```

Then write these five sections **in order**, each opening with its exact `##` heading:

| # | Section heading | Target length |
|---|-----------------|---------------|
| 1 | `## 1. One-Line Thesis & Valuation Snapshot` | ~250 words |
| 2 | `## 2. Business Overview & Operations` | ~350 words |
| 3 | `## 3. Alternative Data & Macro Signals` | ~450 words |
| 4 | `## 4. Consumer & Public Opinion` | ~250 words |
| 5 | `## 5. Key Risks & Structural Barriers` | ~300 words |
| 6 | `## 6. Investment Recommendation` | ~200 words |

Word targets are guidance, not hard caps — prioritize substance over hitting a count.

## Persona and voice

Write as a **Principal Equity Research Analyst specializing in B2B PropTech and
Industrials**. The voice is institutional and data-dense: lead with hard metrics
(growth rates, margins, multiples, retention, unit economics) and reason explicitly
about **operating leverage** — how revenue scaling flows to the cost structure and
margins. Every claim should be anchored to a number or relationship from the payload.

## Writing rules

- **Ground everything in the payload.** Do not introduce figures, dates, products, or
  events that are not in `context_<TICKER>.json`. If the data is silent on something,
  either omit it or flag the gap explicitly (e.g. "the payload does not disclose net
  retention") — never fill it with a guess.
- **No AI filler.** Ban phrases like "crucial role", "it is important to note", "plays
  a key role", and "in conclusion". Open sections with the analysis itself, not throat-
  clearing.
- **Markdown only**, and start each section with the exact heading from the table.
- **Stay coherent across sections.** Later sections should build on earlier ones (e.g.
  the recommendation in §5 should follow from the thesis in §1, the operations in §2,
  and the risks in §4) without restating them verbatim. This is the coherence the old
  pipeline's running summary was trying to preserve — you get it for free by keeping
  the whole memo in view, so use it.
- **Section-specific emphasis:**
  - §1 — a single crisp thesis sentence, then the valuation snapshot (multiples vs.
    growth, what the market is pricing in).
  - §2 — the business model and operating mechanics: revenue mix, customer base,
    go-to-market, cost structure, and where operating leverage sits.
  - §3 — alternative-data and macro read-through: what the non-financial signals in
    the payload imply for the forward numbers. This is the longest section; make it
    the most analytically differentiated.
  - §4 — consumer and public opinion: use `alt_signals.consumer_sentiment` from the
    payload. Cover sentiment label and score, post volume, top recurring themes, and
    which subreddits surfaced the most signal. Flag if post_count is low (< 5) as
    limited sample. If error is present, note the data gap instead of omitting the
    section. Contextualise the sentiment against the business model — negative Reddit
    chatter means something different for a B2C platform (Zillow) vs. a B2B SaaS
    (Procore) vs. a facilities conglomerate (Honeywell).
  - §5 — concrete, ranked risks and structural barriers, each tied to its impact on
    the thesis or the numbers.
  - §6 — a clear recommendation (direction + conviction) that falls out of §§1–5,
    with the key variables that would change the call.

## Output

Always write the memo content to `output/memos/TheoryY_Memo_<TICKER>.md` first — markdown is
the canonical source regardless of chosen format. Then follow the path for `FORMAT`:

### If FORMAT = md

```bash
.venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_<TICKER>.md --skip-docx
```

This routes through the `.dotx` pipeline: `.md` → `.docx` (pandoc + reference.dotx) → HTML →
PDF (chromium headless). `--skip-docx` skips the Word file and produces only the PDF.

Deliverables: `output/memos/TheoryY_Memo_<TICKER>.md` + `output/memos/TheoryY_Memo_<TICKER>.pdf`

### If FORMAT = docx

Single command — generates both `.docx` (branded Word) and `.pdf` (from that same `.docx`):

```bash
.venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_<TICKER>.md
```

Pipeline (all handled inside the script):
1. `pandoc .md --reference-doc=output/theme/reference.dotx → .docx`
2. `pandoc .docx → HTML`  (structured content from the styled Word document)
3. Inject institutional CSS matching the `.dotx` palette
4. `chromium --headless → .pdf`

If `output/theme/reference.dotx` is missing or corrupt, regenerate it:
```bash
.venv/bin/python3 scripts/build_reference_dotx.py
```

Deliverables: `output/memos/TheoryY_Memo_<TICKER>.md` + `output/memos/TheoryY_Memo_<TICKER>.docx` + `output/memos/TheoryY_Memo_<TICKER>.pdf`

---

## Quick reference

**Example invocation** — Input: "write the Theory Y memo for PCOR"
0. Ask user: md or docx? → store as `FORMAT`
1. `.venv/bin/python3 src/fetch_context.py PCOR` → `output/context/context_PCOR.json`
2. Read `output/context/context_PCOR.json`.
3. Write `output/memos/TheoryY_Memo_PCOR.md`: title + the six `##` sections, in the analyst voice,
   grounded only in the payload.
4. **If md:**   `.venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_PCOR.md --skip-docx`
   **If docx:** `.venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_PCOR.md`
5. Present all output paths to the user.