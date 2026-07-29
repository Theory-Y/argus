# Action plan — Memo feedback round v2 (meeting-note validation + implementation)

_Date: 2026-06-11. Status: DONE — all work-breakdown items landed; suite 344 green;
live PCOR payload rebuilt on schema 1.9 with all three new nodes populated._

Source: user meeting note with feedback on generated memos. Each item below was
validated against the codebase, the pivot architecture (`PIVOT_ARCHITECTURE.md`),
and data feasibility (yfinance probed live: insider transactions ✓, 8+ quarters of
earnings surprises ✓, 4–5 FYs of annual statements ✓).

## Validation verdicts

| # | Feedback item | Verdict | Disposition |
|---|---|---|---|
| 1 | Conviction score + "good buy at this price?" under recommendation | **Accept** (reframed: conviction 1–10 + entry view vs 52w range/valuation history; no price targets per pivot §14 P4 discipline) | Skill/prompt §7 |
| 2 | Name market-competitor risk | **Accept** | Skill/prompt §5 rule |
| 3 | Margin-compression risk | **Accept** | Skill/prompt §5 rule |
| 4 | Unscheduled insider selling as confidence signal | **Accept** (yfinance `insider_transactions`; 10b5-1 scheduled-plan detection not in free data — interpretation rule guards this) | New data node + §5 rule |
| 5 | Guidance-cut pattern over last 8 earnings | **Accept as proxy** (EPS estimate-vs-reported surprise pattern, 8 quarters; true guidance language lives in 8-K 2.02 which the writer is told to cross-check) | New data node + §5 rule |
| 6 | Links to public company filings | **Accept** (payload already carries `filing_url` + 8-K URLs; writer must render them as links) | Writing rule |
| 7 | Key risks must not regurgitate 10-K / eliminate 10-K-redundant info | **Accept** (Item 1A demoted to background reference; key risks must state the delta beyond the filing) | Writing rule |
| 8 | Sources: MarketWatch/WSJ/NYT | **Reject scraping** (paywall/ToS); they already arrive attributed via `massive_news` — writer cites publisher+date. Roadmap notes licensed-feed upgrade path (pivot §11). | Roadmap note |
| 9 | Pitch decks / company-website investor info not in 10-K | **Defer to Phase 2** licensed/first-party onboarding with consent refs + MNPI gate (pivot §11, INV-5) | Roadmap |
| 10 | Catalyst test: best/worst case, 3 bull + 3 bear, probability/magnitude/timing/priced-in/public reaction | **Accept** — new memo section `## 6. Catalyst Map — Bull & Bear Cases`; lighter precursor of the Phase 4 scenario engine (kept consistent: no price targets, drivers + stated uncertainty) | Skill/prompt new section |
| 11 | AI council (pessimist / first-principles / expansionist / executor + VC & banking lenses, blind cross-review) | **Defer full council to Phase 4** (pivot §6.3 mandates single-agent first). Distilled now into single-agent rigor: red-team-your-own-call rule + monitoring/next-steps (executor) in §7. Full persona spec recorded in ROADMAP Phase 4. | Rigor rule now; spec in roadmap |
| 12 | §2: multi-year revenue with labeled years | **Accept** — annual revenue history node + `[[chart:revenue_history]]` (FY-labeled) + multi-year revenue-mix writing rule | Data + chart + rule |
| 13 | §4: niche communities + what each is focused on | **Accept** (data already per-source; writing rule to name each community and its focus themes). Google/Bing "as main" rejected — Google attention already covered by Trends; Bing adds no differentiated signal. | Writing rule |
| 14 | EV/Revenue + forward P/E diagram, last 3–4 years | **Accept with substitution** — historical EV/Revenue + trailing P/E (approx, year-end) via `[[chart:valuation_history]]`; historical *forward* P/E impossible without a paid consensus-estimates archive (noted in roadmap) | Data + chart |
| 15 | Polar vs Stripe → use Stripe | **Skip** — already implemented (user-confirmed) | — |

## Work breakdown

1. **Data layer** (`src/financial_service.py`): fetcher + transformer + façade for
   `insider_activity`, `earnings_track` (last 8 surprises + streak math),
   `fundamentals_history` (annual revenue/EBITDA/NI + approx year-end EV/Revenue
   and trailing P/E via 5y price history + balance sheet).
2. **Aggregator** (`src/context_aggregator.py`): `alt_signals.insider_activity`,
   `alt_signals.earnings_track`, top-level `fundamentals_history`; schema 1.8 → 1.9.
3. **Charts** (`src/chart_service.py`): `revenue_history` (FY-labeled bars + YoY),
   `valuation_history` (EV/Revenue ×, trailing P/E × by FY); LABELS en/zh/es/fr;
   token registry + `CHART_TOKENS`.
4. **Memo spec** (`.claude/skills/theory-y-memo/SKILL.md` + `core/memo/prompt.py`,
   kept in sync): 7 sections (new §6 Catalyst Map), §5 risk upgrade rules, §7
   conviction score + red-team + monitoring, §2/§4 rules, new chart anchors,
   filing-link rule, sourcing rules.
5. **Localization glossaries** (`localization/glossary.{zh,es,fr}.md`): new heading
   + new terms (catalyst, priced in, conviction score, margin compression, insider
   selling, guidance cut, bull/bear case).
6. **Tests**: `test_all.py` (schema 1.9, new transformer/service tests),
   `test_chart_service.py` (new builders, degradation), `test_memo_writer.py`
   (7 sections).
7. **Docs**: ROADMAP (validated items + change log + Phase 2/4 deferred entries),
   this plan, `graphify update .`.

## Notes

- All new fetchers follow the repo's never-raise/error-node contract so a data gap
  can't break payload assembly or PDF export.
- Legacy-path edits are content-spec only; the same spec text carries into the
  pivot's `analyst_writer` (prompt.py *is* the future analyst_writer prompt), so
  this work survives the cutover and does not reintroduce the stateless design.
