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

# CJK chart fonts — used only when a chart renders for a CJK language. SVG <text>
# does not inherit the document lang, so the SC family must be named explicitly or
# Skia falls back to the Japanese (CJK JP) face. Latin-script memos keep the plain
# stacks above so no CJK face is embedded for en/es/fr. _CJK_LANGS mirrors the set
# in export_pdf.py. Kept in lockstep with the export CSS font stacks.
_CJK_LANGS = {"zh"}
FONT_SANS_CJK  = "Calibri, Arial, 'Noto Sans CJK SC', 'Noto Sans SC', sans-serif"
FONT_SERIF_CJK = "'EB Garamond', Georgia, 'Noto Serif CJK SC', 'Noto Serif SC', serif"


def _chart_fonts(lang: str) -> Tuple[str, str]:
    """Return the (sans, serif) font stacks for *lang* — CJK-extended only for CJK."""
    if lang in _CJK_LANGS:
        return FONT_SANS_CJK, FONT_SERIF_CJK
    return FONT_SANS, FONT_SERIF

# Figures (charts AND tables) are numbered in a single running sequence assigned
# in document order by the exporter, not here — a chart never knows how many
# tables precede it. Each caption therefore opens with this placeholder; the
# exporter's renumber pass swaps the Nth occurrence for "Figure N".
# NOTE: export_pdf.py matches this exact literal (FIG_PLACEHOLDER_RE) — keep in sync.
FIG_PLACEHOLDER = "[[#fig]]"


# ──────────────────────────────────────────────────────────────────────────────
# Localized chart copy — titles, axis/legend labels, "unavailable" notes, and
# figcaptions, keyed by language. The numeric geometry is language-agnostic; only
# the human-readable text lives here. English values are byte-identical to the
# original literals, so en output is unchanged. Builders take lang="en" and read
# L = LABELS.get(lang, LABELS["en"]); strings are .format()-ed with pre-formatted
# numbers (so locale decimal/thousands styling is applied before substitution).
# ──────────────────────────────────────────────────────────────────────────────

LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "price_unavail_title":  "{ticker} — Price ({period})",
        "price_unavail_reason": "Price history unavailable at render time.",
        "price_legend_close":   "Close ",
        "price_legend_ma":      "— — {ma}-day MA",
        "price_cap":            "<strong>{fig} — {ticker} share price, trailing {period}.</strong> Adjusted daily close (navy) with {ma}-day moving average (gold). 52-wk range {lo}–{hi}. Source: Yahoo Finance, as of {asof}.",
        "val_panel_fpe":        "Forward P/E (×)",
        "val_panel_evrev":      "EV / Revenue (×)",
        "val_unavail_title":    "Valuation comps",
        "val_unavail_target":   "Target financials unavailable.",
        "val_unavail_nomult":   "No comparable multiples in payload.",
        "val_peernote_some":    "{n} payload peer(s)",
        "val_peernote_none":    "no payload peers — see externally-sourced comp table above",
        "val_cap":              "<strong>{fig} — Relative valuation.</strong> {tkr} (gold) vs. peers (navy) on forward P/E and EV/Revenue. {peer_note}.",
        "mar_unavail_title":    "Margins & growth",
        "mar_unavail_target":   "Target financials unavailable.",
        "mar_unavail_nodata":   "No margin/growth data in payload.",
        "mar_ebitda":           "EBITDA margin",
        "mar_growth":           "YoY revenue growth",
        "mar_title":            "Profitability & growth ({ticker})",
        "mar_cap":              "<strong>{fig} — Operating leverage.</strong> TTM EBITDA margin and YoY revenue growth on TTM revenue of {rev}. Source: MCP payload.",
        "st_unavail_title":     "Search interest",
        "st_unavail_nosig":     "Google Trends signal unavailable.",
        "st_unavail_incomplete":"Incomplete Google Trends data.",
        "st_title":             "Google search interest (0–100, normalised)",
        "st_trough":            "trough {v}",
        "st_peak":              "peak {v}",
        "st_velocity":          "{arrow} {v}% velocity",
        "st_cap":               "<strong>{fig} — Attention signal.</strong> Latest search interest ({latest}/100) within its trailing trough–peak band ({trough}–{peak}). Source: Google Trends (MCP payload).",
        "sen_unavail_title":    "Sentiment by source",
        "sen_unavail_nosig":    "Sentiment signal unavailable.",
        "sen_unavail_nodata":   "No per-source sentiment in payload.",
        "sen_title":            "Sentiment by source (−1 to +1)",
        "sen_cap_agg":          "Aggregate {agg} across {total} posts. ",
        "sen_cap":              "<strong>{fig} — Public opinion.</strong> {agg}Per-source mean sentiment; bar opacity scales with source weight, n = message count. Source: multi-source sentiment (MCP payload).",
    },
    "zh": {
        "price_unavail_title":  "{ticker} — 价格 ({period})",
        "price_unavail_reason": "渲染时无法获取价格历史。",
        "price_legend_close":   "收盘价 ",
        "price_legend_ma":      "— — {ma}日均线",
        "price_cap":            "<strong>{fig} — {ticker} 股价，过去 {period}。</strong> 经调整每日收盘价（深蓝）及 {ma} 日移动平均线（金色）。52 周区间 {lo}–{hi}。来源：Yahoo Finance，截至 {asof}。",
        "val_panel_fpe":        "前瞻市盈率 (×)",
        "val_panel_evrev":      "EV / 营收 (×)",
        "val_unavail_title":    "估值对比",
        "val_unavail_target":   "目标公司财务数据不可用。",
        "val_unavail_nomult":   "数据中无可比估值倍数。",
        "val_peernote_some":    "{n} 个数据内可比公司",
        "val_peernote_none":    "数据内无可比公司——参见上方外部来源的对比表",
        "val_cap":              "<strong>{fig} — 相对估值。</strong> {tkr}（金色）对比可比公司（深蓝）的前瞻市盈率与 EV/营收。{peer_note}。",
        "mar_unavail_title":    "利润率与增长",
        "mar_unavail_target":   "目标公司财务数据不可用。",
        "mar_unavail_nodata":   "数据中无利润率/增长数据。",
        "mar_ebitda":           "EBITDA 利润率",
        "mar_growth":           "营收同比增速",
        "mar_title":            "盈利能力与增长 ({ticker})",
        "mar_cap":              "<strong>{fig} — 经营杠杆。</strong> 基于 TTM 营收 {rev} 的 TTM EBITDA 利润率与营收同比增速。来源：MCP 数据。",
        "st_unavail_title":     "搜索热度",
        "st_unavail_nosig":     "Google Trends 信号不可用。",
        "st_unavail_incomplete":"Google Trends 数据不完整。",
        "st_title":             "Google 搜索热度（0–100，标准化）",
        "st_trough":            "低谷 {v}",
        "st_peak":              "高峰 {v}",
        "st_velocity":          "{arrow} {v}% 变动速度",
        "st_cap":               "<strong>{fig} — 关注度信号。</strong> 最新搜索热度（{latest}/100）位于其过去低谷–高峰区间（{trough}–{peak}）之内。来源：Google Trends（MCP 数据）。",
        "sen_unavail_title":    "各来源情绪",
        "sen_unavail_nosig":    "情绪信号不可用。",
        "sen_unavail_nodata":   "数据中无分来源情绪。",
        "sen_title":            "各来源情绪（−1 至 +1）",
        "sen_cap_agg":          "总体 {agg}，覆盖 {total} 条帖子。",
        "sen_cap":              "<strong>{fig} — 公众舆论。</strong> {agg}各来源平均情绪；条形不透明度随来源权重变化，n = 消息数量。来源：多来源情绪（MCP 数据）。",
    },
    "es": {
        "price_unavail_title":  "{ticker} — Precio ({period})",
        "price_unavail_reason": "Historial de precios no disponible al renderizar.",
        "price_legend_close":   "Cierre ",
        "price_legend_ma":      "— — media móvil {ma} días",
        "price_cap":            "<strong>{fig} — Cotización de {ticker}, últimos {period}.</strong> Cierre diario ajustado (azul marino) con media móvil de {ma} días (dorado). Rango de 52 semanas {lo}–{hi}. Fuente: Yahoo Finance, a {asof}.",
        "val_panel_fpe":        "PER prospectivo (×)",
        "val_panel_evrev":      "EV / Ingresos (×)",
        "val_unavail_title":    "Comparables de valoración",
        "val_unavail_target":   "Datos financieros del objetivo no disponibles.",
        "val_unavail_nomult":   "Sin múltiplos comparables en los datos.",
        "val_peernote_some":    "{n} comparable(s) en los datos",
        "val_peernote_none":    "sin comparables en los datos — véase la tabla de fuentes externas arriba",
        "val_cap":              "<strong>{fig} — Valoración relativa.</strong> {tkr} (dorado) frente a comparables (azul marino) en PER prospectivo y EV/Ingresos. {peer_note}.",
        "mar_unavail_title":    "Márgenes y crecimiento",
        "mar_unavail_target":   "Datos financieros del objetivo no disponibles.",
        "mar_unavail_nodata":   "Sin datos de margen/crecimiento en los datos.",
        "mar_ebitda":           "Margen EBITDA",
        "mar_growth":           "Crecimiento interanual de ingresos",
        "mar_title":            "Rentabilidad y crecimiento ({ticker})",
        "mar_cap":              "<strong>{fig} — Apalancamiento operativo.</strong> Margen EBITDA TTM y crecimiento interanual de ingresos sobre ingresos TTM de {rev}. Fuente: datos MCP.",
        "st_unavail_title":     "Interés de búsqueda",
        "st_unavail_nosig":     "Señal de Google Trends no disponible.",
        "st_unavail_incomplete":"Datos de Google Trends incompletos.",
        "st_title":             "Interés de búsqueda en Google (0–100, normalizado)",
        "st_trough":            "mínimo {v}",
        "st_peak":              "máximo {v}",
        "st_velocity":          "{arrow} {v}% de velocidad",
        "st_cap":               "<strong>{fig} — Señal de atención.</strong> Interés de búsqueda más reciente ({latest}/100) dentro de su banda mínimo–máximo ({trough}–{peak}). Fuente: Google Trends (datos MCP).",
        "sen_unavail_title":    "Sentimiento por fuente",
        "sen_unavail_nosig":    "Señal de sentimiento no disponible.",
        "sen_unavail_nodata":   "Sin sentimiento por fuente en los datos.",
        "sen_title":            "Sentimiento por fuente (−1 a +1)",
        "sen_cap_agg":          "Agregado {agg} en {total} publicaciones. ",
        "sen_cap":              "<strong>{fig} — Opinión pública.</strong> {agg}Sentimiento medio por fuente; la opacidad de la barra escala con el peso de la fuente, n = número de mensajes. Fuente: sentimiento multifuente (datos MCP).",
    },
    "fr": {
        "price_unavail_title":  "{ticker} — Cours ({period})",
        "price_unavail_reason": "Historique des cours indisponible au moment du rendu.",
        "price_legend_close":   "Clôture ",
        "price_legend_ma":      "— — moyenne mobile {ma} jours",
        "price_cap":            "<strong>{fig} — Cours de {ticker}, {period} glissant(s).</strong> Clôture quotidienne ajustée (bleu marine) avec moyenne mobile {ma} jours (or). Fourchette sur 52 semaines {lo}–{hi}. Source : Yahoo Finance, au {asof}.",
        "val_panel_fpe":        "PER prospectif (×)",
        "val_panel_evrev":      "EV / Chiffre d'affaires (×)",
        "val_unavail_title":    "Comparables de valorisation",
        "val_unavail_target":   "Données financières de la cible indisponibles.",
        "val_unavail_nomult":   "Aucun multiple comparable dans les données.",
        "val_peernote_some":    "{n} comparable(s) dans les données",
        "val_peernote_none":    "aucun comparable dans les données — voir le tableau de sources externes ci-dessus",
        "val_cap":              "<strong>{fig} — Valorisation relative.</strong> {tkr} (or) face aux comparables (bleu marine) sur le PER prospectif et l'EV/CA. {peer_note}.",
        "mar_unavail_title":    "Marges et croissance",
        "mar_unavail_target":   "Données financières de la cible indisponibles.",
        "mar_unavail_nodata":   "Aucune donnée de marge/croissance dans les données.",
        "mar_ebitda":           "Marge d'EBITDA",
        "mar_growth":           "Croissance du CA en glissement annuel",
        "mar_title":            "Rentabilité et croissance ({ticker})",
        "mar_cap":              "<strong>{fig} — Levier opérationnel.</strong> Marge d'EBITDA TTM et croissance du chiffre d'affaires en glissement annuel sur un CA TTM de {rev}. Source : données MCP.",
        "st_unavail_title":     "Intérêt de recherche",
        "st_unavail_nosig":     "Signal Google Trends indisponible.",
        "st_unavail_incomplete":"Données Google Trends incomplètes.",
        "st_title":             "Intérêt de recherche Google (0–100, normalisé)",
        "st_trough":            "creux {v}",
        "st_peak":              "pic {v}",
        "st_velocity":          "{arrow} {v}% de vélocité",
        "st_cap":               "<strong>{fig} — Signal d'attention.</strong> Intérêt de recherche le plus récent ({latest}/100) dans sa fourchette creux–pic ({trough}–{peak}). Source : Google Trends (données MCP).",
        "sen_unavail_title":    "Sentiment par source",
        "sen_unavail_nosig":    "Signal de sentiment indisponible.",
        "sen_unavail_nodata":   "Aucun sentiment par source dans les données.",
        "sen_title":            "Sentiment par source (−1 à +1)",
        "sen_cap_agg":          "Agrégat {agg} sur {total} publications. ",
        "sen_cap":              "<strong>{fig} — Opinion publique.</strong> {agg}Sentiment moyen par source ; l'opacité des barres varie selon le poids de la source, n = nombre de messages. Source : sentiment multi-source (données MCP).",
    },
}


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
    lang: str = "en",
) -> str:
    """
    Render a 1-year stock curve: area-filled close line + moving average,
    gridlines, month/price axes, 52-week high–low band, and a last-price callout.

    *history* is a sequence of objects/dicts with ``date`` (YYYY-MM-DD) and
    ``close`` attributes/keys. When None, it is fetched live via FinancialService.
    """
    L = LABELS.get(lang, LABELS["en"])
    _fs, _ff = _chart_fonts(lang)
    points = _coerce_history(ticker, history, period)
    if len(points) < 5:
        return _unavailable(
            L["price_unavail_title"].format(ticker=ticker, period=period),
            L["price_unavail_reason"],
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
            f'font-size="9" fill="{SLATE}" font-family="{_fs}">${gv:,.0f}</text>'
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
            f'font-size="8.5" fill="{SLATE}" font-family="{_fs}">{lab}</text>'
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
        f'font-weight="700" fill="{NAVY}" font-family="{_fs}" '
        f'stroke="{WHITE}" stroke-width="2.6" paint-order="stroke" '
        f'stroke-linejoin="round">${last:,.2f}</text>'
    )

    legend = (
        f'<text x="{ml}" y="12" font-size="9" fill="{SLATE}" '
        f'font-family="{_fs}">{_esc(L["price_legend_close"])}'
        f'<tspan fill="{GOLD}" font-weight="700">'
        f'{_esc(L["price_legend_ma"].format(ma=ma_window))}</tspan></text>'
        f'<text x="{ml + pw}" y="12" text-anchor="end" font-size="9.5" '
        f'font-weight="700" fill="{chg_col}" font-family="{_fs}">'
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
    cap = L["price_cap"].format(
        fig=FIG_PLACEHOLDER, ticker=_esc(ticker), period=period, ma=ma_window,
        lo=f"${lo:,.2f}", hi=f"${hi:,.2f}", asof=asof,
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

def valuation_comps_svg(context: Dict, lang: str = "en") -> str:
    """Two stacked bar panels: Forward P/E and EV/Revenue, target highlighted."""
    L = LABELS.get(lang, LABELS["en"])
    _fs, _ff = _chart_fonts(lang)
    target = context.get("target") or {}
    peers  = [p for p in (context.get("peers") or []) if isinstance(p, dict) and "error" not in p]
    if not target or "error" in target:
        return _unavailable(L["val_unavail_title"], L["val_unavail_target"])

    companies = [target] + peers
    tkr = (target.get("ticker") or "TGT").upper()

    panels = [
        (L["val_panel_fpe"],   "forward_pe"),
        (L["val_panel_evrev"], "ev_revenue"),
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
            f'fill="{NAVY}" font-family="{_ff}">{_esc(title)}</text>'
        ]
        y_cursor += head_h - 6
        for t, v in rows:
            is_target = (t == tkr)
            bw = plot_w * v / vmax
            col = GOLD if is_target else NAVY_LT
            bars.append(
                f'<text x="{label_w - 8}" y="{y_cursor + 14:.0f}" text-anchor="end" '
                f'font-size="9.5" font-weight="{700 if is_target else 400}" '
                f'fill="{NAVY if is_target else SLATE}" font-family="{_fs}">{_esc(t)}</text>'
                f'<rect x="{label_w}" y="{y_cursor + 3:.0f}" width="{bw:.1f}" height="{row_h - 6}" '
                f'rx="2" fill="{col}" opacity="{1.0 if is_target else 0.85}"/>'
                f'<text x="{label_w + bw + 6:.1f}" y="{y_cursor + 14:.0f}" '
                f'font-size="9.5" font-weight="{700 if is_target else 400}" '
                f'fill="{INK}" font-family="{_fs}">{v:,.1f}×</text>'
            )
            y_cursor += row_h
        y_cursor += gap + 6
        panel_blocks.append("".join(bars))

    if not panel_blocks:
        return _unavailable(L["val_unavail_title"], L["val_unavail_nomult"])

    total_h = y_cursor + 4
    svg = (
        f'<svg viewBox="0 0 {PW} {total_h:.0f}" class="chart-svg" role="img" '
        f'aria-label="valuation comparables" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(panel_blocks)}</svg>'
    )

    peer_note = (
        L["val_peernote_some"].format(n=len(peers)) if peers
        else L["val_peernote_none"]
    )
    cap = L["val_cap"].format(fig=FIG_PLACEHOLDER, tkr=_esc(tkr), peer_note=peer_note)
    return _figure(svg, cap)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Margins & growth — the operating-leverage visual
# ──────────────────────────────────────────────────────────────────────────────

def margins_svg(context: Dict, lang: str = "en") -> str:
    """Horizontal bars: EBITDA margin and YoY revenue growth (percent scale)."""
    L = LABELS.get(lang, LABELS["en"])
    _fs, _ff = _chart_fonts(lang)
    t = context.get("target") or {}
    if not t or "error" in t:
        return _unavailable(L["mar_unavail_title"], L["mar_unavail_target"])

    rev   = _num(t.get("trailing_revenue_mm"))
    ebitda = _num(t.get("trailing_ebitda_mm"))
    ebitda_margin = (ebitda / rev * 100) if (rev and ebitda is not None and rev != 0) else None
    growth = _num(t.get("yoy_revenue_growth_pct"))

    metrics = []
    if ebitda_margin is not None:
        metrics.append((L["mar_ebitda"], ebitda_margin, NAVY))
    if growth is not None:
        metrics.append((L["mar_growth"], growth, GOLD))
    if not metrics:
        return _unavailable(L["mar_unavail_title"], L["mar_unavail_nodata"])

    W = 700
    label_w, row_h, gap, top = 150, 26, 16, 30
    plot_w = W - label_w - 70
    vmax = _nice_ceiling(max(abs(v) for _, v, _ in metrics) or 1.0)

    blocks, y = [], top
    # zero baseline reference
    blocks.append(
        f'<text x="0" y="16" font-size="11" font-weight="700" fill="{NAVY}" '
        f'font-family="{_ff}">'
        f'{_esc(L["mar_title"].format(ticker=str(t.get("ticker") or "")))}</text>'
    )
    for name, val, col in metrics:
        bw = plot_w * min(abs(val), vmax) / vmax
        blocks.append(
            f'<text x="{label_w - 8}" y="{y + 16:.0f}" text-anchor="end" font-size="9.5" '
            f'fill="{SLATE}" font-family="{_fs}">{_esc(name)}</text>'
            f'<rect x="{label_w}" y="{y + 4:.0f}" width="{bw:.1f}" height="{row_h - 8}" '
            f'rx="2" fill="{col}"/>'
            f'<text x="{label_w + bw + 6:.1f}" y="{y + 16:.0f}" font-size="10" '
            f'font-weight="700" fill="{INK}" font-family="{_fs}">{val:,.1f}%</text>'
        )
        y += row_h + gap
    H = y + 4

    rev_lab = _fmt_money_compact(rev)
    svg = (
        f'<svg viewBox="0 0 {W} {H:.0f}" class="chart-svg" role="img" '
        f'aria-label="margins and growth" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(blocks)}</svg>'
    )
    cap = L["mar_cap"].format(fig=FIG_PLACEHOLDER, rev=rev_lab)
    return _figure(svg, cap)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Search trends — bullet gauge
# ──────────────────────────────────────────────────────────────────────────────

def search_trends_svg(context: Dict, lang: str = "en") -> str:
    """Bullet gauge: latest Google-Trends interest within its trough–peak band."""
    L = LABELS.get(lang, LABELS["en"])
    _fs, _ff = _chart_fonts(lang)
    gt = (context.get("alt_signals") or {}).get("google_trends") or {}
    if "error" in gt:
        return _unavailable(L["st_unavail_title"], L["st_unavail_nosig"])
    latest = _num(gt.get("latest_interest"))
    peak   = _num(gt.get("peak_interest"))
    trough = _num(gt.get("trough_interest"))
    vel    = _num(gt.get("velocity_pct"))
    if latest is None or peak is None or trough is None:
        return _unavailable(L["st_unavail_title"], L["st_unavail_incomplete"])

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

    title_txt  = _esc(L["st_title"])
    trough_txt = _esc(L["st_trough"].format(v=f"{trough:.0f}"))
    peak_txt   = _esc(L["st_peak"].format(v=f"{peak:.0f}"))
    vel_txt    = _esc(L["st_velocity"].format(arrow=arrow, v=f"{abs(vel or 0):.1f}"))

    svg = f'''<svg viewBox="0 0 {W} {H}" class="chart-svg" role="img"
     aria-label="search interest gauge" xmlns="http://www.w3.org/2000/svg">
  <text x="{ml}" y="18" font-size="11" font-weight="700" fill="{NAVY}"
        font-family="{_ff}">{title_txt}</text>
  <rect x="{ml}" y="{track_y}" width="{tw}" height="{track_h}" rx="3" fill="{SILVER}"/>
  <rect x="{band_x0:.1f}" y="{track_y}" width="{(band_x1 - band_x0):.1f}" height="{track_h}"
        rx="3" fill="{NAVY}" opacity="0.16"/>
  <rect x="{ml}" y="{track_y + track_h / 2 - 1.5:.1f}" width="{(mark_x - ml):.1f}" height="3"
        fill="{NAVY_LT}"/>
  <rect x="{mark_x - 2:.1f}" y="{track_y - 5}" width="4" height="{track_h + 10}" rx="1.5" fill="{GOLD}"/>
  <text x="{mark_x:.1f}" y="{track_y - 9}" text-anchor="middle" font-size="11"
        font-weight="700" fill="{NAVY}" font-family="{_fs}">{latest:.0f}</text>
  <text x="{band_x0:.1f}" y="{track_y + track_h + 14:.0f}" text-anchor="middle" font-size="8.5"
        fill="{SLATE}" font-family="{_fs}">{trough_txt}</text>
  <text x="{band_x1:.1f}" y="{track_y + track_h + 14:.0f}" text-anchor="middle" font-size="8.5"
        fill="{SLATE}" font-family="{_fs}">{peak_txt}</text>
  <text x="{W - mr}" y="18" text-anchor="end" font-size="9.5" font-weight="700"
        fill="{vel_col}" font-family="{_fs}">{vel_txt}</text>
</svg>'''
    cap = L["st_cap"].format(
        fig=FIG_PLACEHOLDER, latest=f"{latest:.0f}",
        trough=f"{trough:.0f}", peak=f"{peak:.0f}",
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


def sentiment_sources_svg(context: Dict, lang: str = "en") -> str:
    """Diverging horizontal bars of per-source sentiment scores (−1…+1)."""
    L = LABELS.get(lang, LABELS["en"])
    _fs, _ff = _chart_fonts(lang)
    cs = (context.get("alt_signals") or {}).get("consumer_sentiment") or {}
    if "error" in cs and not cs.get("sources"):
        return _unavailable(L["sen_unavail_title"], L["sen_unavail_nosig"])
    sources = [
        s for s in (cs.get("sources") or [])
        if isinstance(s, dict) and s.get("available") and _num(s.get("sentiment_score")) is not None
    ]
    if not sources:
        return _unavailable(L["sen_unavail_title"], L["sen_unavail_nodata"])

    sources.sort(key=lambda s: _num(s.get("sentiment_score")) or 0.0, reverse=True)

    W = 700
    label_w, row_h, gap, top = 116, 22, 10, 34
    plot_w = W - label_w - 70
    cx = label_w + plot_w / 2          # zero axis (centre)
    half = plot_w / 2

    blocks = [
        f'<text x="0" y="16" font-size="11" font-weight="700" fill="{NAVY}" '
        f'font-family="{_ff}">{_esc(L["sen_title"])}</text>',
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
            f'fill="{SLATE}" font-family="{_fs}">{_esc(name)}</text>'
            f'<rect x="{bx:.1f}" y="{y + 3:.0f}" width="{bw:.1f}" height="{row_h - 6}" rx="2" '
            f'fill="{col}" opacity="{0.45 + 0.55 * min(1.0, weight):.2f}"/>'
            f'<text x="{val_x:.1f}" y="{y + 15:.0f}" text-anchor="{anchor}" font-size="9" '
            f'font-weight="700" fill="{val_col}" font-family="{_fs}">{score:+.2f}</text>'
            f'<text x="{W - 4}" y="{y + 15:.0f}" text-anchor="end" font-size="8" '
            f'fill="{SLATE}" font-family="{_fs}">n={msgs}</text>'
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
    agg_txt = (
        L["sen_cap_agg"].format(agg=f"{agg:+.2f}", total=total)
        if agg is not None else ""
    )
    cap = L["sen_cap"].format(fig=FIG_PLACEHOLDER, agg=agg_txt)
    return _figure(svg, cap)


# ──────────────────────────────────────────────────────────────────────────────
# Token registry — maps [[chart:NAME]] → builder
# ──────────────────────────────────────────────────────────────────────────────

def build_chart(name: str, ticker: str, context: Dict, lang: str = "en") -> str:
    """
    Dispatch a single chart token to its builder. Returns "" for an unknown
    token and never raises — export must proceed even if a chart fails. *lang*
    selects the localized chart copy (titles, labels, captions); defaults to en.
    """
    try:
        name = name.strip().lower()
        if name == "price_history":
            return price_history_svg(ticker, lang=lang)
        if name == "valuation_comps":
            return valuation_comps_svg(context, lang=lang)
        if name == "margins":
            return margins_svg(context, lang=lang)
        if name == "search_trends":
            return search_trends_svg(context, lang=lang)
        if name == "sentiment_sources":
            return sentiment_sources_svg(context, lang=lang)
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
