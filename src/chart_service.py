"""
chart_service.py — Institutional SVG Chart Engine
==================================================
Generates publication-grade, dependency-free **inline SVG** charts for the
Theory Y PDF memo. The PDF is rendered by headless chromium from HTML, so SVG is
the natural medium: vector-crisp at any zoom, fully deterministic, and requiring
no image/plotting libraries (no matplotlib, no kaleido, no fonts to embed).

Data provenance (so every visual is accurate and auditable):
  • price_history     → live yfinance daily adjusted closes (as-of render time)
  • valuation_comps   → context payload `target` + `peers`
  • margins           → context payload `target`
  • search_trends     → context payload `alt_signals.google_trends`
  • sentiment_sources → context payload `alt_signals.consumer_sentiment.sources`

Every public builder returns a complete ``<figure class="chart">…</figure>`` HTML
fragment (SVG + figcaption with source/as-of). Builders **never raise**: on a
missing or malformed signal they return an empty string or a small "unavailable"
note, so a data gap can never break the PDF export.

The palette and type are matched to the institutional CSS in scripts/export_pdf.py.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Palette — kept in lockstep with the export CSS :root variables
# ──────────────────────────────────────────────────────────────────────────────

NAVY    = "#0D1F3C"
NAVY_LT = "#1E3A5F"
GOLD    = "#B8922A"
INK     = "#1A1A1A"
SLATE   = "#4A5568"
SILVER  = "#F4F6F9"
RULE    = "#CBD5E0"
WHITE   = "#FFFFFF"
GREEN   = "#2F7A4F"   # positive sentiment / above-zero
RED     = "#B23A3A"   # negative sentiment / below-zero

FONT_SANS  = "Calibri, Arial, sans-serif"
FONT_SERIF = "'EB Garamond', Georgia, serif"

# Figures (charts AND tables) are numbered in a single running sequence assigned
# in document order by the exporter, not here — a chart never knows how many
# tables precede it. Each caption therefore opens with this placeholder; the
# exporter's renumber pass swaps the Nth occurrence for "Figure N".
# NOTE: export_pdf.py matches this exact literal (FIG_PLACEHOLDER_RE) — keep in sync.
FIG_PLACEHOLDER = "[[#fig]]"


# ──────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ──────────────────────────────────────────────────────────────────────────────

def _esc(text: object) -> str:
    """Minimal XML escaping for text placed inside SVG/HTML."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _num(value: object) -> Optional[float]:
    """Coerce to float, returning None for None / 'N/M' / non-numeric."""
    if value is None:
        return None
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _figure(svg: str, caption: str) -> str:
    """Wrap an SVG body and caption into the standard memo figure block."""
    return (
        '<figure class="chart">\n'
        f"{svg}\n"
        f'<figcaption>{caption}</figcaption>\n'
        "</figure>"
    )


def _unavailable(title: str, reason: str) -> str:
    """A subtle placeholder shown when a chart's data is missing."""
    return (
        '<figure class="chart chart--empty">\n'
        f'<div class="chart-empty-box"><strong>{_esc(title)}</strong>'
        f"<span>{_esc(reason)}</span></div>\n"
        "</figure>"
    )


def _nice_ceiling(value: float) -> float:
    """Round *value* up to a clean axis bound (1/2/2.5/5 × 10^n)."""
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    base = 10 ** exp
    for mult in (1, 2, 2.5, 5, 10):
        if value <= mult * base:
            return mult * base
    return 10 * base


def _fmt_money_compact(mm: Optional[float]) -> str:
    """Format a USD-millions figure as $X.XB / $XXXM."""
    v = _num(mm)
    if v is None:
        return "—"
    if abs(v) >= 1_000:
        return f"${v / 1_000:,.1f}B"
    return f"${v:,.0f}M"


# ──────────────────────────────────────────────────────────────────────────────
# 1. Price history — the professional stock curve
# ──────────────────────────────────────────────────────────────────────────────

def price_history_svg(
    ticker: str,
    history: Optional[Sequence] = None,
    period: str = "1y",
    ma_window: int = 50,
) -> str:
    """
    Render a 1-year stock curve: area-filled close line + moving average,
    gridlines, month/price axes, 52-week high–low band, and a last-price callout.

    *history* is a sequence of objects/dicts with ``date`` (YYYY-MM-DD) and
    ``close`` attributes/keys. When None, it is fetched live via FinancialService.
    """
    points = _coerce_history(ticker, history, period)
    if len(points) < 5:
        return _unavailable(
            f"{ticker} — Price ({period})",
            "Price history unavailable at render time.",
        )

    dates  = [d for d, _ in points]
    closes = [c for _, c in points]

    # ── geometry ──────────────────────────────────────────────────────────────
    W, H = 720, 300
    ml, mr, mt, mb = 52, 16, 18, 34          # plot margins
    pw, ph = W - ml - mr, H - mt - mb

    lo, hi = min(closes), max(closes)
    pad = (hi - lo) * 0.08 or (hi * 0.05 or 1.0)
    y_lo, y_hi = lo - pad, hi + pad
    span = (y_hi - y_lo) or 1.0
    n = len(closes)

    def x(i: int) -> float:
        return ml + (pw * i / (n - 1))

    def y(v: float) -> float:
        return mt + ph * (1 - (v - y_lo) / span)

    # ── y gridlines + labels (5 ticks) ──────────────────────────────────────────
    ticks = 4
    grid, ylabels = [], []
    for k in range(ticks + 1):
        gv = y_lo + span * k / ticks
        gy = y(gv)
        grid.append(
            f'<line x1="{ml}" y1="{gy:.1f}" x2="{ml + pw}" y2="{gy:.1f}" '
            f'stroke="{RULE}" stroke-width="0.6" {"" if k else "opacity=\"0\""}/>'
        )
        ylabels.append(
            f'<text x="{ml - 8:.1f}" y="{gy + 3:.1f}" text-anchor="end" '
            f'font-size="9" fill="{SLATE}" font-family="{FONT_SANS}">${gv:,.0f}</text>'
        )

    # ── x labels: first trading day of each month in the window ──────────────────
    # A trailing window often opens mid/late-month, so the first month tick can
    # land only a few pixels from the next one. Enforce a minimum horizontal gap
    # so adjacent month labels (e.g. "May"/"Jun") never collide.
    MIN_LABEL_GAP = 34.0
    xlabels = []
    seen_months = set()
    last_label_x = -1e9
    for i, dstr in enumerate(dates):
        mkey = dstr[:7]
        if mkey in seen_months:
            continue
        seen_months.add(mkey)
        xi = x(i)
        if xi - last_label_x < MIN_LABEL_GAP:
            continue
        last_label_x = xi
        try:
            lab = datetime.strptime(dstr, "%Y-%m-%d").strftime("%b")
        except ValueError:
            lab = dstr[5:7]
        xlabels.append(
            f'<text x="{xi:.1f}" y="{H - 12:.1f}" text-anchor="middle" '
            f'font-size="8.5" fill="{SLATE}" font-family="{FONT_SANS}">{lab}</text>'
        )

    # ── 52-wk high/low band ──────────────────────────────────────────────────────
    band = (
        f'<rect x="{ml}" y="{y(hi):.1f}" width="{pw}" '
        f'height="{(y(lo) - y(hi)):.1f}" fill="{NAVY}" opacity="0.04"/>'
    )

    # ── area + line path ──────────────────────────────────────────────────────────
    pts = " ".join(f"{x(i):.2f},{y(c):.2f}" for i, c in enumerate(closes))
    area = (
        f'M{ml:.2f},{y(closes[0]):.2f} '
        + " ".join(f"L{x(i):.2f},{y(c):.2f}" for i, c in enumerate(closes))
        + f" L{x(n - 1):.2f},{mt + ph:.2f} L{ml:.2f},{mt + ph:.2f} Z"
    )

    # ── moving average ─────────────────────────────────────────────────────────────
    ma_line = ""
    if n >= ma_window:
        ma_pts = []
        for i in range(n):
            if i + 1 >= ma_window:
                window = closes[i + 1 - ma_window: i + 1]
                ma_pts.append(f"{x(i):.2f},{y(sum(window) / ma_window):.2f}")
        if len(ma_pts) > 1:
            ma_line = (
                f'<polyline points="{" ".join(ma_pts)}" fill="none" '
                f'stroke="{GOLD}" stroke-width="1.6" stroke-dasharray="5 3" '
                f'opacity="0.9"/>'
            )

    # ── last-price callout ───────────────────────────────────────────────────────
    last = closes[-1]
    first = closes[0]
    chg_pct = (last / first - 1) * 100 if first else 0.0
    chg_col = GREEN if chg_pct >= 0 else RED
    lx, ly = x(n - 1), y(last)
    label_y = max(mt + 9, ly - 9)          # keep the label inside the plot top
    callout = (
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="3.2" fill="{NAVY}" '
        f'stroke="{WHITE}" stroke-width="1.2"/>'
        # white halo (paint-order=stroke) keeps the value legible where it would
        # otherwise sit on top of the price line near a peak.
        f'<text x="{lx - 4:.1f}" y="{label_y:.1f}" text-anchor="end" font-size="10.5" '
        f'font-weight="700" fill="{NAVY}" font-family="{FONT_SANS}" '
        f'stroke="{WHITE}" stroke-width="2.6" paint-order="stroke" '
        f'stroke-linejoin="round">${last:,.2f}</text>'
    )

    legend = (
        f'<text x="{ml}" y="12" font-size="9" fill="{SLATE}" '
        f'font-family="{FONT_SANS}">Close '
        f'<tspan fill="{GOLD}" font-weight="700">— — {ma_window}-day MA</tspan></text>'
        f'<text x="{ml + pw}" y="12" text-anchor="end" font-size="9.5" '
        f'font-weight="700" fill="{chg_col}" font-family="{FONT_SANS}">'
        f'{"+" if chg_pct >= 0 else ""}{chg_pct:.1f}% / {period}</text>'
    )

    svg = f'''<svg viewBox="0 0 {W} {H}" class="chart-svg" role="img"
     aria-label="{_esc(ticker)} price history" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{NAVY_LT}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="{NAVY_LT}" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  {"".join(grid)}
  {band}
  <path d="{area}" fill="url(#priceFill)"/>
  <polyline points="{pts}" fill="none" stroke="{NAVY}" stroke-width="1.8"
            stroke-linejoin="round" stroke-linecap="round"/>
  {ma_line}
  {"".join(ylabels)}
  {"".join(xlabels)}
  {callout}
  {legend}
</svg>'''

    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cap = (
        f"<strong>{FIG_PLACEHOLDER} — {_esc(ticker)} share price, trailing {period}.</strong> "
        f"Adjusted daily close (navy) with {ma_window}-day moving average (gold). "
        f"52-wk range ${lo:,.2f}–${hi:,.2f}. Source: Yahoo Finance, as of {asof}."
    )
    return _figure(svg, cap)


def _coerce_history(
    ticker: str, history: Optional[Sequence], period: str
) -> List[Tuple[str, float]]:
    """Normalise supplied history, or fetch live, into [(date, close), …]."""
    if history is None:
        try:
            from financial_service import FinancialService  # local import: optional dep
            history = FinancialService().get_price_history(ticker, period=period)
        except Exception as exc:                              # pragma: no cover
            logger.warning("price-history fetch failed for %s: %s", ticker, exc)
            return []
    out: List[Tuple[str, float]] = []
    for p in history:
        if isinstance(p, dict):
            d, c = p.get("date"), _num(p.get("close"))
        else:
            d, c = getattr(p, "date", None), _num(getattr(p, "close", None))
        if d and c is not None:
            out.append((str(d), c))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 2. Valuation comps — target vs peers
# ──────────────────────────────────────────────────────────────────────────────

def valuation_comps_svg(context: Dict) -> str:
    """Two stacked bar panels: Forward P/E and EV/Revenue, target highlighted."""
    target = context.get("target") or {}
    peers  = [p for p in (context.get("peers") or []) if isinstance(p, dict) and "error" not in p]
    if not target or "error" in target:
        return _unavailable("Valuation comps", "Target financials unavailable.")

    companies = [target] + peers
    tkr = (target.get("ticker") or "TGT").upper()

    panels = [
        ("Forward P/E (×)",  "forward_pe"),
        ("EV / Revenue (×)", "ev_revenue"),
    ]

    PW = 700
    row_h, gap, label_w, head_h = 22, 10, 96, 26
    panel_blocks, total_h, y_cursor = [], 8, 8

    for title, key in panels:
        rows = [(str(c.get("ticker") or "?").upper(), _num(c.get(key))) for c in companies]
        rows = [(t, v) for t, v in rows if v is not None]
        if not rows:
            continue
        vmax = _nice_ceiling(max(v for _, v in rows))
        plot_w = PW - label_w - 56

        bars = [
            f'<text x="0" y="{y_cursor:.0f}" font-size="11" font-weight="700" '
            f'fill="{NAVY}" font-family="{FONT_SERIF}">{_esc(title)}</text>'
        ]
        y_cursor += head_h - 6
        for t, v in rows:
            is_target = (t == tkr)
            bw = plot_w * v / vmax
            col = GOLD if is_target else NAVY_LT
            bars.append(
                f'<text x="{label_w - 8}" y="{y_cursor + 14:.0f}" text-anchor="end" '
                f'font-size="9.5" font-weight="{700 if is_target else 400}" '
                f'fill="{NAVY if is_target else SLATE}" font-family="{FONT_SANS}">{_esc(t)}</text>'
                f'<rect x="{label_w}" y="{y_cursor + 3:.0f}" width="{bw:.1f}" height="{row_h - 6}" '
                f'rx="2" fill="{col}" opacity="{1.0 if is_target else 0.85}"/>'
                f'<text x="{label_w + bw + 6:.1f}" y="{y_cursor + 14:.0f}" '
                f'font-size="9.5" font-weight="{700 if is_target else 400}" '
                f'fill="{INK}" font-family="{FONT_SANS}">{v:,.1f}×</text>'
            )
            y_cursor += row_h
        y_cursor += gap + 6
        panel_blocks.append("".join(bars))

    if not panel_blocks:
        return _unavailable("Valuation comps", "No comparable multiples in payload.")

    total_h = y_cursor + 4
    svg = (
        f'<svg viewBox="0 0 {PW} {total_h:.0f}" class="chart-svg" role="img" '
        f'aria-label="valuation comparables" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(panel_blocks)}</svg>'
    )

    peer_note = (
        f"{len(peers)} payload peer(s)" if peers
        else "no payload peers — see externally-sourced comp table above"
    )
    cap = (
        f"<strong>{FIG_PLACEHOLDER} — Relative valuation.</strong> {_esc(tkr)} (gold) vs. "
        f"peers (navy) on forward P/E and EV/Revenue. {peer_note}."
    )
    return _figure(svg, cap)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Margins & growth — the operating-leverage visual
# ──────────────────────────────────────────────────────────────────────────────

def margins_svg(context: Dict) -> str:
    """Horizontal bars: EBITDA margin and YoY revenue growth (percent scale)."""
    t = context.get("target") or {}
    if not t or "error" in t:
        return _unavailable("Margins & growth", "Target financials unavailable.")

    rev   = _num(t.get("trailing_revenue_mm"))
    ebitda = _num(t.get("trailing_ebitda_mm"))
    ebitda_margin = (ebitda / rev * 100) if (rev and ebitda is not None and rev != 0) else None
    growth = _num(t.get("yoy_revenue_growth_pct"))

    metrics = []
    if ebitda_margin is not None:
        metrics.append(("EBITDA margin", ebitda_margin, NAVY))
    if growth is not None:
        metrics.append(("YoY revenue growth", growth, GOLD))
    if not metrics:
        return _unavailable("Margins & growth", "No margin/growth data in payload.")

    W = 700
    label_w, row_h, gap, top = 150, 26, 16, 30
    plot_w = W - label_w - 70
    vmax = _nice_ceiling(max(abs(v) for _, v, _ in metrics) or 1.0)

    blocks, y = [], top
    # zero baseline reference
    blocks.append(
        f'<text x="0" y="16" font-size="11" font-weight="700" fill="{NAVY}" '
        f'font-family="{FONT_SERIF}">Profitability &amp; growth ({_esc(str(t.get("ticker") or ""))})</text>'
    )
    for name, val, col in metrics:
        bw = plot_w * min(abs(val), vmax) / vmax
        blocks.append(
            f'<text x="{label_w - 8}" y="{y + 16:.0f}" text-anchor="end" font-size="9.5" '
            f'fill="{SLATE}" font-family="{FONT_SANS}">{_esc(name)}</text>'
            f'<rect x="{label_w}" y="{y + 4:.0f}" width="{bw:.1f}" height="{row_h - 8}" '
            f'rx="2" fill="{col}"/>'
            f'<text x="{label_w + bw + 6:.1f}" y="{y + 16:.0f}" font-size="10" '
            f'font-weight="700" fill="{INK}" font-family="{FONT_SANS}">{val:,.1f}%</text>'
        )
        y += row_h + gap
    H = y + 4

    rev_lab = _fmt_money_compact(rev)
    svg = (
        f'<svg viewBox="0 0 {W} {H:.0f}" class="chart-svg" role="img" '
        f'aria-label="margins and growth" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(blocks)}</svg>'
    )
    cap = (
        f"<strong>{FIG_PLACEHOLDER} — Operating leverage.</strong> TTM EBITDA margin and "
        f"YoY revenue growth on TTM revenue of {rev_lab}. Source: MCP payload."
    )
    return _figure(svg, cap)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Search trends — bullet gauge
# ──────────────────────────────────────────────────────────────────────────────

def search_trends_svg(context: Dict) -> str:
    """Bullet gauge: latest Google-Trends interest within its trough–peak band."""
    gt = (context.get("alt_signals") or {}).get("google_trends") or {}
    if "error" in gt:
        return _unavailable("Search interest", "Google Trends signal unavailable.")
    latest = _num(gt.get("latest_interest"))
    peak   = _num(gt.get("peak_interest"))
    trough = _num(gt.get("trough_interest"))
    vel    = _num(gt.get("velocity_pct"))
    if latest is None or peak is None or trough is None:
        return _unavailable("Search interest", "Incomplete Google Trends data.")

    W, H = 700, 96
    ml, mr = 16, 16
    track_y, track_h = 44, 18
    tw = W - ml - mr

    def px(v: float) -> float:
        return ml + tw * max(0.0, min(100.0, v)) / 100.0

    band_x0, band_x1 = px(trough), px(peak)
    mark_x = px(latest)
    vel_col = GREEN if (vel or 0) >= 0 else RED
    arrow = "▲" if (vel or 0) >= 0 else "▼"

    svg = f'''<svg viewBox="0 0 {W} {H}" class="chart-svg" role="img"
     aria-label="search interest gauge" xmlns="http://www.w3.org/2000/svg">
  <text x="{ml}" y="18" font-size="11" font-weight="700" fill="{NAVY}"
        font-family="{FONT_SERIF}">Google search interest (0–100, normalised)</text>
  <rect x="{ml}" y="{track_y}" width="{tw}" height="{track_h}" rx="3" fill="{SILVER}"/>
  <rect x="{band_x0:.1f}" y="{track_y}" width="{(band_x1 - band_x0):.1f}" height="{track_h}"
        rx="3" fill="{NAVY}" opacity="0.16"/>
  <rect x="{ml}" y="{track_y + track_h / 2 - 1.5:.1f}" width="{(mark_x - ml):.1f}" height="3"
        fill="{NAVY_LT}"/>
  <rect x="{mark_x - 2:.1f}" y="{track_y - 5}" width="4" height="{track_h + 10}" rx="1.5" fill="{GOLD}"/>
  <text x="{mark_x:.1f}" y="{track_y - 9}" text-anchor="middle" font-size="11"
        font-weight="700" fill="{NAVY}" font-family="{FONT_SANS}">{latest:.0f}</text>
  <text x="{band_x0:.1f}" y="{track_y + track_h + 14:.0f}" text-anchor="middle" font-size="8.5"
        fill="{SLATE}" font-family="{FONT_SANS}">trough {trough:.0f}</text>
  <text x="{band_x1:.1f}" y="{track_y + track_h + 14:.0f}" text-anchor="middle" font-size="8.5"
        fill="{SLATE}" font-family="{FONT_SANS}">peak {peak:.0f}</text>
  <text x="{W - mr}" y="18" text-anchor="end" font-size="9.5" font-weight="700"
        fill="{vel_col}" font-family="{FONT_SANS}">{arrow} {abs(vel or 0):.1f}% velocity</text>
</svg>'''
    cap = (
        f"<strong>{FIG_PLACEHOLDER} — Attention signal.</strong> Latest search interest "
        f"({latest:.0f}/100) within its trailing trough–peak band ({trough:.0f}–{peak:.0f}). "
        f"Source: Google Trends (MCP payload)."
    )
    return _figure(svg, cap)


# ──────────────────────────────────────────────────────────────────────────────
# 5. Sentiment by source — diverging bars
# ──────────────────────────────────────────────────────────────────────────────

_SOURCE_LABELS = {
    "stocktwits":    "StockTwits",
    "yahoo_finance": "Yahoo Finance",
    "google_news":   "Google News",
    "bing_news":     "Bing News",
    "hackernews":    "HackerNews",
    "reddit":        "Reddit",
}


def sentiment_sources_svg(context: Dict) -> str:
    """Diverging horizontal bars of per-source sentiment scores (−1…+1)."""
    cs = (context.get("alt_signals") or {}).get("consumer_sentiment") or {}
    if "error" in cs and not cs.get("sources"):
        return _unavailable("Sentiment by source", "Sentiment signal unavailable.")
    sources = [
        s for s in (cs.get("sources") or [])
        if isinstance(s, dict) and s.get("available") and _num(s.get("sentiment_score")) is not None
    ]
    if not sources:
        return _unavailable("Sentiment by source", "No per-source sentiment in payload.")

    sources.sort(key=lambda s: _num(s.get("sentiment_score")) or 0.0, reverse=True)

    W = 700
    label_w, row_h, gap, top = 116, 22, 10, 34
    plot_w = W - label_w - 70
    cx = label_w + plot_w / 2          # zero axis (centre)
    half = plot_w / 2

    blocks = [
        f'<text x="0" y="16" font-size="11" font-weight="700" fill="{NAVY}" '
        f'font-family="{FONT_SERIF}">Sentiment by source (−1 to +1)</text>',
        f'<line x1="{cx:.1f}" y1="{top - 4}" x2="{cx:.1f}" '
        f'y2="{top + len(sources) * (row_h + gap):.0f}" stroke="{RULE}" stroke-width="1"/>',
    ]
    y = top
    for s in sources:
        score = max(-1.0, min(1.0, _num(s.get("sentiment_score"))))
        name = _SOURCE_LABELS.get(s.get("source"), str(s.get("source") or "?"))
        msgs = int(_num(s.get("message_count")) or 0)
        weight = _num(s.get("weight")) or 1.0
        col = GREEN if score > 0.02 else RED if score < -0.02 else SLATE
        bw = half * abs(score)
        bx = cx if score >= 0 else cx - bw
        # Positive bars label outside-right (ink); negative bars label inside the
        # bar near the zero axis (white) so the value never collides with the
        # left-hand source label when the bar spans the full negative half.
        if score >= 0:
            val_x, anchor, val_col = cx + bw + 6, "start", INK
        else:
            val_x, anchor, val_col = cx - 6, "end", WHITE
        blocks.append(
            f'<text x="{label_w - 8}" y="{y + 15:.0f}" text-anchor="end" font-size="9.5" '
            f'fill="{SLATE}" font-family="{FONT_SANS}">{_esc(name)}</text>'
            f'<rect x="{bx:.1f}" y="{y + 3:.0f}" width="{bw:.1f}" height="{row_h - 6}" rx="2" '
            f'fill="{col}" opacity="{0.45 + 0.55 * min(1.0, weight):.2f}"/>'
            f'<text x="{val_x:.1f}" y="{y + 15:.0f}" text-anchor="{anchor}" font-size="9" '
            f'font-weight="700" fill="{val_col}" font-family="{FONT_SANS}">{score:+.2f}</text>'
            f'<text x="{W - 4}" y="{y + 15:.0f}" text-anchor="end" font-size="8" '
            f'fill="{SLATE}" font-family="{FONT_SANS}">n={msgs}</text>'
        )
        y += row_h + gap
    H = y + 6

    agg = _num(cs.get("sentiment_score"))
    total = int(_num(cs.get("post_count")) or 0)
    svg = (
        f'<svg viewBox="0 0 {W} {H:.0f}" class="chart-svg" role="img" '
        f'aria-label="sentiment by source" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(blocks)}</svg>'
    )
    agg_txt = f"Aggregate {agg:+.2f} across {total} posts. " if agg is not None else ""
    cap = (
        f"<strong>{FIG_PLACEHOLDER} — Public opinion.</strong> {agg_txt}Per-source mean "
        f"sentiment; bar opacity scales with source weight, n = message count. "
        f"Source: multi-source sentiment (MCP payload)."
    )
    return _figure(svg, cap)


# ──────────────────────────────────────────────────────────────────────────────
# Token registry — maps [[chart:NAME]] → builder
# ──────────────────────────────────────────────────────────────────────────────

def build_chart(name: str, ticker: str, context: Dict) -> str:
    """
    Dispatch a single chart token to its builder. Returns "" for an unknown
    token and never raises — export must proceed even if a chart fails.
    """
    try:
        name = name.strip().lower()
        if name == "price_history":
            return price_history_svg(ticker)
        if name == "valuation_comps":
            return valuation_comps_svg(context)
        if name == "margins":
            return margins_svg(context)
        if name == "search_trends":
            return search_trends_svg(context)
        if name == "sentiment_sources":
            return sentiment_sources_svg(context)
        logger.warning("Unknown chart token: %r", name)
        return ""
    except Exception as exc:                                  # pragma: no cover
        logger.error("Chart build failed for %r: %s", name, exc)
        return _unavailable(name, "Chart could not be rendered.")


CHART_TOKENS = (
    "price_history",
    "valuation_comps",
    "margins",
    "search_trends",
    "sentiment_sources",
)
