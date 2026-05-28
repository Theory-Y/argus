"""
export_pdf.py  —  Convert a Theory Y memo markdown to PDF via the .dotx pipeline.

Pipeline:
  1. pandoc  .md  + reference.dotx  →  .docx        (branded Word output)
  2. pandoc  .docx                  →  .html         (structured content extract)
  3. Inject  institutional CSS      into  .html
  4. chromium --headless            →  .pdf

Usage:
  .venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_MU.md
  .venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_MU.md --skip-docx
"""

import argparse, os, re, subprocess, sys, tempfile

REFERENCE_DOTX = "output/theme/reference.dotx"
CHROMIUM       = "chromium"

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


def main():
    parser = argparse.ArgumentParser(description="Export memo to PDF via .dotx pipeline")
    parser.add_argument("md_path", help="Path to the markdown memo")
    parser.add_argument("--skip-docx", action="store_true",
                        help="Skip .docx generation; use existing .docx")
    parser.add_argument("--date", default="2026-05-28")
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
             "--reference-doc", REFERENCE_DOTX,
             "-o", docx_path])
        print(f"      ✓ {docx_path}")

    # ── Step 2: docx → html ────────────────────────────────────────────────
    print(f"[2/3] pandoc  {docx_path} → HTML")
    result = run(["pandoc", docx_path, "-t", "html", "--standalone"])
    html = result.stdout

    # ── Inject CSS + header ────────────────────────────────────────────────
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    html = html.replace("</head>", f"<style>\n{CSS}\n</style>\n</head>", 1)
    html = inject_header(html, ticker, args.date)

    with tempfile.NamedTemporaryFile(suffix=".html", mode="w",
                                     delete=False, encoding="utf-8") as tf:
        tf.write(html)
        tmp_html = tf.name

    # ── Step 3: chromium → pdf ─────────────────────────────────────────────
    print(f"[3/3] chromium → {pdf_path}")
    run([CHROMIUM,
         "--headless", "--no-sandbox",
         "--disable-gpu",
         f"--print-to-pdf={pdf_path}",
         "--print-to-pdf-no-header",
         tmp_html])
    os.unlink(tmp_html)
    size = os.path.getsize(pdf_path)
    print(f"      ✓ {pdf_path}  ({size/1024:.0f} KB)")
    print(f"\nDeliverables\n  Word : {docx_path}\n  PDF  : {pdf_path}")


if __name__ == "__main__":
    main()
