---
name: theory-y-memo
description: Generate a Theory Y institutional equity research memo for a given stock ticker. Use this whenever the user asks for an investment memo, equity research write-up, or "Theory Y memo" for a company or ticker (e.g. "write the memo for PCOR", "draft an investment memo on Procore"). The skill fetches deterministic company data from the local MCP server, then writes a seven-section institutional memo as a Markdown file. Trigger it even when the user just names a ticker and asks for "the memo" or "the write-up", since that is the core deliverable this skill produces.
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
then these seven sections in order, each opening with its exact `##` heading:

| Section heading | ~Words |
|---|---|
| `## 1. One-Line Thesis & Valuation Snapshot` | 250 |
| `## 2. Business Overview & Operations` | 400 |
| `## 3. Alternative Data & Macro Signals` | 450 |
| `## 4. Consumer & Public Opinion` | 300 |
| `## 5. Key Risks & Structural Barriers` | 400 |
| `## 6. Catalyst Map — Bull & Bear Cases` | 350 |
| `## 7. Investment Recommendation` | 250 |

Word counts are **ceilings, not quotas** — a section that makes its point in half the budget
is a better section. Never pad toward a target; the reader is a professional billing their
own time.

### Charts & figures

Place each token on its own blank line. The exporter renders data-driven SVG from live
yfinance + payload data (you supply no numbers); unmatched tokens degrade to a small
"unavailable" note, so they're always safe.

| Token | Section | Anchor |
|---|---|---|
| `[[chart:price_history]]` | §1 | after the valuation-snapshot table |
| `[[chart:valuation_comps]]` | §1 | after the peer comp table |
| `[[chart:valuation_history]]` | §1 | after the multiple-re-rating discussion (FY-end EV/Revenue + trailing P/E; the engine appends today's forward P/E as the gold row) |
| `[[chart:revenue_history]]` | §2 | with the multi-year revenue trajectory discussion (FY-labeled) |
| `[[chart:margins]]` | §2 | near the operating-leverage discussion |
| `[[chart:search_trends]]` | §3 | start of the Google-Trends discussion |
| `[[chart:sentiment_sources]]` | §4 | after the per-source sentiment table |

Charts **complement** tables — keep the tables. Caption every table: put
`[[table:Caption text]]` on the line **immediately above** it (snapshot, peer comps,
segment/revenue mix, per-source sentiment, catalyst map). Charts and tables share **one running
`Figure N` sequence** assigned by the exporter top-to-bottom — never write figure
numbers yourself; refer to figures by description, not "Figure 3".

### Persona & voice

Write as a **Principal Equity Research Analyst** in the issuer's sector (read
`payload.target.sector`/`industry`; engine is sector-agnostic). The reader is a professional
or experienced individual investor: assume fluency (never explain what EV/EBITDA or a 10-K
is), lead with hard metrics, and reason explicitly about **operating leverage**. Every claim
anchored to a payload number/relationship or an explicitly sourced external figure.

Sound like an analyst who has covered the name for years, not a model summarizing a payload:

- Plain declarative sentences, varied in length; one idea per sentence. Let the numbers carry
  the argument — "revenue grew 65%" needs no "remarkable".
- Take a position early and state it flatly: "the multiple already prices this in", never
  "it is worth considering the extent to which this may be priced in".
- Hedge on substance, not in syntax. "I can't verify this", "the data here is thin", "this
  could go either way" are good analyst sentences; reflexive qualifier-stacking is not.
- Bolded paragraph labels only where a section genuinely needs scannable structure (≤3 per
  section), not as a crutch opening every paragraph.

### Writing rules

- **Ground everything in the payload.** No figures/dates/products/events absent from it;
  if data is silent, omit or flag the gap explicitly — never guess.
- **Every sentence earns its place** — it adds a number, a mechanism, or a judgment, or it
  goes. Never narrate what an adjacent table or chart already shows; state only the
  read-through. Open every section with analysis, not preamble.
- **Banned slop patterns** (each caught in past drafts; the final pass in rigor rule 12d
  hunts for them):
  - Filler: "it is important to note", "crucial role", "in conclusion", "Taken together",
    "This matters because/for", "warrants scrutiny".
  - The "not X, but Y" / "not because X, but because Y" rhetorical seesaw more than once
    per memo.
  - Superlative inflation: "unprecedented", "unambiguous", "category of one", "starkest".
  - Both-sides closers that take no position ("constructive but not euphoric") — pick the
    lean and say it.
  - More than one em-dash aside in a sentence.
  - Re-performing §1's thesis in §6/§7 with synonyms — build on it, don't restate it.
- **No naked derived numbers.** Any figure not literally in the payload shows its arithmetic
  at first use (inline or table footnote) and gets an entry in the Analytical-estimates
  appendix. A professional must be able to recompute every number in the memo from the
  references alone.
- **Markdown only**; exact headings.
- **Footnote markers in tables** must use HTML `<sup>a</sup>` — never `^(a)` markdown notation. The exporter disables pandoc superscripts; `^(a)` renders as literal text.
- **Coherence across sections** — later sections build on earlier (§7 follows from §§1–6) without verbatim restatement.
- **Per-section emphasis:**
  - §1 — one crisp thesis sentence + valuation snapshot (rigor rules 1–2). If
    `alt_signals.massive_price_metrics` has no `error`, anchor with current price, 52-week
    range (`high_52w`/`low_52w`, note near high vs low), `return_1y_pct`, and `return_30d_pct` if present.
  - §2 — business model & operating mechanics: revenue mix, customers, GTM, cost structure, where
    leverage sits. **Multi-year framing is mandatory:** use `fundamentals_history.years` to show the
    revenue trajectory across the last 3–5 fiscal years with each year labeled (FY2023, FY2024, …),
    never a single TTM number in isolation. When tabulating segment/revenue mix (rigor rule 3),
    give the mix **percentages for multiple recent years with the year labeled on every column** so
    mix shift is visible, not just the latest split.
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
    Contextualize sentiment vs business model (B2C vs B2B vs conglomerate). Also read `alt_signals.web_research`
    (first-hand scrape of full news article bodies + niche forums): its
    `forum_posts_toon`/`news_extracts_toon` are compact TOON tables (or minified JSON when
    smaller) — read them as the arrays they encode, never quote the serialization markup.
    Honor its `sentiment`/`confidence` and weave a `top_quotes` excerpt where it sharpens
    §3/§4; when `available` is false or `error` is set, skip it (don't invent forum chatter).
    Calibrate by `extraction_mode`: `"lexical"` (no-LLM keyword scoring of page text) is a
    directional read like the other lexicon sources; `"llm"` (structured extraction) may be
    cited more concretely. Never let a low-`confidence` web_research read anchor the call.
    **Per-community breakdown:** name each community individually (StockTwits, Yahoo,
    HackerNews, Reddit subs, web_research niche forums) and state **what that community is
    focused on** (its dominant themes/quotes), not just its score — retail flow, technical
    chatter, product gripes, and professional skepticism are different signals.
  - §5 — concrete, ranked risks/barriers, each tied to thesis or numbers. Mandatory coverage
    (each either assessed or explicitly cleared as not material):
    (a) **named competitive risk** — name the specific competitor(s) from `peers`/dynamic
    discovery and the vector of attack (price, bundling, distribution, technology);
    (b) **margin compression** — which cost line or pricing dynamic could compress EBITDA
    margin, anchored to the payload margin and peer margins;
    (c) **insider selling** — read `alt_signals.insider_activity` and interpret per rigor
    rule 11;
    (d) **guidance credibility** — read `alt_signals.earnings_track` per rigor rule 11 and
    cross-check `sec_8k_events` for guidance language.
    **De-dup vs the 10-K (rigor rule 10):** Item 1A is background, not your risk list.
  - §6 — the catalyst map. Exactly **3 bull catalysts and 3 bear catalysts**, each a row in a
    captioned table with columns: Catalyst | Probability (High/Med/Low) | Magnitude (impact on
    revenue/margins/multiple — operating terms, never price targets) | Timing (window, e.g.
    "2–3 quarters") | Priced in? (Yes/No + one-line why, judged against current multiples vs.
    peers/history) | Public reaction (what §3/§4 sentiment + news data say the market is doing
    with it). Follow with two short paragraphs — **best case** and **worst case** — the
    composite scenario if the bull (resp. bear) catalysts land, stated in operating
    consequences. Every catalyst traces to a payload signal or is labeled externally sourced
    (rigor rule 9).
  - §7 — clear direction + conviction falling out of §§1–6, with the variables that would
    change the call. Must end with three deliverables:
    (a) **conviction score (N/10)**, anchored — 8–10 high-confidence and data-corroborated;
    5–7 directional but signal-limited; ≤4 speculative; thin §3/§4 data caps the score (say so);
    (b) **entry view at the current price** — is the stock attractive *here*, reasoned from
    the 52-week-range position, the valuation-history re-rating path, and what the current
    multiple already prices in; a judgment, never a price target;
    (c) **monitoring list** — the 3–5 concrete things to watch next (filings, prints, §6
    catalyst windows) and which of them would flip the call.

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
   thesis, §5 risk pillar, or §7 call. If overall `confidence` "low", §4 is directional only.
   For `massive_news` with `article_count`<3, treat `blended_sentiment` as directional;
   cite `sentiment_reasoning` as press perspective, not verified conclusion. Match language
   strength to evidence strength.
9. **Catalyst discipline (§6).** Every catalyst carries all five table attributes (§6 defines
   them) — one you can't time or size is a theme, not a catalyst; drop it. "Priced in?" is
   argued, never asserted. **Never emit price targets** anywhere in the memo.
10. **Key risks are not the 10-K.** `sec_risk_snippet` (Item 1A) is background reference
    only — never reproduce its boilerplate as a "key risk". A §5 risk must be specific,
    current, and tied to the numbers; if it overlaps an Item 1A factor, state what is *new*
    beyond the filing (recent 8-K, insider cluster, miss streak, competitor move). Every
    public-document claim must be one click from its source — but link it to the matching
    **References** entry (`#ref-N`), not to the external URL directly; the external URL lives
    once in the References list (see *References & citations* below).
11. **Interpret insider + earnings patterns, don't just report them.** Form 4 data cannot
    distinguish 10b5-1 scheduled sales from discretionary ones — so reason from clustering
    (several officers in a window), size vs. role, buy/sell asymmetry, and proximity to
    events; never call a lone sale a loss of confidence. For `earnings_track`: ≥2 consecutive
    misses or a negative average surprise over 8 quarters is a guidance-credibility risk that
    belongs in §5; a long beat streak with decelerating surprise size is its own signal
    (estimates catching up). Quote the streak/counts, then interpret.
12. **Red-team your own call before finalizing (council-lite).** Before writing §7's last
    paragraph: (a) state the strongest objection to your own recommendation — the best
    argument the other side would make from THIS payload — and either rebut it with data or
    concede it into the conviction score; (b) re-verify the three highest-stakes numbers in
    the memo against the payload (the ones your call would die on if wrong); (c) confirm §1's
    thesis, §5's top risk, and §6's top catalysts are mutually consistent (rule 4); (d) one
    full read purely for the banned slop patterns and quota-padding — cut, don't paraphrase;
    a memo that shrinks in this pass got better. The full
    multi-perspective AI council is a Phase 4 orchestrator feature; this rule is its
    single-agent distillation.

### References & citations

End the memo with a `## References` section listing every external source as a numbered
item, then cite into it from the body. **All in-body links point inward to the reference
entry; only the References list holds external URLs.**

- **Reference list (the only place external URLs appear).** One numbered item per source.
  Prefix each item with a pandoc anchor span `[]{#ref-N}` (matching its number) and end it
  with the external URL as a bare autolink `<https://…>`. Use the pandoc span, **not** a raw
  `<a id="ref-N">` — the docx writer drops raw inline HTML in list items, so the anchor would
  not become a real bookmark. Example:
  `4. []{#ref-4}**NVIDIA Corp., Form 10-K, FY2026** — … <https://www.sec.gov/Archives/edgar/…>`
- **In-body citations point to the reference, never to the external URL.** Numbered
  superscript citations are `<sup>[[N]](#ref-N)</sup>`; inline prose links that reference a
  source (filings, proxy, IR pages) use the reference anchor too — `[FY2026 10-K](#ref-4)`,
  not the SEC URL. The reader clicks once to the References entry, which carries the live link.
- Author-derived estimates that aren't external sources get their own anchored entry
  (e.g. `### []{#a-analytical-estimates}A. Analytical estimates`) and are cited `[[A]](#a-analytical-estimates)`.
- The exporter does no link rewriting — author the `#ref-N` anchors and links directly so the
  PDF/docx carry internal cross-references (GoTo) for citations and external links only in the list.

When external sourcing is used, add a short **Sourcing note** at the end distinguishing
payload-derived from externally fetched figures. External sourcing rules: cite aggregated
press (`massive_news`) by publisher + date — major-outlet perspectives (WSJ, NYT, MarketWatch,
Reuters…) enter the memo through that attributed channel, never by scraping paywalled sites.
Company-website/IR figures not in the 10-K may be cited as externally sourced data reference
with a link; investor pitch decks and other non-public material are out of bounds until the
licensed-source pipeline exists (MNPI gate).

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
