---
name: theory-y-localize
description: Translate an existing English Theory Y investment memo into Mandarin (zh), Spanish (es), or French (fr), preserving all chart/table tokens and institutional terminology, then export the localized PDF. Use this when asked to localize, translate, or produce a non-English version of a memo that already exists at output/memos/TheoryY_Memo_<TICKER>.md. This is the per-language worker that theory-y-memo's localization phase dispatches; it can also be run on its own for a single TICKER + language.
---

# Theory Y Memo — Localization Worker

Translate one finished English memo into one target language. This is the
**portable translation core**: it depends only on (a) the finished English
markdown and (b) the matching glossary — never on the data payload or the memo's
analytical rigor rules. That isolation is deliberate. The expensive analysis was
done once in English; your job is a faithful, market-standard translation, not a
re-analysis. Keep the context lean and **return only file paths** so the caller
never has to hold the translated text.

## Inputs
- `TICKER` — e.g. `NVDA`
- `LANG` — one of `zh` (Mandarin), `es` (Spanish), `fr` (French)

## Step 1 — Load source + glossary
Read both, in full:
1. `output/memos/TheoryY_Memo_<TICKER>.md` — the English source of truth.
2. `localization/glossary.<LANG>.md` — term map + conventions for this language.

If the source memo is missing, stop and report it — do not translate from memory
or regenerate the analysis. If the glossary is missing, stop and report it.

## Step 2 — Translate
Produce a complete `<LANG>` translation of the memo. Apply the glossary's
**Target term** for every listed concept, consistently, and follow its conventions
(acronym-in-parentheses on first use, number formatting, do-not-translate list).

**Preserve verbatim — do not translate or reformat:**
- Every `[[chart:NAME]]` token, exactly as written, on its own line. The PDF
  exporter replaces these with rendered figures; altering them breaks the charts.
- The `[[table:...]]` token wrapper. **Do** translate the human caption text
  *inside* it (e.g. `[[table:Valuation snapshot — …]]` → translated caption), but
  keep the `[[table:` prefix and `]]` suffix intact and keep the token on its own
  line immediately above its table.
- Markdown structure: `#` / `##` heading markers (translate the heading *text*,
  keep the markers and their order), table pipe `|` layout and the `|---|` separator
  rows, blockquote `>` markers, list markers, and `---` horizontal rules.
- Tickers (`NVDA`, `AMD`, `TSM`…), company legal names (`NVIDIA Corporation`), the
  `$` currency symbol, and data-quality flags (`N/M`, `N/A`, `†`).
- **Numeric magnitudes never change.** Only reformat per the glossary's locale rules
  (decimal comma / thin-space thousands for es & fr; keep Western numerals for zh).
  Keep compact scale notation and the `x` multiple suffix **inside tables** as-is
  (`30.6x`, `$5,114B`, `20.0x`) so column alignment survives.

**Translate fully:**
- The `# Investment Memo: <TICKER>` title — translate the words "Investment Memo"
  via the glossary, keep `<TICKER>`.
- All section headings, prose, table cell text, table captions, blockquote text
  (keep the source attribution after `—`, e.g. `— StockTwits`, untranslated since
  it's a source name), and the closing **Sourcing note**.

**Fidelity rules (mirror the memo's own grounding standard):**
- No new facts, no added analysis, no dropped sentences. A faithful translation —
  every claim, number, and caveat in the English memo appears in the translation.
- Match register: this is institutional equity research. Use the formal,
  data-dense voice a native-language sell-side analyst would use, not casual prose.

## Step 3 — Write the localized markdown
Write the translation to:

```
output/memos/TheoryY_Memo_<TICKER>_<LANG>.md
```

## Step 4 — Export the localized PDF
```bash
.venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_<TICKER>_<LANG>.md --skip-docx --lang <LANG>
```

The exporter infers the ticker from the filename (the `_<LANG>` suffix is ignored),
so charts and `context_<TICKER>.json` resolve automatically. `--lang` selects the
CJK font fallback (needed for `zh`) and localizes the PDF header chrome.

## Step 5 — Return
Return **only** the two output paths — the `.md` and the `.pdf`. Do not echo the
translated memo body; the caller wants confirmation and paths, not the content.

Example return:
```
output/memos/TheoryY_Memo_NVDA_zh.md
output/memos/TheoryY_Memo_NVDA_zh.pdf
```
