#!/usr/bin/env python3
"""
export_pdf.py — Convert a Theory Y memo markdown to PDF via md-to-pdf.

Usage:
  .venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_MU.md
  .venv/bin/python3 scripts/export_pdf.py output/memos/TheoryY_Memo_MU.md --output output/TheoryY_Memo_MU_custom.pdf

Dependencies:
  npm install md-to-pdf
  (Chromium/Puppeteer is bundled with md-to-pdf)
"""

import argparse
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Export memo to PDF via md-to-pdf")
    parser.add_argument("md_path", help="Path to the markdown memo")
    parser.add_argument(
        "--output",
        default=None,
        help="Output PDF path (default: <input>.pdf)",
    )
    args = parser.parse_args()

    md_path = args.md_path
    if not os.path.isfile(md_path):
        print(f"ERROR: markdown file not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    # Infer output path
    if args.output:
        pdf_path = args.output
    else:
        base = os.path.splitext(md_path)[0]
        pdf_path = base + ".pdf"

    # Ensure output directory exists
    os.makedirs(os.path.dirname(pdf_path) or ".", exist_ok=True)

    # Run md-to-pdf
    print(f"Converting {md_path} → {pdf_path}")
    try:
        result = subprocess.run(
            ["./node_modules/.bin/md-to-pdf", md_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # md-to-pdf writes <input>.pdf in the same directory; move if custom path requested
        default_pdf = os.path.splitext(md_path)[0] + ".pdf"
        if args.output and default_pdf != pdf_path and os.path.isfile(default_pdf):
            os.replace(default_pdf, pdf_path)
        if result.returncode != 0:
            print(f"ERROR: md-to-pdf failed with exit code {result.returncode}", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            sys.exit(1)
    except FileNotFoundError:
        print(
            "ERROR: md-to-pdf not found. Install with: npm install md-to-pdf",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("ERROR: md-to-pdf timed out after 60 seconds", file=sys.stderr)
        sys.exit(1)

    if os.path.isfile(pdf_path):
        size = os.path.getsize(pdf_path)
        print(f"✓ {pdf_path}  ({size / 1024:.0f} KB)")
    else:
        print(f"ERROR: PDF was not created at {pdf_path}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
