---
name: theory-y-memo
description: Generate a Theory Y institutional equity research memo for a given stock ticker. Use this whenever the user asks for an investment memo, equity research write-up, or "Theory Y memo" for a company or ticker. Write a five-section institutional memo as a Markdown file grounded in provided company data. Trigger it even when the user just names a ticker and asks for "the memo" or "the write-up", since that is the core deliverable this skill produces.
---

# Theory Y Investment Memo

Produce a six-section institutional equity research memo for a stock ticker based on
provided company data. The workflow has one phase: **(1)** write the memo section by section,
grounded strictly in the data provided.

> **Simplified workflow.** This project no longer fetches data from an MCP server.
> Instead, company data can be provided by the user directly, from external sources,
> or from your training knowledge (with clear attribution). The focus is on clear,
> analytical writing grounded in available facts.

---

## Write the memo

Write to `output/memos/TheoryY_Memo_<TICKER>.md`. Start the file with:

```markdown
# Investment Memo: <TICKER>
```

Then write these six sections **in order**, each opening with its exact `##` heading:

| # | Section heading | Target length |
|---|-----------------|---------------|
| 1 | `## 1. One-Line Thesis & Valuation Snapshot` | ~400 words |
| 2 | `## 2. Business Overview & Operations` | ~600 words |
| 3 | `## 3. Alternative Data & Macro Signals` | ~700 words |
| 4 | `## 4. Consumer & Public Opinion` | ~400 words |
| 5 | `## 5. Key Risks & Structural Barriers` | ~500 words |
| 6 | `## 6. Investment Recommendation` | ~300 words |

Word targets are guidance, not hard caps — prioritize substance over hitting a count.

## Persona and voice

Write as a **Principal Equity Research Analyst specializing in B2B PropTech and
Industrials**. The voice is institutional and data-dense: lead with hard metrics
(growth rates, margins, multiples, retention, unit economics) and reason explicitly
about **operating leverage** — how revenue scaling flows to the cost structure and
margins. Every claim should be anchored to a number or relationship from available data.

## Writing rules

- **Ground everything in available data.** Do not introduce figures, dates, products, or
  events unless they come from provided data or can be verified. If data is silent on something,
  either omit it or flag the gap explicitly (e.g. "public disclosures do not reveal net
  retention") — never fill it with a guess.
- **No AI filler.** Ban phrases like "crucial role", "it is important to note", "plays
  a key role", and "in conclusion". Open sections with the analysis itself, not throat-
  clearing.
- **Markdown only**, and start each section with the exact heading from the table.
- **Stay coherent across sections.** Later sections should build on earlier ones (e.g.
  the recommendation in §6 should follow from the thesis in §1, the operations in §2,
  and the risks in §5) without restating them verbatim.
- **Section-specific emphasis:**
  - §1 — a single crisp thesis sentence, then the valuation snapshot (multiples vs.
    growth, what the market is pricing in).
  - §2 — the business model and operating mechanics: revenue mix, customer base,
    go-to-market, cost structure, and where operating leverage sits.
  - §3 — alternative-data and macro read-through: trends, competitive positioning, and
    forward signals. This is the longest section; make it analytically differentiated.
  - §4 — public sentiment and opinion where available. Contextualize against the business
    model — negative sentiment means something different for B2C vs. B2B vs. industrial.
  - §5 — concrete, ranked risks and structural barriers, each tied to its impact on
    the thesis or the numbers.
  - §6 — a clear recommendation (direction + conviction) that falls out of §§1–5,
    with the key variables that would change the call.

## Output

Always write the memo content to `output/memos/TheoryY_Memo_<TICKER>.md` first —
markdown is the canonical source. Then export to PDF:

```bash
python3 scripts/export_pdf.py output/memos/TheoryY_Memo_<TICKER>.md
```

This uses `md-to-pdf` to produce a clean PDF with institutional styling.

Deliverables: `output/memos/TheoryY_Memo_<TICKER>.md` + `output/memos/TheoryY_Memo_<TICKER>.pdf`

---

## Quick reference

**Example invocation** — Input: "write the Theory Y memo for PCOR"

1. Write `output/memos/TheoryY_Memo_PCOR.md`: title + the six `##` sections, in the analyst voice,
   grounded in provided or verified data.
2. Export to PDF: `python3 scripts/export_pdf.py output/memos/TheoryY_Memo_PCOR.md`
3. Present output paths to the user.
