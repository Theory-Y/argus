"""
export_pdf.py  —  Convert a Theory Y memo markdown to PDF via the .dotx pipeline.

Pipeline:
  1. pandoc  .md  + reference.dotx  →  .docx        (branded Word output)
  2. pandoc  .docx                  →  .html         (structured content extract)
  3. Inject  institutional CSS      into  .html
  4. headless browser (chromium/chrome/edge) →  .pdf

Usage:
  .venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_MU.md
  .venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_MU.md --skip-docx
"""

import argparse, datetime, json, os, re, shutil, subprocess, sys, tempfile

# chart_service lives in src/ alongside the other domain modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
try:
    import chart_service
except Exception as _chart_exc:                              # pragma: no cover
    chart_service = None
    _CHART_IMPORT_ERROR = _chart_exc

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

REFERENCE_DOTX = "output/theme/reference.dotx"
CONTEXT_DIR = "output/context"

# Shared figure-number placeholder. Charts (chart_service) and tables both emit
# this in their captions; number_figures() swaps each for "Figure N" in document
# order. Sourced from chart_service so the literal lives in one place, with a
# fallback for when the chart module fails to import (tables still need it).
FIG_PLACEHOLDER = getattr(chart_service, "FIG_PLACEHOLDER", "[[#fig]]")

# Pandoc markdown dialect. Subscript/superscript are disabled because memos use
# "~" to mean "approximately" (e.g. ~$306.6B); with the default extension on,
# a "~" pair silently turns the text between them into a <sub> run, which then
# fights the surrounding <strong> and renders in the wrong (serif/bold) font.
PANDOC_MD = "markdown-subscript-superscript"

def _ensure_table_blank_lines(md: str) -> str:
    """Insert a blank line between [[table:...]] tokens and the pipe table that follows.

    Pandoc collapses a [[table:...]] line and an immediately-adjacent pipe-table
    row into a single <p> when no blank line separates them, so no <table> element
    is emitted and _TABLE_TOKEN_RE never matches. This pass inserts the required
    blank line defensively so the memo author doesn't need to remember the quirk.
    """
    return re.sub(r'(\[\[table:[^\]]*\]\])\n(\|)', r'\1\n\n\2', md)


def _sanitize_footnote_markers(md: str) -> str:
    """Convert ^(x) markdown footnote notation to <sup>x</sup> HTML.

    The pandoc superscript extension is disabled (PANDOC_MD) to prevent bare
    "~" from becoming <sub>. Any ^(x) the LLM writes therefore renders as
    literal text. This pass normalises them to inline HTML that survives pandoc.
    """
    return re.sub(r'\^\(([^)\n]+)\)', lambda m: f'<sup>{m.group(1)}</sup>', md)


# Matches [[chart:name]] tokens, including the <p>…</p> pandoc wraps them in.
_CHART_TOKEN_RE = re.compile(
    r"(?:<p>)?\s*\[\[chart:([a-z_]+)\]\]\s*(?:</p>)?", re.IGNORECASE
)

# Matches a [[table:Caption text]] token immediately followed by its <table>.
# The caption text is everything up to the closing "]]". The trailing <table>
# is captured so the caption can be injected into that exact table.
_TABLE_TOKEN_RE = re.compile(
    r"(?:<p>)?\s*\[\[table:(.*?)\]\]\s*(?:</p>)?\s*(<table\b[^>]*>)",
    re.IGNORECASE | re.DOTALL,
)

# Browser binary names/paths vary by OS and distro. Probed in order; first hit wins.
_BROWSER_CANDIDATES = [
    "chromium", "chromium-browser",
    "google-chrome", "google-chrome-stable", "chrome",
    "msedge", "microsoft-edge", "microsoft-edge-stable",
    # macOS application bundles
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    # Windows default install locations
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str:
    """Locate a Chromium-family browser for headless PDF rendering."""
    env = os.environ.get("CHROMIUM_BIN") or os.environ.get("CHROME_BIN")
    if env and (shutil.which(env) or os.path.isfile(env)):
        return env
    for cand in _BROWSER_CANDIDATES:
        found = shutil.which(cand) or (cand if os.path.isfile(cand) else None)
        if found:
            return found
    sys.exit(
        "ERROR: no Chromium-family browser found for PDF rendering.\n"
        "Install one of: chromium, google-chrome, or microsoft-edge,\n"
        "or set CHROMIUM_BIN=/path/to/browser. (See setup.sh / setup.ps1.)"
    )

# ── institutional CSS injected into pandoc HTML ──────────────────────────────
CSS = """
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,600;0,700;1,400;1,600&family=Calibri:wght@400;600;700&display=swap');

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

:root{
  --navy:    #0D1F3C;
  --navy-lt: #1E3A5F;
  --gold:    #B8922A;
  --ink:     #1A1A1A;
  --slate:   #4A5568;
  --silver:  #F4F6F9;
  --rule:    #CBD5E0;
  --white:   #FFFFFF;
  --page-w:  750px;
}

@page{size:letter;margin:0.75in 0.875in 0.85in 0.875in}

html{font-size:10.5pt;-webkit-print-color-adjust:exact;print-color-adjust:exact}

body{
  font-family:"Calibri",Arial,sans-serif;
  color:var(--ink);
  background:var(--white);
  line-height:1.45;
  max-width:var(--page-w);
  margin:0 auto;
  padding:28px 0 40px;
}

/* ── Title block ─────────────────────────────────────────────────────────── */
h1.title{
  font-family:"EB Garamond",Georgia,serif;
  font-size:26pt;
  font-weight:700;
  color:var(--navy);
  letter-spacing:-0.02em;
  line-height:1.1;
  margin-bottom:4px;
  padding-bottom:10px;
  border-bottom:3px solid var(--gold);
}
p.subtitle{
  font-family:"Calibri",Arial,sans-serif;
  font-size:9.5pt;
  color:var(--slate);
  font-style:italic;
  margin-top:6px;
  margin-bottom:28px;
  letter-spacing:0.01em;
}

/* ── Section headings ────────────────────────────────────────────────────── */
h1,h2,h3,h4{page-break-after:avoid}

/* # level (document title if no YAML title) */
h1{
  font-family:"EB Garamond",Georgia,serif;
  font-size:22pt;
  font-weight:700;
  color:var(--navy);
  margin-top:36px;
  margin-bottom:6px;
  padding-bottom:8px;
  border-bottom:2.5px solid var(--navy);
  letter-spacing:-0.01em;
}

/* ## section headers */
h2{
  font-family:"EB Garamond",Georgia,serif;
  font-size:14pt;
  font-weight:700;
  color:var(--navy);
  margin-top:38px;
  margin-bottom:8px;
  padding-bottom:5px;
  border-bottom:1.5px solid var(--navy);
  letter-spacing:-0.005em;
}

/* ### sub-section */
h3{
  font-family:"Calibri",Arial,sans-serif;
  font-size:11pt;
  font-weight:700;
  font-style:italic;
  color:var(--gold);
  margin-top:20px;
  margin-bottom:4px;
}

/* #### detail label */
h4{
  font-family:"Calibri",Arial,sans-serif;
  font-size:10.5pt;
  font-weight:700;
  color:var(--slate);
  margin-top:16px;
  margin-bottom:2px;
}

/* ── Body copy ───────────────────────────────────────────────────────────── */
p{margin-bottom:9px;text-align:justify;hyphens:auto;orphans:3;widows:3}

strong{font-weight:700;color:var(--ink)}
em{font-style:italic;color:var(--ink)}

/* ── Tables ──────────────────────────────────────────────────────────────── */
table{
  width:100%;
  border-collapse:collapse;
  font-size:9.5pt;
  margin:14px 0 18px;
  page-break-inside:avoid;
  break-inside:avoid;
}
/* Numbered table caption — same visual language as chart figcaptions:
   Calibri 8.5pt, slate colour, navy bold label, border-top rule, placed below. */
caption{
  caption-side:bottom;
  text-align:left;
  font-family:"Calibri",Arial,sans-serif;
  font-size:8.5pt;
  font-weight:400;
  color:var(--slate);
  line-height:1.4;
  padding:7px 0 0;
  margin-top:8px;
  border-top:1px solid var(--rule);
}
caption strong{color:var(--navy);font-weight:700}
thead tr{
  background:var(--navy);
  color:var(--white);
}
thead th{
  padding:7px 10px;
  font-family:"Calibri",Arial,sans-serif;
  font-weight:700;
  font-size:9pt;
  text-align:left;
  letter-spacing:0.03em;
  text-transform:uppercase;
  border:none;
}
tbody tr:nth-child(even){background:var(--silver)}
tbody tr:nth-child(odd) {background:var(--white)}
tbody td{
  padding:6px 10px;
  border-bottom:1px solid var(--rule);
  vertical-align:top;
}
tbody tr:last-child td{border-bottom:1.5px solid var(--navy)}

/* ── Blockquotes ─────────────────────────────────────────────────────────── */
blockquote{
  font-family:"EB Garamond",Georgia,serif;
  font-size:10.5pt;
  font-style:italic;
  color:var(--slate);
  border-left:4px solid var(--gold);
  margin:14px 0;
  padding:6px 16px;
  background:var(--silver);
  break-inside:avoid;
}

/* ── Code / pre ──────────────────────────────────────────────────────────── */
code{
  font-family:"Courier New",monospace;
  font-size:8.5pt;
  background:var(--silver);
  padding:1px 4px;
  border-radius:2px;
  color:var(--navy-lt);
}
pre{
  font-family:"Courier New",monospace;
  font-size:8pt;
  background:var(--silver);
  border-left:3px solid var(--rule);
  padding:10px 14px;
  margin:12px 0;
  overflow-x:auto;
  line-height:1.4;
}
pre code{background:none;padding:0;border-radius:0}

/* ── Lists ───────────────────────────────────────────────────────────────── */
ul,ol{padding-left:20px;margin-bottom:9px}
li{margin-bottom:3px;line-height:1.4}
li p{margin-bottom:3px}

/* ── Horizontal rule ─────────────────────────────────────────────────────── */
hr{
  border:none;
  border-top:1.5px solid var(--rule);
  margin:24px 0;
}

/* ── Header / Ticker watermark ───────────────────────────────────────────── */
.doc-header{
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  padding-bottom:10px;
  border-bottom:3px double var(--navy);
  margin-bottom:20px;
}
.doc-header .firm{
  font-family:"EB Garamond",Georgia,serif;
  font-size:10pt;
  font-weight:700;
  color:var(--navy);
  letter-spacing:0.08em;
  text-transform:uppercase;
}
.doc-header .meta{
  font-size:8pt;
  color:var(--slate);
  text-align:right;
  line-height:1.5;
}

/* ── Charts / figures ──────────────────────────────────────────────────────── */
figure.chart{
  margin:18px 0 20px;
  padding:14px 16px 10px;
  background:var(--white);
  border:1px solid var(--rule);
  border-top:3px solid var(--gold);
  border-radius:3px;
  page-break-inside:avoid;
  break-inside:avoid;
}
figure.chart .chart-svg{
  display:block;
  width:100%;
  height:auto;
  overflow:visible;
}
figure.chart figcaption{
  font-family:"Calibri",Arial,sans-serif;
  font-size:8.5pt;
  color:var(--slate);
  line-height:1.4;
  margin-top:8px;
  padding-top:7px;
  border-top:1px solid var(--rule);
  text-align:left;
}
figure.chart figcaption strong{color:var(--navy)}
figure.chart--empty{border-top-color:var(--rule)}
figure.chart .chart-empty-box{
  display:flex;flex-direction:column;gap:3px;
  padding:14px;background:var(--silver);border-radius:2px;
  font-family:"Calibri",Arial,sans-serif;font-size:9pt;color:var(--slate);
}
figure.chart .chart-empty-box strong{color:var(--navy)}

/* ── Print overrides ─────────────────────────────────────────────────────── */
/* Sections flow continuously (no forced page-per-section, which stranded
   half-empty pages). Headings keep break-after:avoid so a heading never lands
   alone at the foot of a page, and tables/figures carry break-inside:avoid so
   they never split — together these keep the flow clean without the whitespace. */
@media print{
  a{color:inherit;text-decoration:none}
}
"""

# CJK overlay — injected only for CJK languages (see _CJK_LANGS) so Latin-script
# memos (en/es/fr) keep the exact original font stacks and never embed a CJK face.
# It appends the locally-installed Noto CJK **SC** family (correct weight, full
# Simplified coverage, offline) ahead of the Google webfont fallback, re-declaring
# the same selectors as the base CSS so the cascade order makes these win. Charts
# carry their own CJK fallback inline (chart_service FONT_SANS/FONT_SERIF).
_CJK_LANGS = {"zh"}
_CJK_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@400;600;700&display=swap');
body,p.subtitle,h3,h4,thead th,caption,figure.chart figcaption,.doc-header .meta,tbody td{font-family:"Calibri",Arial,"Noto Sans CJK SC","Noto Sans SC",sans-serif}
h1,h1.title,h2,blockquote,.doc-header .firm{font-family:"EB Garamond",Georgia,"Noto Serif CJK SC","Noto Serif SC",serif}
"""


def run(cmd, **kwargs):
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(f"ERROR running: {' '.join(cmd)}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result


# Localized header chrome. The firm name "Theoryy Research" is a brand and stays
# verbatim; only the descriptor + the institutional-use banner translate. Falls
# back to English for any unknown lang.
# BCP-47 document-language tags. The script subtag on zh ("zh-Hans") is what makes
# the headless browser resolve Han characters to the Simplified (SC) glyph variants
# / Noto Sans CJK **SC** face — a bare "zh" is ambiguous (could be Traditional) and
# lets Skia fall back to the Japanese (CJK JP) face for the body text.
_BCP47_LANG = {"en": "en", "zh": "zh-Hans", "es": "es", "fr": "fr"}

_HEADER_CHROME = {
    "en": ("Equity Research",                "INSTITUTIONAL USE ONLY"),
    "zh": ("股票研究",                         "仅供机构使用"),
    "es": ("Análisis de Renta Variable",     "USO INSTITUCIONAL EXCLUSIVO"),
    "fr": ("Recherche Actions",              "USAGE INSTITUTIONNEL EXCLUSIVEMENT"),
}


def inject_header(html: str, ticker: str, date: str, lang: str = "en") -> str:
    research, institutional = _HEADER_CHROME.get(lang, _HEADER_CHROME["en"])
    header_html = f"""<div class="doc-header">
  <div class="firm">Theoryy Research &nbsp;·&nbsp; {research}</div>
  <div class="meta">
    <strong style="font-size:11pt;color:#0D1F3C">{ticker}</strong><br>
    NASDAQ: {ticker} &nbsp;|&nbsp; {date}<br>
    <span style="color:#B8922A;font-weight:600">{institutional}</span>
  </div>
</div>
"""
    return html.replace("<body>", f"<body>\n{header_html}", 1)


def style_title_block(html: str) -> str:
    """Activate the hero title styling and declutter the document head.

    Pandoc renders the memo's ``# …`` line as a plain ``<h1>`` and the optional
    ``*Firm | Generated: …*`` line as a plain ``<p><em>…</em></p>`` — so the
    ``h1.title`` / ``p.subtitle`` CSS never engages. We add those classes here
    (the same post-process move as ``inject_header``) rather than touch the memo
    content spec, so every existing ``.md`` benefits without being rewritten.

    Three passes:
      1. Promote the first ``<h1>`` to the gold-underlined hero title.
      2. Class the subtitle paragraph and strip a redundant leading firm name —
         the masthead already carries "Theoryy Research", so repeating it in the
         subtitle is noise.
      3. Drop ``<hr>`` rules that sit directly before a section ``<h2>`` (the
         memo's ``---`` separators). The navy-ruled headings already separate
         sections; removing the rules clears the heavy triple-line stack under
         the title and keeps the flowing layout clean.
    """
    # 1. hero title
    html = re.sub(r"<h1\b", '<h1 class="title"', html, count=1)

    # 2. subtitle paragraph immediately after the title (skipped when absent)
    def _subtitle(match: "re.Match") -> str:
        text = match.group(2).strip()
        text = re.sub(r"^\s*Theory\s*Y\s+Research\s*[|·\-–—]\s*", "", text,
                      flags=re.IGNORECASE)
        return f'{match.group(1)}<p class="subtitle">{text}</p>'

    html = re.sub(r"(</h1>\s*)<p><em>(.*?)</em></p>", _subtitle, html,
                  count=1, flags=re.DOTALL)

    # 3. drop section-divider rules (incl. the one under the title block)
    html = re.sub(r"<hr\s*/?>\s*(?=<h2)", "", html, flags=re.IGNORECASE)
    return html


def load_context(ticker: str, override: str | None = None) -> dict:
    """
    Load the deterministic MCP context payload for *ticker*. Returns {} when the
    file is missing or unreadable so chart injection degrades gracefully.
    """
    path = override or os.path.join(CONTEXT_DIR, f"context_{ticker}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        print(f"      · no context payload at {path} — charts use live/empty data")
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"      · could not read context {path}: {exc}", file=sys.stderr)
        return {}


def inject_charts(html: str, ticker: str, context: dict, lang: str = "en") -> str:
    """Replace every [[chart:name]] token in *html* with its rendered SVG figure."""
    if chart_service is None:
        print(f"      · chart_service unavailable ({_CHART_IMPORT_ERROR}); "
              "leaving tokens in place", file=sys.stderr)
        return _CHART_TOKEN_RE.sub("", html)

    rendered: list[str] = []

    def _replace(match: "re.Match") -> str:
        name = match.group(1).lower()
        svg = chart_service.build_chart(name, ticker, context, lang=lang)
        rendered.append(name)
        return svg  # "" for unknown tokens → cleanly removed

    new_html, n = _CHART_TOKEN_RE.subn(_replace, html)
    if n:
        print(f"      · injected {n} chart(s): {', '.join(rendered)}")
    return new_html


def inject_table_captions(html: str) -> str:
    """
    Turn every ``[[table:Caption]]`` token into a ``<caption>`` on the table that
    follows it, placed below the table (caption-side:bottom) and styled to match
    the chart figcaptions. The caption opens with the shared figure placeholder
    rather than a number — ``number_figures`` assigns the running figure number
    later, in document order, so tables and charts share one sequence. Tokens
    with no following table, or tables with no token, are left untouched.
    """
    def _replace(match: "re.Match") -> str:
        title = match.group(1).strip()
        table_open = match.group(2)
        return (
            f"{table_open}\n"
            f"<caption><strong>{FIG_PLACEHOLDER} — {title}</strong></caption>"
        )

    new_html, n = _TABLE_TOKEN_RE.subn(_replace, html)
    if n:
        print(f"      · captioned {n} table(s)")
    # Any leftover [[table:…]] tokens (no following table) are stripped cleanly.
    new_html = re.sub(
        r"(?:<p>)?\s*\[\[table:.*?\]\]\s*(?:</p>)?", "", new_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return new_html


# Localized figure-label word. Chart/table captions read "<word> N — caption".
_FIGURE_WORD = {"en": "Figure", "zh": "图", "es": "Figura", "fr": "Figure"}


def number_figures(html: str, lang: str = "en") -> str:
    """
    Assign the single running ``Figure N`` sequence shared by charts and tables.

    Both chart figcaptions (from chart_service) and table captions open with
    ``FIG_PLACEHOLDER``. This pass walks the fully-assembled HTML top-to-bottom
    and replaces the Nth placeholder with ``<word> N`` (the word localized per
    *lang*), so the numbers always match the order figures actually appear in the
    document — regardless of how charts and tables interleave.
    """
    word = _FIGURE_WORD.get(lang, _FIGURE_WORD["en"])
    counter = {"n": 0}

    def _replace(_match: "re.Match") -> str:
        counter["n"] += 1
        return f"{word} {counter['n']}"

    new_html, n = re.subn(re.escape(FIG_PLACEHOLDER), _replace, html)
    if n:
        print(f"      · numbered {n} figure(s) in document order")
    return new_html


def render_pdf(html_path: str, pdf_path: str) -> None:
    """Render *html_path* to *pdf_path* without browser-injected headers or footers.

    Prefers Playwright (CDP `displayHeaderFooter=false`) because the legacy
    `--print-to-pdf-no-header` CLI flag is a no-op on Chromium 112+.
    Falls back to direct CLI invocation when Playwright is unavailable.
    """
    if _PLAYWRIGHT_AVAILABLE:
        with _sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"file://{os.path.abspath(html_path)}")
            page.pdf(
                path=pdf_path,
                print_background=True,
                display_header_footer=False,
                prefer_css_page_size=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            browser.close()
    else:
        browser = find_browser()
        run([browser, "--headless", "--no-sandbox", "--disable-gpu",
             f"--print-to-pdf={pdf_path}", "--print-to-pdf-no-header", html_path])


def main():
    parser = argparse.ArgumentParser(description="Export memo to PDF via .dotx pipeline")
    parser.add_argument("md_path", help="Path to the markdown memo")
    parser.add_argument("--skip-docx", action="store_true",
                        help="Skip .docx generation; use existing .docx")
    parser.add_argument("--date", default=None,
                        help="Header date string (default: today's date)")
    parser.add_argument("--context", default=None,
                        help="Path to context_<TICKER>.json (default: output/context/)")
    parser.add_argument("--no-charts", action="store_true",
                        help="Disable [[chart:…]] token rendering")
    parser.add_argument("--lang", default="en", choices=["en", "zh", "es", "fr"],
                        help="Memo language: selects CJK font fallback + localized "
                             "header chrome (default: en)")
    args = parser.parse_args()

    if args.date is None:
        d = datetime.date.today()
        args.date = f"{d.strftime('%B')} {d.day}, {d.year}"

    md_path   = args.md_path
    base       = os.path.splitext(md_path)[0]
    docx_path  = base + ".docx"
    pdf_path   = base + ".pdf"

    # Infer ticker from filename. The [A-Z]+ class stops at the first underscore,
    # so a localized memo like TheoryY_Memo_NVDA_zh.md still yields "NVDA" — charts
    # and context_<TICKER>.json resolve correctly regardless of the _<lang> suffix.
    m = re.search(r"TheoryY_Memo_([A-Z]+)", os.path.basename(md_path))
    ticker = m.group(1) if m else "MEMO"

    # Pre-process the markdown once; both pandoc calls below use the result.
    with open(md_path, encoding="utf-8") as _fh:
        md_content = _sanitize_footnote_markers(_ensure_table_blank_lines(_fh.read()))

    # ── Step 1: md → docx via reference.dotx ──────────────────────────────
    if not args.skip_docx:
        print(f"[1/3] pandoc  {md_path} → {docx_path}  (using {REFERENCE_DOTX})")
        run(["pandoc", "-f", PANDOC_MD,
             "--reference-doc", REFERENCE_DOTX,
             "-o", docx_path], input=md_content)
        print(f"      ✓ {docx_path}")

    # ── Step 2: md → html directly (avoids docx round-trip drift in table rendering) ──
    print(f"[2/3] pandoc  {md_path} → HTML")
    result = run(["pandoc", "-f", PANDOC_MD, "-t", "html", "--standalone"], input=md_content)
    html = result.stdout

    # ── Inject CSS + header ────────────────────────────────────────────────
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    style = CSS + (_CJK_CSS if args.lang in _CJK_LANGS else "")
    html = html.replace("</head>", f"<style>\n{style}\n</style>\n</head>", 1)
    # Set the document language so the browser applies correct line-breaking
    # (CJK wrapping for zh, hyphenation for es/fr) AND the right Han glyph variant
    # (zh-Hans → Simplified/SC face). Pandoc emits <html ... lang="">; overwrite any
    # existing lang attr, else add one.
    doc_lang = _BCP47_LANG.get(args.lang, args.lang)
    if re.search(r"<html[^>]*\blang=", html):
        html = re.sub(r'(<html[^>]*\blang=")[^"]*(")', rf"\g<1>{doc_lang}\g<2>", html, count=1)
    else:
        html = re.sub(r"<html\b", f'<html lang="{doc_lang}"', html, count=1)
    html = inject_header(html, ticker, args.date, args.lang)
    html = style_title_block(html)

    # ── Inject data-driven charts (live price + payload signals) ───────────────
    if args.no_charts:
        html = _CHART_TOKEN_RE.sub("", html)
    else:
        context = load_context(ticker, args.context)
        html = inject_charts(html, ticker, context, args.lang)

    # Caption tables (runs for both chart modes), then assign the single running
    # Figure N sequence over charts + tables in the order they appear.
    html = inject_table_captions(html)
    html = number_figures(html, args.lang)

    with tempfile.NamedTemporaryFile(suffix=".html", mode="w",
                                     delete=False, encoding="utf-8") as tf:
        tf.write(html)
        tmp_html = tf.name

    # ── Step 3: html → pdf via Playwright (CDP displayHeaderFooter=false) ────
    renderer = "playwright" if _PLAYWRIGHT_AVAILABLE else find_browser()
    print(f"[3/3] {renderer if isinstance(renderer, str) else os.path.basename(renderer)} → {pdf_path}")
    render_pdf(tmp_html, pdf_path)
    os.unlink(tmp_html)
    size = os.path.getsize(pdf_path)
    print(f"      ✓ {pdf_path}  ({size/1024:.0f} KB)")
    if args.skip_docx:
        print(f"\nDeliverables\n  PDF  : {pdf_path}")
    else:
        print(f"\nDeliverables\n  Word : {docx_path}\n  PDF  : {pdf_path}")


if __name__ == "__main__":
    main()
