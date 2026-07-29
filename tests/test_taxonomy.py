"""tests/test_taxonomy.py — Unit tests for src.taxonomy.

Verifies:
  1. Every 8-K code in ITEM_8K_TAXONOMY has a non-empty label, a valid
     category, and a valid tier.
  2. The two previously-missing codes (4.02, 1.05) are present with sensible
     category and tier assignments.
  3. Every code in the OLD _8K_ITEM_LABELS dict (the 17 codes that existed in
     alt_data_service.py before the taxonomy was introduced) is still present
     in ITEM_8K_LABELS with the EXACT SAME label string. This is the guard
     against byte-for-byte regression in _label_items() output.
  4. MATERIAL_EVENT_PREDICATES entries are well-formed: snake_case keys,
     valid category + tier values, and the vocabulary includes both downside
     and at least one upside (positive-catalyst) predicate.
  5. ITEM_8K_LABELS (the derived code→label dict) is a superset of the
     original 17 codes and includes the two new additions.
  6. alt_data_service._8K_ITEM_LABELS is derived from taxonomy (same object
     identity or equal dict), so _label_items() has a single source of truth.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

# Ensure repo root is on sys.path so src.* imports work.
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from src.taxonomy import (
    ALL_CATEGORIES,
    ALL_TIERS,
    ITEM_8K_LABELS,
    ITEM_8K_TAXONOMY,
    MATERIAL_EVENT_PREDICATES,
    CAT_ACCOUNTING_RED_FLAGS,
    CAT_POSITIVE_CATALYST,
    CAT_REGULATORY,
)


# ---------------------------------------------------------------------------
# Frozen reference: the EXACT 17 code→label pairs that existed in the OLD
# _8K_ITEM_LABELS dict in alt_data_service.py (lines 94-112 before refactor).
# These strings MUST remain byte-for-byte identical in the taxonomy so that
# _label_items() output is unchanged for existing callers.
# ---------------------------------------------------------------------------
_ORIGINAL_17: dict[str, str] = {
    "1.01": "Entry into Material Agreement",
    "1.02": "Termination of Material Agreement",
    "1.03": "Bankruptcy/Receivership",
    "2.01": "Completion of Acquisition/Disposition",
    "2.02": "Results of Operations",
    "2.03": "Creation of Direct Financial Obligation",
    "2.05": "Exit or Disposal Cost Obligations",
    "2.06": "Material Impairment",
    "3.01": "Notice of Delisting",
    "3.02": "Unregistered Sales of Equity Securities",
    "4.01": "Changes in Certifying Accountant",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Directors/Officers Departure/Appointment",
    "5.03": "Amendments to Articles/Certificate",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

# The two codes added by this work (from the playbook).
_NEW_CODES = {"4.02", "1.05"}


# ============================================================================
# Tests: ITEM_8K_TAXONOMY structure
# ============================================================================

class TestItem8KTaxonomy:
    """Structural correctness of ITEM_8K_TAXONOMY."""

    def test_all_entries_have_nonempty_label(self) -> None:
        for code, entry in ITEM_8K_TAXONOMY.items():
            assert entry["label"], f"8-K code {code!r} has an empty label"
            assert entry["label"].strip(), f"8-K code {code!r} has a whitespace-only label"

    def test_all_entries_have_valid_category(self) -> None:
        for code, entry in ITEM_8K_TAXONOMY.items():
            assert entry["category"] in ALL_CATEGORIES, (
                f"8-K code {code!r} has unknown category {entry['category']!r}. "
                f"Valid categories: {sorted(ALL_CATEGORIES)}"
            )

    def test_all_entries_have_valid_tier(self) -> None:
        for code, entry in ITEM_8K_TAXONOMY.items():
            assert entry["tier"] in ALL_TIERS, (
                f"8-K code {code!r} has unknown tier {entry['tier']!r}. "
                f"Valid tiers: {sorted(ALL_TIERS)}"
            )

    def test_original_17_codes_present_exact_labels(self) -> None:
        """Every original code is in the taxonomy with the EXACT original label."""
        for code, original_label in _ORIGINAL_17.items():
            assert code in ITEM_8K_TAXONOMY, (
                f"Original 8-K code {code!r} is missing from ITEM_8K_TAXONOMY"
            )
            actual_label = ITEM_8K_TAXONOMY[code]["label"]
            assert actual_label == original_label, (
                f"Label mismatch for 8-K code {code!r}:\n"
                f"  expected: {original_label!r}\n"
                f"  actual:   {actual_label!r}\n"
                "Label strings must be byte-for-byte identical to preserve "
                "_label_items() output for existing callers."
            )

    def test_new_codes_present(self) -> None:
        """The two codes added from the playbook are in the taxonomy."""
        for code in _NEW_CODES:
            assert code in ITEM_8K_TAXONOMY, (
                f"New 8-K code {code!r} (from playbook) is missing from ITEM_8K_TAXONOMY"
            )

    def test_code_4_02_has_accounting_category_and_s_tier(self) -> None:
        """4.02 (non-reliance / restatement) is a Tier-S accounting red flag."""
        entry = ITEM_8K_TAXONOMY["4.02"]
        assert entry["category"] == CAT_ACCOUNTING_RED_FLAGS, (
            f"4.02 should be category {CAT_ACCOUNTING_RED_FLAGS!r}, got {entry['category']!r}"
        )
        assert entry["tier"] == "S", (
            f"4.02 (non-reliance) is Tier S per the playbook; got {entry['tier']!r}"
        )

    def test_code_1_05_has_regulatory_category_and_a_tier(self) -> None:
        """1.05 (cybersecurity incident) is a Tier-A regulatory event."""
        entry = ITEM_8K_TAXONOMY["1.05"]
        assert entry["category"] == CAT_REGULATORY, (
            f"1.05 should be category {CAT_REGULATORY!r}, got {entry['category']!r}"
        )
        assert entry["tier"] in {"A", "S"}, (
            f"1.05 (cybersecurity) should be at least Tier A; got {entry['tier']!r}"
        )

    def test_taxonomy_is_superset_of_original(self) -> None:
        """ITEM_8K_TAXONOMY must contain all 17 original codes PLUS the new additions."""
        original_codes = set(_ORIGINAL_17.keys())
        taxonomy_codes = set(ITEM_8K_TAXONOMY.keys())
        assert original_codes.issubset(taxonomy_codes), (
            f"Taxonomy is missing original codes: {original_codes - taxonomy_codes}"
        )
        assert _NEW_CODES.issubset(taxonomy_codes), (
            f"Taxonomy is missing new codes: {_NEW_CODES - taxonomy_codes}"
        )


# ============================================================================
# Tests: ITEM_8K_LABELS (derived dict)
# ============================================================================

class TestItem8KLabels:
    """ITEM_8K_LABELS is the derived code→label mapping used by _label_items()."""

    def test_derived_labels_match_taxonomy(self) -> None:
        """ITEM_8K_LABELS must equal {code: entry['label'] for ...} from taxonomy."""
        expected = {code: entry["label"] for code, entry in ITEM_8K_TAXONOMY.items()}
        assert ITEM_8K_LABELS == expected

    def test_original_17_labels_byte_for_byte(self) -> None:
        """Every original label is byte-for-byte identical in the derived dict."""
        for code, original_label in _ORIGINAL_17.items():
            assert ITEM_8K_LABELS.get(code) == original_label, (
                f"ITEM_8K_LABELS[{code!r}] = {ITEM_8K_LABELS.get(code)!r}, "
                f"expected {original_label!r}"
            )

    def test_new_codes_in_labels(self) -> None:
        for code in _NEW_CODES:
            assert code in ITEM_8K_LABELS, f"New code {code!r} missing from ITEM_8K_LABELS"
            assert ITEM_8K_LABELS[code], f"New code {code!r} has empty label"


# ============================================================================
# Tests: alt_data_service integration
# ============================================================================

class TestAltDataServiceIntegration:
    """alt_data_service._8K_ITEM_LABELS is derived from taxonomy."""

    def test_alt_data_service_labels_equal_taxonomy(self) -> None:
        """The module-level _8K_ITEM_LABELS in alt_data_service must equal ITEM_8K_LABELS."""
        # Import the module; use its public-ish dict via a direct attribute access.
        # We import conditionally to surface import errors clearly.
        import src.alt_data_service as ads  # noqa: PLC0415

        assert ads._8K_ITEM_LABELS == ITEM_8K_LABELS, (
            "alt_data_service._8K_ITEM_LABELS diverged from taxonomy ITEM_8K_LABELS. "
            "It must be derived from src.taxonomy.ITEM_8K_LABELS to maintain a single "
            "source of truth."
        )

    def test_label_items_output_unchanged_for_known_codes(self) -> None:
        """_label_items() must produce the same format as before the refactor.

        Known codes → "CODE: Label"; unknown codes → bare "CODE".
        This is the byte-for-byte contract that existing tests depend on.
        """
        import src.alt_data_service as ads  # noqa: PLC0415

        # Known code (from original 17)
        result = ads.Sec8KFetcher._label_items("4.01")
        assert result == ["4.01: Changes in Certifying Accountant"], (
            f"_label_items('4.01') returned {result!r}"
        )

        # New code 4.02 (should now be labeled, not bare)
        result = ads.Sec8KFetcher._label_items("4.02")
        assert result == ["4.02: Non-Reliance on Previously Issued Financial Statements"], (
            f"_label_items('4.02') returned {result!r}"
        )

        # New code 1.05
        result = ads.Sec8KFetcher._label_items("1.05")
        assert result == ["1.05: Material Cybersecurity Incident"], (
            f"_label_items('1.05') returned {result!r}"
        )

        # Unknown code → bare
        result = ads.Sec8KFetcher._label_items("9.99")
        assert result == ["9.99"], f"_label_items unknown code returned {result!r}"

        # Multi-code string
        result = ads.Sec8KFetcher._label_items("5.02,4.01")
        assert result == [
            "5.02: Directors/Officers Departure/Appointment",
            "4.01: Changes in Certifying Accountant",
        ], f"_label_items multi-code returned {result!r}"


# ============================================================================
# Tests: MATERIAL_EVENT_PREDICATES
# ============================================================================

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9_]*)+$")


class TestMaterialEventPredicates:
    """Structure and content of MATERIAL_EVENT_PREDICATES."""

    def test_all_keys_are_snake_case(self) -> None:
        for key in MATERIAL_EVENT_PREDICATES:
            assert _SNAKE_CASE_RE.match(key), (
                f"Predicate key {key!r} is not in expected snake_case format "
                "(e.g. 'event.going_concern')"
            )

    def test_all_entries_have_valid_category(self) -> None:
        for key, entry in MATERIAL_EVENT_PREDICATES.items():
            assert entry["category"] in ALL_CATEGORIES, (
                f"Predicate {key!r} has unknown category {entry['category']!r}"
            )

    def test_all_entries_have_valid_tier(self) -> None:
        for key, entry in MATERIAL_EVENT_PREDICATES.items():
            assert entry["tier"] in ALL_TIERS, (
                f"Predicate {key!r} has unknown tier {entry['tier']!r}"
            )

    def test_nonempty(self) -> None:
        assert len(MATERIAL_EVENT_PREDICATES) > 0, "MATERIAL_EVENT_PREDICATES is empty"

    def test_includes_downside_predicates(self) -> None:
        """Must contain classic downside/distress predicates."""
        required_downside = {
            "event.going_concern",
            "event.material_weakness",
            "event.restatement",
            "event.cfo_resignation",
            "event.chapter_11_filed",
        }
        for pred in required_downside:
            assert pred in MATERIAL_EVENT_PREDICATES, (
                f"Expected downside predicate {pred!r} not found in MATERIAL_EVENT_PREDICATES"
            )

    def test_includes_upside_predicates(self) -> None:
        """Must contain at least one upside / positive-catalyst predicate."""
        upside = [
            k for k, v in MATERIAL_EVENT_PREDICATES.items()
            if v["category"] == CAT_POSITIVE_CATALYST
        ]
        assert len(upside) >= 1, (
            "MATERIAL_EVENT_PREDICATES must include at least one upside "
            f"(category={CAT_POSITIVE_CATALYST!r}) predicate. "
            "Materiality is direction-agnostic (see playbook principle)."
        )

    def test_tier_s_predicates_are_accounting_or_distress(self) -> None:
        """Spot-check: known Tier-S playbook terms have Tier S in the vocabulary."""
        tier_s_required = {
            "event.going_concern",
            "event.material_weakness",
            "event.non_reliance",
            "event.late_filing_nt",
            "event.wells_notice",
            "event.chapter_11_filed",
        }
        for pred in tier_s_required:
            assert pred in MATERIAL_EVENT_PREDICATES, (
                f"Playbook TIER-S predicate {pred!r} missing from MATERIAL_EVENT_PREDICATES"
            )
            assert MATERIAL_EVENT_PREDICATES[pred]["tier"] == "S", (
                f"Predicate {pred!r} is a TIER-S playbook term but has tier "
                f"{MATERIAL_EVENT_PREDICATES[pred]['tier']!r}"
            )

    def test_category_vocab_matches_taxonomy(self) -> None:
        """All category values in predicates must be in the same ALL_CATEGORIES set."""
        for key, entry in MATERIAL_EVENT_PREDICATES.items():
            assert entry["category"] in ALL_CATEGORIES, (
                f"Predicate {key!r} category {entry['category']!r} not in ALL_CATEGORIES. "
                "Predicate categories must use the same vocabulary as 8-K taxonomy categories."
            )

    def test_predicates_are_namespaced_with_event_prefix(self) -> None:
        """All material-event predicates should use the 'event.' namespace prefix
        to distinguish them from financial predicates (revenue, ebitda, etc.)."""
        for key in MATERIAL_EVENT_PREDICATES:
            assert key.startswith("event."), (
                f"Predicate {key!r} does not start with 'event.' prefix. "
                "Event predicates must be namespaced to distinguish from financial predicates."
            )
