"""
test_chart_service.py — Unit tests for the SVG chart engine and PDF token injection.

No network is touched: price history is injected directly, and all other charts
read from synthetic context dicts. These tests pin two invariants:
  1. Every builder returns well-formed XML and never raises on bad/empty data.
  2. The export script's [[chart:name]] token regex matches the forms pandoc emits.
"""
import os
import re
import sys
import unittest

from defusedxml.minidom import parseString as _parse_xml  # XXE-safe parser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import chart_service as cs


def _svg_of(fragment: str) -> str:
    m = re.search(r"<svg.*?</svg>", fragment, re.DOTALL)
    assert m, f"no <svg> in fragment: {fragment[:120]}"
    return m.group(0)


def _well_formed(fragment: str) -> None:
    _parse_xml(_svg_of(fragment))


# Minimal but realistic payload mirroring context_<TICKER>.json shape.
_CONTEXT = {
    "target": {
        "ticker": "TST", "name": "Test Co",
        "trailing_revenue_mm": 1000.0, "trailing_ebitda_mm": 250.0,
        "forward_pe": 18.0, "yoy_revenue_growth_pct": 22.0,
        "ev_revenue": 5.0, "ev_ebitda": 12.0,
    },
    "peers": [
        {"ticker": "PRA", "forward_pe": 25.0, "ev_revenue": 7.0},
        {"ticker": "PRB", "forward_pe": 30.0, "ev_revenue": 9.0},
    ],
    "alt_signals": {
        "google_trends": {"latest_interest": 40, "peak_interest": 100,
                          "trough_interest": 20, "velocity_pct": -1.5},
        "consumer_sentiment": {
            "sentiment_score": 0.3, "post_count": 80,
            "sources": [
                {"source": "stocktwits", "available": True, "message_count": 30,
                 "sentiment_score": 0.7, "weight": 1.0},
                {"source": "hackernews", "available": True, "message_count": 25,
                 "sentiment_score": -1.0, "weight": 0.6},
            ],
        },
    },
}

_PRICE = [{"date": f"2025-{(i // 21) + 1:02d}-{(i % 21) + 1:02d}",
           "close": 100 + i * 0.5} for i in range(120)]


class TestChartBuilders(unittest.TestCase):

    def test_price_history_well_formed(self):
        frag = cs.price_history_svg("TST", history=_PRICE)
        self.assertIn("<figure", frag)
        _well_formed(frag)
        self.assertNotIn("chart--empty", frag)

    def test_all_payload_charts_well_formed(self):
        for fn in (cs.valuation_comps_svg, cs.margins_svg,
                   cs.search_trends_svg, cs.sentiment_sources_svg):
            frag = fn(_CONTEXT)
            self.assertIn("<figure", frag, fn.__name__)
            _well_formed(frag)
            self.assertNotIn("chart--empty", frag, fn.__name__)

    def test_valuation_includes_target_and_peers(self):
        frag = cs.valuation_comps_svg(_CONTEXT)
        for tk in ("TST", "PRA", "PRB"):
            self.assertIn(tk, frag)

    def test_sentiment_negative_value_is_white_inside(self):
        # The -1.00 label must render white (inside the bar), not ink — the fix
        # that stopped it colliding with the source label.
        frag = cs.sentiment_sources_svg(_CONTEXT)
        self.assertRegex(frag, rf'fill="{cs.WHITE}"[^>]*>-1\.00<')


class TestGracefulDegradation(unittest.TestCase):

    def test_empty_price_history_is_placeholder_not_crash(self):
        frag = cs.price_history_svg("TST", history=[])
        self.assertIn("chart--empty", frag)

    def test_missing_signals_degrade(self):
        for fn in (cs.valuation_comps_svg, cs.margins_svg,
                   cs.search_trends_svg, cs.sentiment_sources_svg):
            frag = fn({})           # empty context
            self.assertIn("chart--empty", frag, fn.__name__)

    def test_error_nodes_degrade(self):
        ctx = {"target": {"ticker": "X", "error": "boom"},
               "peers": [{"ticker": "Y", "error": "boom"}],
               "alt_signals": {"google_trends": {"error": "boom"},
                               "consumer_sentiment": {"error": "boom"}}}
        self.assertIn("chart--empty", cs.valuation_comps_svg(ctx))
        self.assertIn("chart--empty", cs.search_trends_svg(ctx))
        self.assertIn("chart--empty", cs.sentiment_sources_svg(ctx))

    def test_build_chart_unknown_token_returns_empty(self):
        self.assertEqual(cs.build_chart("does_not_exist", "TST", _CONTEXT), "")

    def test_build_chart_never_raises(self):
        # Pass a context shaped to trip attribute access; must not raise.
        # price_history is excluded here (it would hit the live network); its
        # graceful path is covered by test_empty_price_history_is_placeholder.
        for name in (t for t in cs.CHART_TOKENS if t != "price_history"):
            cs.build_chart(name, "TST", {"target": None, "alt_signals": None})


class TestTokenRegex(unittest.TestCase):

    def setUp(self):
        import export_pdf
        self.re = export_pdf._CHART_TOKEN_RE

    def test_matches_bare_token(self):
        self.assertEqual(self.re.findall("x [[chart:price_history]] y"),
                         ["price_history"])

    def test_matches_pandoc_paragraph_wrapped_token(self):
        # pandoc wraps a lone token line in <p>…</p>
        html = "<p>[[chart:valuation_comps]]</p>"
        m = self.re.search(html)
        self.assertEqual(m.group(1), "valuation_comps")
        # full <p> wrapper is consumed so no stray empty paragraph remains
        self.assertEqual(self.re.sub("X", html), "X")

    def test_case_insensitive(self):
        self.assertEqual(self.re.findall("[[Chart:Margins]]"), ["Margins"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
