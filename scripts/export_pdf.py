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

import argparse, json, os, re, shutil, subprocess, sys, tempfile

# chart_service lives in src/ alongside the other domain modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
try:
    import chart_service
except Exception as _chart_exc:                              # pragma: no cover
    chart_service = None
    _CHART_IMPORT_ERROR = _chart_exc

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
  margin-top:32px;
  margin-bottom:6px;
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
p{margin-bottom:9px;text-align:justify;hyphens:auto}

strong{font-weight:700;color:var(--ink)}
em{font-style:italic;color:var(--ink)}

/* ── Tables ──────────────────────────────────────────────────────────────── */
table{
  width:100%;
  border-collapse:collapse;
  font-size:9.5pt;
  margin:14px 0 18px;
  page-break-inside:avoid;
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
@media print{
  a{color:inherit;text-decoration:none}
  h2{page-break-before:always}
  h2:first-of-type{page-break-before:avoid}
}
"""


def run(cmd, **kwargs):
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(f"ERROR running: {' '.join(cmd)}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result


def inject_header(html: str, ticker: str, date: str) -> str:
    header_html = f"""<div class="doc-header">
  <div class="firm">Theory Y Research &nbsp;·&nbsp; Equity Research</div>
  <div class="meta">
    <strong style="font-size:11pt;color:#0D1F3C">{ticker}</strong><br>
    NASDAQ: {ticker} &nbsp;|&nbsp; {date}<br>
    <span style="color:#B8922A;font-weight:600">INSTITUTIONAL USE ONLY</span>
  </div>
</div>
"""
    return html.replace("<body>", f"<body>\n{header_html}", 1)


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


def inject_charts(html: str, ticker: str, context: dict) -> str:
    """Replace every [[chart:name]] token in *html* with its rendered SVG figure."""
    if chart_service is None:
        print(f"      · chart_service unavailable ({_CHART_IMPORT_ERROR}); "
              "leaving tokens in place", file=sys.stderr)
        return _CHART_TOKEN_RE.sub("", html)

    rendered: list[str] = []

    def _replace(match: "re.Match") -> str:
        name = match.group(1).lower()
        svg = chart_service.build_chart(name, ticker, context)
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


def number_figures(html: str) -> str:
    """
    Assign the single running ``Figure N`` sequence shared by charts and tables.

    Both chart figcaptions (from chart_service) and table captions open with
    ``FIG_PLACEHOLDER``. This pass walks the fully-assembled HTML top-to-bottom
    and replaces the Nth placeholder with ``Figure N``, so the numbers always
    match the order figures actually appear in the document — regardless of how
    charts and tables interleave.
    """
    counter = {"n": 0}

    def _replace(_match: "re.Match") -> str:
        counter["n"] += 1
        return f"Figure {counter['n']}"

    new_html, n = re.subn(re.escape(FIG_PLACEHOLDER), _replace, html)
    if n:
        print(f"      · numbered {n} figure(s) in document order")
    return new_html


def main():
    parser = argparse.ArgumentParser(description="Export memo to PDF via .dotx pipeline")
    parser.add_argument("md_path", help="Path to the markdown memo")
    parser.add_argument("--skip-docx", action="store_true",
                        help="Skip .docx generation; use existing .docx")
    parser.add_argument("--date", default="2026-05-28")
    parser.add_argument("--context", default=None,
                        help="Path to context_<TICKER>.json (default: output/context/)")
    parser.add_argument("--no-charts", action="store_true",
                        help="Disable [[chart:…]] token rendering")
    args = parser.parse_args()

    md_path   = args.md_path
    base       = os.path.splitext(md_path)[0]
    docx_path  = base + ".docx"
    pdf_path   = base + ".pdf"

    # infer ticker from filename
    m = re.search(r"TheoryY_Memo_([A-Z]+)", os.path.basename(md_path))
    ticker = m.group(1) if m else "MEMO"

    # ── Step 1: md → docx via reference.dotx ──────────────────────────────
    if not args.skip_docx:
        print(f"[1/3] pandoc  {md_path} → {docx_path}  (using {REFERENCE_DOTX})")
        run(["pandoc", md_path,
             "-f", PANDOC_MD,
             "--reference-doc", REFERENCE_DOTX,
             "-o", docx_path])
        print(f"      ✓ {docx_path}")

    # ── Step 2: docx → html (or md → html when skipping docx) ───────────────
    if args.skip_docx:
        print(f"[2/3] pandoc  {md_path} → HTML")
        result = run(["pandoc", md_path, "-f", PANDOC_MD,
                      "-t", "html", "--standalone"])
    else:
        print(f"[2/3] pandoc  {docx_path} → HTML")
        result = run(["pandoc", docx_path, "-t", "html", "--standalone"])
    html = result.stdout

    # ── Inject CSS + header ────────────────────────────────────────────────
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    html = html.replace("</head>", f"<style>\n{CSS}\n</style>\n</head>", 1)
    html = inject_header(html, ticker, args.date)

    # ── Inject data-driven charts (live price + payload signals) ───────────────
    if args.no_charts:
        html = _CHART_TOKEN_RE.sub("", html)
    else:
        context = load_context(ticker, args.context)
        html = inject_charts(html, ticker, context)

    # Caption tables (runs for both chart modes), then assign the single running
    # Figure N sequence over charts + tables in the order they appear.
    html = inject_table_captions(html)
    html = number_figures(html)

    with tempfile.NamedTemporaryFile(suffix=".html", mode="w",
                                     delete=False, encoding="utf-8") as tf:
        tf.write(html)
        tmp_html = tf.name

    # ── Step 3: headless browser → pdf ─────────────────────────────────────
    browser = find_browser()
    print(f"[3/3] {os.path.basename(browser)} → {pdf_path}")
    run([browser,
         "--headless", "--no-sandbox",
         "--disable-gpu",
         f"--print-to-pdf={pdf_path}",
         "--print-to-pdf-no-header",
         tmp_html])
    os.unlink(tmp_html)
    size = os.path.getsize(pdf_path)
    print(f"      ✓ {pdf_path}  ({size/1024:.0f} KB)")
    if args.skip_docx:
        print(f"\nDeliverables\n  PDF  : {pdf_path}")
    else:
        print(f"\nDeliverables\n  Word : {docx_path}\n  PDF  : {pdf_path}")


if __name__ == "__main__":
    main()
