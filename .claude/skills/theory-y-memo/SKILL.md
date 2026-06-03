---
name: theory-y-memo
description: Generate a Theory Y institutional equity research memo for a given stock ticker. Use this whenever the user asks for an investment memo, equity research write-up, or "Theory Y memo" for a company or ticker (e.g. "write the memo for PCOR", "draft an investment memo on Procore"). The skill fetches deterministic company data from the local MCP server, then writes a five-section institutional memo as a Markdown file. Trigger it even when the user just names a ticker and asks for "the memo" or "the write-up", since that is the core deliverable this skill produces.
---

# Theory Y Investment Memo

Two phases: **(1)** fetch hard data deterministically from the local MCP server, then
**(2)** write the memo yourself, grounded strictly in that data. No LLM API call —
you hold the whole memo and payload in context, so keep sections coherent and
non-repetitive without any summary-compression machinery.

## Phase 0 — Format & languages

Use `AskUserQuestion` (one call, two questions):
1. **Format** → `FORMAT` = `md` (markdown→PDF via CSS) or `docx` (branded Word + PDF).
2. **Languages** (multi-select) → `LANGS` = subset of `{zh, es, fr}`. English is always produced.

## Phase 1 — Fetch the payload

```bash
.venv/bin/python3 src/fetch_context.py <TICKER>
```

Writes `output/context/context_<TICKER>.json`. **Read it — it is your single source of
truth.** Pass `--server-python`/`--server` if the venv or `src/mcp_server.py` moved
(`--help` for options). **If the fetch fails, stop and report the exact error** — never
write from memory; fabricated financials are worse than no memo.

## Phase 2 — Write the memo

Write to `output/memos/TheoryY_Memo_<TICKER>.md`, starting with `# Investment Memo: <TICKER>`,
then these six sections in order, each opening with its exact `##` heading:

| Section heading | ~Words |
|---|---|
| `## 1. One-Line Thesis & Valuation Snapshot` | 250 |
| `## 2. Business Overview & Operations` | 350 |
| `## 3. Alternative Data & Macro Signals` | 450 |
| `## 4. Consumer & Public Opinion` | 250 |
| `## 5. Key Risks & Structural Barriers` | 300 |
| `## 6. Investment Recommendation` | 200 |

Word targets are guidance — prioritize substance.

### Charts & figures

Place each token on its own blank line. The exporter renders data-driven SVG from live
yfinance + payload data (you supply no numbers); unmatched tokens degrade to a small
"unavailable" note, so they're always safe.

| Token | Section | Anchor |
|---|---|---|
| `[[chart:price_history]]` | §1 | after the valuation-snapshot table |
| `[[chart:valuation_comps]]` | §1 | after the peer comp table |
| `[[chart:margins]]` | §2 | near the operating-leverage discussion |
| `[[chart:search_trends]]` | §3 | start of the Google-Trends discussion |
| `[[chart:sentiment_sources]]` | §4 | after the per-source sentiment table |

Charts **complement** tables — keep the tables. Caption every table: put
`[[table:Caption text]]` on the line **immediately above** it (snapshot, peer comps,
segment/revenue mix, per-source sentiment). Charts and tables share **one running
`Figure N` sequence** assigned by the exporter top-to-bottom — never write figure
numbers yourself; refer to figures by description, not "Figure 3".

### Persona & voice

Write as a **Principal Equity Research Analyst** in the issuer's sector (read
`payload.target.sector`/`industry`; engine is sector-agnostic). Institutional,
data-dense: lead with hard metrics and reason explicitly about **operating leverage**.
Every claim anchored to a payload number/relationship or an explicitly sourced external figure.

### Writing rules

- **Ground everything in the payload.** No figures/dates/products/events absent from it;
  if data is silent, omit or flag the gap explicitly — never guess.
- **No AI filler** ("crucial role", "it is important to note", "in conclusion"). Open with analysis.
- **Markdown only**; exact headings.
- **Coherence across sections** — later sections build on earlier (§6 follows from §§1–5) without verbatim restatement.
- **Per-section emphasis:**
  - §1 — one crisp thesis sentence + valuation snapshot (rigor rules 1–2). If
    `alt_signals.massive_price_metrics` has no `error`, anchor with current price, 52-week
    range (`high_52w`/`low_52w`, note near high vs low), `return_1y_pct`, and `return_30d_pct` if present.
  - §2 — business model & operating mechanics: revenue mix, customers, GTM, cost structure, where leverage sits.
  - §3 — longest, most differentiated. Alt-data/macro read-through to forward numbers.
    Rigor rules 5–6. `alt_signals.massive_news`: when `article_count` ≥ 3 and
    `blended_sentiment` non-null, frame news momentum; cite `articles[*].sentiment_reasoning`
    as press/analyst perspectives (publisher + date), and prefer it over lexicon-scored RSS
    on conflict. If `error` or `article_count` 0, note the gap. `massive_price_metrics` can
    contextualize demand signals (e.g. Trends uptick + 30-day price recovery).
  - §4 — lead with `alt_signals.consumer_sentiment`. Source priority: StockTwits (Bull/Bear),
    Yahoo news, HackerNews; Reddit is thin-source fallback. Structure: (a) overall label +
    score + `confidence`; (b) per-source breakdown weighed by `signal_count` + `confidence`
    (not raw `message_count`), discounting extreme scores on low signal counts (rule 8);
    (c) ≤4 verbatim `top_quotes` as blockquotes with source label, skipping 0-message/error
    sources. Supplement with `massive_news` reasoning that reflects investor/public reaction.
    If overall `confidence` "low", say §4 is directional only. Contextualize sentiment vs
    business model (B2C vs B2B vs conglomerate). Also read `alt_signals.web_research`
    (first-hand scrape of full news article bodies + niche forums): its
    `forum_posts_toon`/`news_extracts_toon` are compact TOON tables (or minified JSON when
    smaller) — read them as the arrays they encode, never quote the serialization markup.
    Honor its `sentiment`/`confidence` and weave a `top_quotes` excerpt where it sharpens
    §3/§4; when `available` is false or `error` is set, skip it (don't invent forum chatter).
    Calibrate by `extraction_mode`: `"lexical"` (no-LLM keyword scoring of page text) is a
    directional read like the other lexicon sources; `"llm"` (structured extraction) may be
    cited more concretely. Never let a low-`confidence` web_research read anchor the call.
  - §5 — concrete, ranked risks/barriers, each tied to thesis or numbers.
  - §6 — clear direction + conviction falling out of §§1–5, with variables that would change the call.

### Analytical rigor (non-negotiable — each maps to a past failure)

1. **Bridge every valuation gap; never assert "cheap" without math.** When a forward
   multiple diverges from a trailing one, show the implied-earnings bridge: implied fwd
   net income = `market cap ÷ forward P/E`, vs trailing, and the growth × margin step
   required. State which forward period a "forward" multiple references (NTM vs out-year).
   Present as a term structure (trailing → NTM → out-year).
2. **Always do a cross-sectional peer comp.** Use `payload.peers`; **empty peers = coverage
   gap, not absence of comparables** — source 2–4 real peers externally, build a comp table
   (fwd P/E, EV/Revenue, EV/EBITDA, growth, PEG), label as external. Never write "relative
   valuation not possible." Check `data_quality.flagged_comparables` first: a peer reading
   `N/M` or flagged `currency_mismatch` (e.g. a non-USD ADR like TSMC) is non-certifiable —
   source it externally rather than printing or dropping it.
3. **Source segment mix when the payload omits it** — pull the latest 10-Q/8-K/earnings and
   tabulate. Don't write "segment mix not disclosed" as a substitute.
4. **Internal-contradiction check before finalizing.** A datapoint must not be a positive in
   one section and a risk in another without explicit reconciliation — pick a net stance or
   show the offset, state it once.
5. **Gate every macro/alt-data signal on a stated transmission mechanism** to *this* issuer's
   revenue/margins. Honor `macro_fred.relevance`: if `"low"`, omit or label low-relevance
   backdrop — never manufacture correlation.
6. **Investigate signals; don't just flag "smoke."** For governance/litigation/insider flags
   (5.02 filings, EDGAR-fallback litigation node), either resolve via the underlying source
   (proxy, press, PACER, 8-K text) or name the specific next source to check and that it's a gap.
7. **Honor `data_quality`; never present a flagged figure as fact.** Flags: `currency_mismatch`
   (multiple wrong by FX, set `N/M` — source externally), `peer_outlier`/`implausible` (verify
   vs primary filing; distinguish real-but-extreme from artifact). **Exclude flagged values
   before computing any median/average or "cheap vs peers" claim.**
8. **Calibrate confidence to the data.** Weigh `consumer_sentiment` by `signal_count` not
   `message_count`; an extreme score (±1.0) on low signal count is noise. A source with
   `confidence:"low"` or `signal_count`<3 may be a soft signal but must **never** anchor a
   thesis, §5 risk pillar, or §6 call. If overall `confidence` "low", §4 is directional only.
   For `massive_news` with `article_count`<3, treat `blended_sentiment` as directional;
   cite `sentiment_reasoning` as press perspective, not verified conclusion. Match language
   strength to evidence strength.

When external sourcing is used, add a short **Sourcing note** at the end distinguishing
payload-derived from externally fetched figures.

## Output

Always write the `.md` first (canonical), then per `FORMAT`:

- **md:** `.venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_<TICKER>.md --skip-docx` → `.md` + `.pdf`
- **docx:** `.venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_<TICKER>.md` → `.md` + `.docx` + `.pdf`

Pipeline: `.md` →(pandoc + `output/theme/reference.dotx`)→ `.docx` → HTML + institutional CSS
→ chromium headless → `.pdf`. If `reference.dotx` is missing/corrupt, regenerate with
`.venv/bin/python3 scripts/build_reference_dotx.py`.

## Phase 3 — Localization (only if `LANGS` non-empty)

The English memo is canonical. **Dispatch one `Agent` (`subagent_type: theory-y-translator`)
per language, all in one message** so they run concurrently and in isolation. That worker
carries only the tools the job needs (no MCP/plugin catalog) and runs on a lighter model —
translation is faithful glossary work, not re-analysis — so each spawn is far cheaper than a
general-purpose agent. Each loads only the English memo + glossary (never the payload or rigor
rules) and returns only paths. Prompt each with just the assignment:

> Translate the finished English Theory Y memo for ticker `<TICKER>` into `<lang>`.

The worker's own definition tells it to drive the `theory-y-localize` skill end-to-end.

Collect returned paths and list every deliverable (English + each localized `.md`/`.pdf`).
