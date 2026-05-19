"""
Unit tests for views/ui_utils.py.

The helpers in ui_utils are pure functions about widget labels and the soft
confidence gate. They live with views/ rather than utils/ because they shape
the review UI, but they have no Streamlit dependency and can be unit-tested
without a runtime.
"""

import pytest

from views.ui_utils import (
    CONFIDENCE_LEGEND_CAPTION,
    CONFIDENCE_LEVELS,
    build_confidence_map,
    confidence_label,
    gate_value,
    should_clear_field,
)


# ---------------------------------------------------------------------------
# build_confidence_map
# ---------------------------------------------------------------------------


class TestBuildConfidenceMap:
    """Regression coverage for the helper used to surface confidence badges."""

    def test_strips_confidence_suffix_from_policy_keys(self):
        payload = {
            "policy_number": "PN-1",
            "policy_number_confidence": "high",
            "effective_date": "2025-01-01",
            "effective_date_confidence": "medium",
            "premium": 1234.56,
            "premium_confidence": "low",
        }
        result = build_confidence_map(payload)
        assert result == {
            "policy_number": "high",
            "effective_date": "medium",
            "premium": "low",
        }

    def test_ignores_unknown_confidence_values(self):
        payload = {
            "policy_number_confidence": "extremely-high",  # not in CONFIDENCE_LEVELS
            "carrier_name_confidence": "MEDIUM",  # case sensitive — also ignored
            "insured_name_confidence": "high",
        }
        result = build_confidence_map(payload)
        # only the literal "high" survives
        assert result == {"insured_name": "high"}

    def test_drops_non_string_suffix_keys(self):
        payload = {
            123: "high",  # non-string key
            "policy_number_confidence": "high",
        }
        result = build_confidence_map(payload)
        assert result == {"policy_number": "high"}

    def test_fallback_map_merges_with_policy_winning(self):
        fallback = {"policy_number": "low", "carrier_name": "medium"}
        payload = {"policy_number_confidence": "high"}  # overrides fallback
        result = build_confidence_map(payload, fallback_map=fallback)
        assert result == {
            "policy_number": "high",
            "carrier_name": "medium",
        }

    def test_handles_none_and_non_dict_inputs(self):
        # None payload
        assert build_confidence_map(None) == {}
        # Non-dict fallback is silently ignored
        assert build_confidence_map({"x_confidence": "high"}, fallback_map="not-a-dict") == {
            "x": "high"
        }


# ---------------------------------------------------------------------------
# should_clear_field — the soft confidence gate
# ---------------------------------------------------------------------------


# Truth table: (threshold, field_confidence) -> expected should_clear
_GATE_TRUTH_TABLE = [
    # threshold "off" — gate disabled, never clears
    ("off", "high", False),
    ("off", "medium", False),
    ("off", "low", False),
    # threshold "medium" — clears only "low"
    ("medium", "high", False),
    ("medium", "medium", False),
    ("medium", "low", True),
    # threshold "high" — clears "low" and "medium"
    ("high", "high", False),
    ("high", "medium", True),
    ("high", "low", True),
]


class TestShouldClearField:
    @pytest.mark.parametrize("threshold,confidence,expected", _GATE_TRUTH_TABLE)
    def test_truth_table(self, threshold, confidence, expected):
        cm = {"policy_number": confidence}
        assert should_clear_field("policy_number", cm, threshold) is expected

    def test_missing_field_defaults_to_high_so_never_cleared(self):
        # An LLM that said nothing is assumed confident — don't wipe values
        # that didn't even get a confidence vote.
        cm = {}
        for threshold in ("off", "medium", "high"):
            assert should_clear_field("unmentioned", cm, threshold) is False

    def test_unknown_threshold_disables_gate(self):
        cm = {"policy_number": "low"}
        # typos / stale session-state values must not accidentally clear data
        assert should_clear_field("policy_number", cm, "strictest") is False
        assert should_clear_field("policy_number", cm, "") is False
        assert should_clear_field("policy_number", cm, None) is False  # type: ignore[arg-type]

    def test_garbage_confidence_value_disables_gate_for_that_field(self):
        cm = {"policy_number": "kinda-sure"}
        # garbage in cm → treat as missing → no clear
        assert should_clear_field("policy_number", cm, "high") is False


# ---------------------------------------------------------------------------
# gate_value — the type-aware blank substitution wrapper
# ---------------------------------------------------------------------------


class TestGateValue:
    def test_returns_raw_when_confidence_above_threshold(self):
        cm = {"policy_number": "high"}
        assert gate_value("PN-1", "policy_number", cm, "medium", blank="") == "PN-1"

    def test_returns_blank_when_confidence_below_threshold(self):
        cm = {"policy_number": "low"}
        assert gate_value("PN-1", "policy_number", cm, "medium", blank="") == ""

    def test_blank_for_date_widget(self):
        cm = {"effective_date": "low"}
        assert gate_value("2025-01-01", "effective_date", cm, "medium", blank=None) is None

    def test_blank_for_number_widget(self):
        cm = {"premium": "medium"}
        assert gate_value(1234.56, "premium", cm, "high", blank=None) is None

    def test_threshold_off_returns_raw_even_for_low_confidence(self):
        cm = {"policy_number": "low"}
        assert gate_value("PN-1", "policy_number", cm, "off", blank="") == "PN-1"

    def test_unknown_field_returns_raw_unchanged(self):
        # Field has no confidence entry → defaults to high → not gated
        assert gate_value("value", "unmentioned", {}, "high", blank="") == "value"


# ---------------------------------------------------------------------------
# confidence_label — already in production but lacks regression tests
# ---------------------------------------------------------------------------


class TestConfidenceLabel:
    def test_high_confidence_no_prefix(self):
        assert confidence_label("Policy Number", "policy_number", {"policy_number": "high"}) == "Policy Number"

    def test_medium_confidence_half_circle_prefix(self):
        assert confidence_label("Effective Date", "effective_date", {"effective_date": "medium"}) == "◐ Effective Date"

    def test_low_confidence_warning_prefix(self):
        assert confidence_label("Premium", "premium", {"premium": "low"}) == "⚠️ Premium"

    def test_missing_field_defaults_to_high(self):
        assert confidence_label("Carrier", "carrier_name", {}) == "Carrier"


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_confidence_levels_is_a_set_of_known_strings(self):
        assert CONFIDENCE_LEVELS == {"high", "medium", "low"}

    def test_legend_caption_mentions_both_badges(self):
        # The caption must explain ◐ AND ⚠️ so users can decode badges.
        assert "◐" in CONFIDENCE_LEGEND_CAPTION
        assert "⚠️" in CONFIDENCE_LEGEND_CAPTION
