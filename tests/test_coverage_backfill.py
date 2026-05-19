"""
Tests for modules/extraction/coverage_backfill.py.

backfill_coverages_from_flat_limits is the safety net that synthesizes
Coverage entries when the LLM populated flat policy fields
(`liability_limit`, `cargo_limit`, …) but left the structured
`coverages[]` array empty. The d8df149 commit was the regression fix
that surfaced this need. These tests lock its behavior so it cannot
silently break.
"""

import pytest

from modules.extraction.coverage_backfill import backfill_coverages_from_flat_limits


# ---------- empty / no-op cases ---------------------------------------------


def test_empty_inputs_produce_no_backfill():
    assert backfill_coverages_from_flat_limits([], {}, "personal_auto") == []


def test_none_inputs_are_safe():
    assert backfill_coverages_from_flat_limits(None, {}, "commercial_auto") == []


def test_no_flat_limits_produces_no_backfill():
    """A coverage already present should not be re-backfilled."""
    existing = [
        {"coverage_code": "AUTO_LIAB_CSL", "family": "auto_liability"},
    ]
    out = backfill_coverages_from_flat_limits(existing, {"liability_limit": "1000000"}, "commercial_auto")
    assert out == []


# ---------- liability_limit -> AUTO_LIAB_CSL --------------------------------


def test_liability_limit_backfills_auto_csl():
    out = backfill_coverages_from_flat_limits(
        [], {"liability_limit": "1,000,000"}, "commercial_auto"
    )
    assert len(out) == 1
    row = out[0]
    assert row["coverage_code"] == "AUTO_LIAB_CSL"
    assert row["family"] == "auto_liability"
    assert row["limits"]["combined_single_limit"] == 1_000_000
    assert row["limit_structure"] == "csl"
    assert row["_backfill_source"] == "policy.liability_limit"


def test_existing_auto_liab_bi_blocks_csl_backfill():
    """Split-limit forms (AUTO_LIAB_BI) must not get an additional CSL row."""
    existing = [{"coverage_code": "AUTO_LIAB_BI", "family": "auto_liability"}]
    out = backfill_coverages_from_flat_limits(
        existing, {"liability_limit": "1,000,000"}, "commercial_auto"
    )
    assert all(r["coverage_code"] != "AUTO_LIAB_CSL" for r in out)


# ---------- cargo -----------------------------------------------------------


def test_cargo_limit_and_deductible_backfilled_together():
    out = backfill_coverages_from_flat_limits(
        [], {"cargo_limit": "100,000", "cargo_deductible": "1,000"}, "commercial_auto"
    )
    cargo_rows = [r for r in out if r["coverage_code"] == "CARGO"]
    assert len(cargo_rows) == 1
    cargo = cargo_rows[0]
    assert cargo["limits"]["per_occurrence"] == 100_000
    assert cargo["deductible"] == 1_000
    assert cargo["family"] == "cargo"


def test_cargo_deductible_alone_still_emits_row():
    out = backfill_coverages_from_flat_limits(
        [], {"cargo_deductible": "500"}, "commercial_auto"
    )
    cargo_rows = [r for r in out if r["coverage_code"] == "CARGO"]
    assert len(cargo_rows) == 1
    assert cargo_rows[0]["deductible"] == 500
    assert cargo_rows[0]["limits"] == {}


# ---------- UM/UIM ----------------------------------------------------------


def test_um_uim_limit_backfills_um_bi():
    out = backfill_coverages_from_flat_limits(
        [], {"um_uim_limit": "500000"}, "commercial_auto"
    )
    um_rows = [r for r in out if r["coverage_code"] == "UM_BI"]
    assert len(um_rows) == 1
    assert um_rows[0]["limits"]["combined_single_limit"] == 500_000


def test_existing_uim_blocks_um_backfill():
    existing = [{"coverage_code": "UIM_BI", "family": "underinsured_motorist"}]
    out = backfill_coverages_from_flat_limits(
        existing, {"um_uim_limit": "500000"}, "commercial_auto"
    )
    assert all(r["coverage_code"] != "UM_BI" for r in out)


# ---------- med_pay (numeric vs "Included") --------------------------------


def test_med_pay_numeric_value():
    out = backfill_coverages_from_flat_limits(
        [], {"med_pay_limit": "5000"}, "commercial_auto"
    )
    med = next(r for r in out if r["coverage_code"] == "MED_PAY")
    assert med["limits"]["per_person"] == 5_000
    assert "limit_descriptor" not in med


def test_med_pay_included_marker():
    """The 'Included' string is a known LLM output and must round-trip as a descriptor."""
    out = backfill_coverages_from_flat_limits(
        [], {"med_pay_limit": "Included"}, "commercial_auto"
    )
    med = next(r for r in out if r["coverage_code"] == "MED_PAY")
    assert med["limits"] == {}
    assert med.get("limit_descriptor") == "Included"


# ---------- PIP -------------------------------------------------------------


def test_pip_limit_backfilled():
    out = backfill_coverages_from_flat_limits(
        [], {"pip_limit": "10000"}, "personal_auto"
    )
    pip = next(r for r in out if r["coverage_code"] == "PIP")
    assert pip["limits"]["per_person"] == 10_000


# ---------- comp / coll deductibles ----------------------------------------


def test_comp_and_coll_deductibles_emit_deductible_only_rows():
    out = backfill_coverages_from_flat_limits(
        [], {"comp_deductible": "500", "coll_deductible": "1000"}, "commercial_auto"
    )
    comp = next(r for r in out if r["coverage_code"] == "COMP")
    coll = next(r for r in out if r["coverage_code"] == "COLL")
    assert comp["deductible"] == 500
    assert comp["limit_structure"] == "deductible_only"
    assert coll["deductible"] == 1_000
    assert coll["limit_structure"] == "deductible_only"


# ---------- general liability gating ---------------------------------------


def test_gl_backfilled_for_general_liability_policy():
    out = backfill_coverages_from_flat_limits(
        [], {"general_liability_limit": "1000000"}, "general_liability"
    )
    gl = next(r for r in out if r["coverage_code"] == "GL_OCCURRENCE")
    assert gl["limits"]["per_occurrence"] == 1_000_000


def test_gl_skipped_for_personal_auto():
    """GL backfill must not run for personal_auto even if the flat field is set."""
    out = backfill_coverages_from_flat_limits(
        [], {"general_liability_limit": "1000000"}, "personal_auto"
    )
    assert all(r["coverage_code"] != "GL_OCCURRENCE" for r in out)


def test_gl_backfilled_for_commercial_auto_only_when_field_present():
    out_present = backfill_coverages_from_flat_limits(
        [], {"general_liability_limit": "1000000"}, "commercial_auto"
    )
    assert any(r["coverage_code"] == "GL_OCCURRENCE" for r in out_present)

    out_absent = backfill_coverages_from_flat_limits(
        [], {}, "commercial_auto"
    )
    assert all(r["coverage_code"] != "GL_OCCURRENCE" for r in out_absent)


# ---------- _money parser via behavior --------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,000,000", 1_000_000),
        ("$1,000,000.00", 1_000_000),
        ("100k", 100_000),
        ("1.5m", 1_500_000),
        ("2b", 2_000_000_000),
        ("100K", 100_000),  # case-insensitive suffix
        ("not a number", None),
        ("", None),
        (None, None),
        ("included", None),  # special case is handled by _money returning None
    ],
)
def test_money_parser_via_liability_backfill(raw, expected):
    out = backfill_coverages_from_flat_limits([], {"liability_limit": raw}, "commercial_auto")
    if expected is None:
        # No row emitted when the value parses to None.
        assert all(r["coverage_code"] != "AUTO_LIAB_CSL" for r in out)
    else:
        row = next(r for r in out if r["coverage_code"] == "AUTO_LIAB_CSL")
        assert row["limits"]["combined_single_limit"] == expected


# ---------- d8df149 regression ---------------------------------------------


def test_d8df149_regression_empty_coverages_with_three_flat_limits():
    """The exact scenario commit d8df149 fixed: LLM returned empty coverages[]
    but flat liability + um_uim + med_pay 'Included' were populated. All three
    must materialize through the backfill."""
    out = backfill_coverages_from_flat_limits(
        existing=[],
        flat={
            "liability_limit": "1,000,000",
            "um_uim_limit": "1,000,000",
            "med_pay_limit": "Included",
        },
        policy_type="commercial_auto",
    )
    codes = {r["coverage_code"] for r in out}
    assert {"AUTO_LIAB_CSL", "UM_BI", "MED_PAY"}.issubset(codes)
