"""src.taxonomy — Material-signal event taxonomy for theoryy-argus.

Content salvaged from the (now-deleted) material-signal-keyword-playbook.md.
The playbook's web/Reddit keyword-scraping methodology, source-convergence
scoring, and source-routing logic were intentionally dropped per
PIVOT_ARCHITECTURE.md — this project sources data via curated API adapters
and a verified claim store, not open web scraping.

What is preserved here:
  - The event-category taxonomy derived from the playbook's "Full taxonomy by
    event category" table.
  - A materiality tier scheme (Tier S/A/B/C) anchored to the playbook's
    explicit "TIER S" list (lines 34-58 of the original playbook) and to
    the playbook's own materiality principle: "triggers an SEC Form 8-K, or
    moves the stock."
  - An authoritative 8-K item-code → label/category/tier mapping that
    supersedes and extends the old _8K_ITEM_LABELS dict in alt_data_service.py.
  - A MATERIAL_EVENT_PREDICATES vocabulary for the future LLM claim extractor.

IMPORTANT — what "tier" means here:
  `tier` encodes EVENT MATERIALITY ONLY — how significant is this event type
  to an investment thesis. It NEVER encodes source trust, source weighting,
  two-source convergence, or source-type credibility. Those belong in the
  source_trust table (PIVOT_ARCHITECTURE.md §2.2, §7.2) and are updated by
  the verification flywheel — not this module.

Tier definitions (event materiality):
  S — Highest-alpha, typically 8-K-triggering; the ~25 terms the playbook
      explicitly calls out as "TIER S — highest-alpha". Tend to lead the stock.
  A — Material events that trigger 8-K filings or move a thesis materially
      but not necessarily in the S cluster.
  B — Notable events that are material in context but less thesis-altering
      standalone.
  C — Background / monitoring signals.
"""

from __future__ import annotations

from typing import TypedDict


# ---------------------------------------------------------------------------
# Event category vocabulary
# Derived from the playbook's "Full taxonomy by event category" table.
# Use these string constants everywhere to avoid silent typos.
# ---------------------------------------------------------------------------

CAT_EARNINGS_GUIDANCE = "earnings_guidance"
CAT_MA_STRATEGIC = "ma_strategic"
CAT_EXEC_BOARD = "exec_board"
CAT_LAYOFFS_RESTRUCTURING = "layoffs_restructuring"
CAT_LEGAL_LITIGATION = "legal_litigation"
CAT_REGULATORY = "regulatory"
CAT_RECALL_SAFETY = "recall_safety"
CAT_ACCOUNTING_RED_FLAGS = "accounting_red_flags"
CAT_FINANCING_DILUTION = "financing_dilution"
CAT_SUPPLY_CUSTOMER = "supply_customer"
CAT_INSIDER = "insider"
CAT_CREDIT_BANKRUPTCY = "credit_bankruptcy"
CAT_POSITIVE_CATALYST = "positive_catalyst"

# The full set of valid category strings (for validation).
ALL_CATEGORIES: frozenset[str] = frozenset({
    CAT_EARNINGS_GUIDANCE,
    CAT_MA_STRATEGIC,
    CAT_EXEC_BOARD,
    CAT_LAYOFFS_RESTRUCTURING,
    CAT_LEGAL_LITIGATION,
    CAT_REGULATORY,
    CAT_RECALL_SAFETY,
    CAT_ACCOUNTING_RED_FLAGS,
    CAT_FINANCING_DILUTION,
    CAT_SUPPLY_CUSTOMER,
    CAT_INSIDER,
    CAT_CREDIT_BANKRUPTCY,
    CAT_POSITIVE_CATALYST,
})

# The full set of valid tier strings.
ALL_TIERS: frozenset[str] = frozenset({"S", "A", "B", "C"})


# ---------------------------------------------------------------------------
# 8-K item code taxonomy
# Each entry: label (exact human-readable string), category, tier.
#
# Authoritativeness contract:
#   - Every code in the OLD _8K_ITEM_LABELS dict (alt_data_service.py lines
#     94-112) is present here with its EXACT original label string —
#     no wording changes.
#   - New additions per the playbook (lines 118, 40-58):
#       1.05 — Material Cybersecurity Incident (playbook: "1.05 (cyber incident)")
#       4.02 — Non-Reliance on Previously Issued Financial Statements
#              (playbook's "TIER S" term: "non-reliance" / "restatement";
#               playbook line 118 lists 4.02 explicitly)
#
# Tier assignments for existing codes:
#   Tier S: 4.01 (auditor change — playbook TIER S "auditor resignation"),
#            4.02 (non-reliance / restatement — explicit TIER S term)
#   Tier A: exec departure (5.02), delisting (3.01), impairment (2.06),
#            restructuring charges (2.05), acquisition (2.01),
#            cybersecurity (1.05 — explicit in playbook EDGAR list),
#            bankruptcy (1.03)
#   Tier B: material agreement entry/term (1.01, 1.02), results (2.02),
#            financial obligation (2.03), equity sales (3.02),
#            control change (5.01), charter amendments (5.03)
#   Tier C: Reg FD (7.01), Other Events (8.01), exhibits (9.01)
# ---------------------------------------------------------------------------

class _8KEntry(TypedDict):
    label: str
    category: str
    tier: str


# Authoritative 8-K item code → label/category/tier mapping.
# This is the SINGLE SOURCE OF TRUTH for 8-K item labeling.
# alt_data_service._8K_ITEM_LABELS is DERIVED from this dict at module import.
ITEM_8K_TAXONOMY: dict[str, _8KEntry] = {
    # ── Existing codes (exact original labels preserved) ──────────────────
    "1.01": {
        "label": "Entry into Material Agreement",
        "category": CAT_MA_STRATEGIC,
        "tier": "B",
    },
    "1.02": {
        "label": "Termination of Material Agreement",
        "category": CAT_MA_STRATEGIC,
        "tier": "B",
    },
    "1.03": {
        "label": "Bankruptcy/Receivership",
        "category": CAT_CREDIT_BANKRUPTCY,
        "tier": "A",
    },
    "2.01": {
        "label": "Completion of Acquisition/Disposition",
        "category": CAT_MA_STRATEGIC,
        "tier": "A",
    },
    "2.02": {
        "label": "Results of Operations",
        "category": CAT_EARNINGS_GUIDANCE,
        "tier": "B",
    },
    "2.03": {
        "label": "Creation of Direct Financial Obligation",
        "category": CAT_FINANCING_DILUTION,
        "tier": "B",
    },
    "2.05": {
        "label": "Exit or Disposal Cost Obligations",
        "category": CAT_LAYOFFS_RESTRUCTURING,
        "tier": "A",
    },
    "2.06": {
        "label": "Material Impairment",
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "A",
    },
    "3.01": {
        "label": "Notice of Delisting",
        "category": CAT_CREDIT_BANKRUPTCY,
        "tier": "A",
    },
    "3.02": {
        "label": "Unregistered Sales of Equity Securities",
        "category": CAT_FINANCING_DILUTION,
        "tier": "B",
    },
    "4.01": {
        "label": "Changes in Certifying Accountant",
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "S",
    },
    "5.01": {
        "label": "Changes in Control of Registrant",
        "category": CAT_MA_STRATEGIC,
        "tier": "B",
    },
    "5.02": {
        "label": "Directors/Officers Departure/Appointment",
        "category": CAT_EXEC_BOARD,
        "tier": "A",
    },
    "5.03": {
        "label": "Amendments to Articles/Certificate",
        "category": CAT_MA_STRATEGIC,
        "tier": "B",
    },
    "7.01": {
        "label": "Regulation FD Disclosure",
        "category": CAT_EARNINGS_GUIDANCE,
        "tier": "C",
    },
    "8.01": {
        "label": "Other Events",
        "category": CAT_EARNINGS_GUIDANCE,
        "tier": "C",
    },
    "9.01": {
        "label": "Financial Statements and Exhibits",
        "category": CAT_EARNINGS_GUIDANCE,
        "tier": "C",
    },
    # ── NEW additions (gaps flagged by the playbook) ──────────────────────
    # Playbook TIER S term: "non-reliance" (line 40), explicit EDGAR item
    # in line 118: "4.02 (restatement / non-reliance)"
    "4.02": {
        "label": "Non-Reliance on Previously Issued Financial Statements",
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "S",
    },
    # Playbook EDGAR list line 118: "1.05 (cyber incident)"
    "1.05": {
        "label": "Material Cybersecurity Incident",
        "category": CAT_REGULATORY,
        "tier": "A",
    },
}


# Convenience dict: code → label only. Derived from ITEM_8K_TAXONOMY so
# alt_data_service._label_items() has a single source of truth.
# All 17 original label strings are IDENTICAL to the old _8K_ITEM_LABELS dict.
ITEM_8K_LABELS: dict[str, str] = {
    code: entry["label"] for code, entry in ITEM_8K_TAXONOMY.items()
}


# ---------------------------------------------------------------------------
# Material-event predicate vocabulary
# For use by the LLM claim extractor (src/ingest/extract_llm.py).
#
# Predicates are snake_case, consistent with _PREDICATE_MAP in
# extract_deterministic.py. Each entry maps to {category, tier}.
#
# These are the event-type predicates an LLM extractor prompt should
# recognise and classify claims into. NOT live-plumbed yet — see TODO in
# extract_llm.py.
#
# Coverage: all 13 playbook event categories (downside + upside).
# Upside / positive catalysts are included per the playbook's principle:
# "Materiality is direction-agnostic: a positive surprise moves a thesis
# as much as a negative one."
# ---------------------------------------------------------------------------

class _PredicateEntry(TypedDict):
    category: str
    tier: str


MATERIAL_EVENT_PREDICATES: dict[str, _PredicateEntry] = {
    # ── Earnings / guidance ──────────────────────────────────────────────
    "event.guidance_lowered": {
        "category": CAT_EARNINGS_GUIDANCE,
        "tier": "S",
    },
    "event.guidance_withdrawn": {
        "category": CAT_EARNINGS_GUIDANCE,
        "tier": "S",
    },
    "event.profit_warning": {
        "category": CAT_EARNINGS_GUIDANCE,
        "tier": "S",
    },
    "event.preliminary_results": {
        "category": CAT_EARNINGS_GUIDANCE,
        "tier": "A",
    },
    "event.earnings_miss": {
        "category": CAT_EARNINGS_GUIDANCE,
        "tier": "A",
    },
    # ── M&A / strategic alternatives ────────────────────────────────────
    "event.strategic_alternatives_announced": {
        "category": CAT_MA_STRATEGIC,
        "tier": "S",
    },
    "event.going_private": {
        "category": CAT_MA_STRATEGIC,
        "tier": "S",
    },
    "event.acquisition_announced": {
        "category": CAT_MA_STRATEGIC,
        "tier": "A",
    },
    "event.divestiture_announced": {
        "category": CAT_MA_STRATEGIC,
        "tier": "A",
    },
    "event.spinoff_announced": {
        "category": CAT_MA_STRATEGIC,
        "tier": "A",
    },
    # ── Exec / board ─────────────────────────────────────────────────────
    "event.cfo_resignation": {
        "category": CAT_EXEC_BOARD,
        "tier": "S",
    },
    "event.ceo_resignation": {
        "category": CAT_EXEC_BOARD,
        "tier": "S",
    },
    "event.interim_ceo_appointed": {
        "category": CAT_EXEC_BOARD,
        "tier": "A",
    },
    "event.exec_departure_abrupt": {
        "category": CAT_EXEC_BOARD,
        "tier": "A",
    },
    "event.board_member_departure": {
        "category": CAT_EXEC_BOARD,
        "tier": "B",
    },
    # ── Layoffs / restructuring ──────────────────────────────────────────
    "event.mass_layoff_warn_act": {
        "category": CAT_LAYOFFS_RESTRUCTURING,
        "tier": "A",
    },
    "event.workforce_reduction": {
        "category": CAT_LAYOFFS_RESTRUCTURING,
        "tier": "A",
    },
    "event.restructuring_charge": {
        "category": CAT_LAYOFFS_RESTRUCTURING,
        "tier": "A",
    },
    "event.facility_closure": {
        "category": CAT_LAYOFFS_RESTRUCTURING,
        "tier": "B",
    },
    "event.hiring_freeze": {
        "category": CAT_LAYOFFS_RESTRUCTURING,
        "tier": "B",
    },
    # ── Legal / litigation ───────────────────────────────────────────────
    "event.securities_class_action": {
        "category": CAT_LEGAL_LITIGATION,
        "tier": "A",
    },
    "event.shareholder_derivative_suit": {
        "category": CAT_LEGAL_LITIGATION,
        "tier": "A",
    },
    "event.adverse_judgment": {
        "category": CAT_LEGAL_LITIGATION,
        "tier": "A",
    },
    "event.indictment": {
        "category": CAT_LEGAL_LITIGATION,
        "tier": "A",
    },
    "event.antitrust_complaint": {
        "category": CAT_LEGAL_LITIGATION,
        "tier": "B",
    },
    # ── Regulatory ──────────────────────────────────────────────────────
    "event.wells_notice": {
        "category": CAT_REGULATORY,
        "tier": "S",
    },
    "event.sec_investigation": {
        "category": CAT_REGULATORY,
        "tier": "S",
    },
    "event.grand_jury_subpoena": {
        "category": CAT_REGULATORY,
        "tier": "S",
    },
    "event.fda_warning_letter": {
        "category": CAT_REGULATORY,
        "tier": "A",
    },
    "event.consent_decree": {
        "category": CAT_REGULATORY,
        "tier": "A",
    },
    "event.cybersecurity_incident_material": {
        "category": CAT_REGULATORY,
        "tier": "A",
    },
    # ── Recall / safety ──────────────────────────────────────────────────
    "event.class_i_recall": {
        "category": CAT_RECALL_SAFETY,
        "tier": "A",
    },
    "event.voluntary_recall": {
        "category": CAT_RECALL_SAFETY,
        "tier": "A",
    },
    "event.safety_defect_disclosed": {
        "category": CAT_RECALL_SAFETY,
        "tier": "B",
    },
    # ── Accounting red flags ─────────────────────────────────────────────
    "event.material_weakness": {
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "S",
    },
    "event.going_concern": {
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "S",
    },
    "event.restatement": {
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "S",
    },
    "event.non_reliance": {
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "S",
    },
    "event.late_filing_nt": {
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "S",
    },
    "event.auditor_resignation": {
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "S",
    },
    "event.audit_committee_investigation": {
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "A",
    },
    "event.related_party_transaction_flagged": {
        "category": CAT_ACCOUNTING_RED_FLAGS,
        "tier": "B",
    },
    # ── Financing / dilution ─────────────────────────────────────────────
    "event.covenant_breach": {
        "category": CAT_FINANCING_DILUTION,
        "tier": "S",
    },
    "event.event_of_default": {
        "category": CAT_FINANCING_DILUTION,
        "tier": "S",
    },
    "event.secondary_offering": {
        "category": CAT_FINANCING_DILUTION,
        "tier": "A",
    },
    "event.pipe_financing": {
        "category": CAT_FINANCING_DILUTION,
        "tier": "A",
    },
    "event.atm_offering": {
        "category": CAT_FINANCING_DILUTION,
        "tier": "A",
    },
    "event.convertible_notes_issued": {
        "category": CAT_FINANCING_DILUTION,
        "tier": "B",
    },
    # ── Supply / customer ────────────────────────────────────────────────
    "event.major_customer_lost": {
        "category": CAT_SUPPLY_CUSTOMER,
        "tier": "A",
    },
    "event.contract_terminated": {
        "category": CAT_SUPPLY_CUSTOMER,
        "tier": "A",
    },
    "event.supply_chain_disruption": {
        "category": CAT_SUPPLY_CUSTOMER,
        "tier": "A",
    },
    "event.production_halt": {
        "category": CAT_SUPPLY_CUSTOMER,
        "tier": "A",
    },
    # ── Insider ──────────────────────────────────────────────────────────
    "event.insider_cluster_selling": {
        "category": CAT_INSIDER,
        "tier": "A",
    },
    "event.schedule_13d_filed": {
        "category": CAT_INSIDER,
        "tier": "A",
    },
    "event.ten_b5_1_plan_terminated": {
        "category": CAT_INSIDER,
        "tier": "B",
    },
    # ── Credit / bankruptcy ──────────────────────────────────────────────
    "event.chapter_11_filed": {
        "category": CAT_CREDIT_BANKRUPTCY,
        "tier": "S",
    },
    "event.credit_rating_downgrade": {
        "category": CAT_CREDIT_BANKRUPTCY,
        "tier": "S",
    },
    "event.missed_interest_payment": {
        "category": CAT_CREDIT_BANKRUPTCY,
        "tier": "S",
    },
    "event.dip_financing": {
        "category": CAT_CREDIT_BANKRUPTCY,
        "tier": "S",
    },
    "event.forbearance_agreement": {
        "category": CAT_CREDIT_BANKRUPTCY,
        "tier": "A",
    },
    "event.restructuring_support_agreement": {
        "category": CAT_CREDIT_BANKRUPTCY,
        "tier": "A",
    },
    # ── Positive / growth catalysts (upside) ────────────────────────────
    # Playbook: "Materiality is direction-agnostic: a positive surprise …
    # moves a thesis as much as a negative one."
    "event.guidance_raised": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "S",
    },
    "event.beat_and_raise": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "A",
    },
    "event.record_bookings": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "A",
    },
    "event.major_contract_awarded": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "A",
    },
    "event.fda_approval": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "A",
    },
    "event.regulatory_approval": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "A",
    },
    "event.buyback_authorization": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "A",
    },
    "event.dividend_initiation": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "B",
    },
    "event.dividend_increase": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "B",
    },
    "event.index_inclusion": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "B",
    },
    "event.activist_investor_constructive": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "B",
    },
    "event.design_win": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "B",
    },
    "event.major_customer_added": {
        "category": CAT_POSITIVE_CATALYST,
        "tier": "B",
    },
}
