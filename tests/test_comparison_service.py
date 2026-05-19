"""
Unit tests for core/comparison_service.py.

Uses SimpleNamespace mocks for Policy + child objects so we don't have to
build an in-memory DB with foreign-key fixtures just to verify pure-Python
diff math. The service never queries the session, so passing None as the
session is safe.
"""

from types import SimpleNamespace
from typing import Optional

import pytest

# Side-effect imports so any module-level Base.metadata access is happy.
import core.history_model  # noqa: F401
import core.notification_model  # noqa: F401
from core.comparison_service import (
    ComparisonResult,
    ComparisonService,
    CoverageDiff,
    CollectionDiff,
    _humanize_label,
    _parse_premium,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _policy(
    pid: int = 1,
    *,
    carrier_name: Optional[str] = None,
    policy_number: Optional[str] = None,
    premium: object = None,
    insured_name: Optional[str] = None,
    naic_number: Optional[str] = None,
    vehicles=None,
    drivers=None,
    coverages=None,
    additional_interests=None,
    **extras,
) -> SimpleNamespace:
    """Build a Policy-shaped mock. `extras` lets a test override any other
    scalar field without polluting the default-argument list."""
    base = dict(
        id=pid,
        carrier_name=carrier_name,
        policy_number=policy_number,
        premium=premium,
        insured_name=insured_name,
        naic_number=naic_number,
        vehicles=vehicles or [],
        drivers=drivers or [],
        coverages=coverages or [],
        additional_interests=additional_interests or [],
    )
    base.update(extras)
    return SimpleNamespace(**base)


def _vehicle(vin: str, year: str = "2024", make: str = "Ford", model: str = "F150"):
    return SimpleNamespace(
        vin=vin, year=year, make=make, model=model,
        gvw=None, vehicle_type=None, chassis=None, body=None,
    )


def _driver(full_name: str, license_number: str = "DL-A", is_excluded: bool = False):
    return SimpleNamespace(
        full_name=full_name, license_number=license_number, is_excluded=is_excluded,
    )


def _coverage(
    coverage_code: str,
    family: str = "auto_liability",
    type_: str = "BI",
    *,
    vehicle_vin: Optional[str] = None,
    per_person=None,
    per_accident=None,
    per_occurrence=None,
    combined_single_limit=None,
    aggregate=None,
    deductible=None,
):
    veh = SimpleNamespace(vin=vehicle_vin) if vehicle_vin else None
    return SimpleNamespace(
        coverage_code=coverage_code,
        family=family,
        type=type_,
        vehicle=veh,
        per_person=per_person,
        per_accident=per_accident,
        per_occurrence=per_occurrence,
        combined_single_limit=combined_single_limit,
        aggregate=aggregate,
        deductible=deductible,
    )


def _interest(name: str, address: str = "123 Main", interest_type: str = "lienholder"):
    return SimpleNamespace(name=name, address=address, interest_type=interest_type)


@pytest.fixture
def svc():
    # No DB queries happen, so a None session is fine.
    return ComparisonService(session=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHumanizeLabel:
    def test_simple_attr(self):
        assert _humanize_label("carrier_name") == "Carrier Name"

    def test_known_acronyms_stay_upper(self):
        assert _humanize_label("naic_number") == "NAIC Number"
        assert _humanize_label("um_uim_limit") == "UM UIM Limit"
        assert _humanize_label("gl_limit") == "GL Limit"
        assert _humanize_label("pip_limit") == "PIP Limit"

    def test_compound_attrs(self):
        assert _humanize_label("has_full_collision") == "Has Full Collision"


class TestParsePremium:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            ("", None),
            (1000, 1000.0),
            (1234.56, 1234.56),
            ("1234.56", 1234.56),
            ("$1,234.56", 1234.56),
            ("not a number", None),
        ],
    )
    def test_parse(self, value, expected):
        assert _parse_premium(value) == expected


# ---------------------------------------------------------------------------
# Scalar diff
# ---------------------------------------------------------------------------


class TestScalarDiff:
    def test_identical_policies_have_no_changes(self, svc):
        a = _policy(carrier_name="X", policy_number="P1", premium=1000)
        b = _policy(2, carrier_name="X", policy_number="P1", premium=1000)
        result = svc.compare(a, b)
        assert result.summary.n_scalar_changed == 0
        # Every ScalarDiff says equal=True
        assert all(d.equal for d in result.scalar_diffs)

    def test_changed_carrier_flagged(self, svc):
        a = _policy(carrier_name="Progressive")
        b = _policy(2, carrier_name="State Farm")
        result = svc.compare(a, b)
        changed = [d for d in result.scalar_diffs if not d.equal]
        names = {d.field for d in changed}
        assert "carrier_name" in names

    def test_whitespace_normalized_equality(self, svc):
        # HistoryService.normalize delegates to utils.text_utils.normalize_string
        # which strips/collapses whitespace. "  100,000" and "100,000" should
        # therefore compare equal even though their raw values differ.
        # NOTE: Currency-like normalization (',' / '$' stripping) is NOT
        # currently implemented in HistoryService.normalize despite the
        # docstring — pre-existing bug, tracked separately. So we test the
        # behavior that IS implemented.
        a = _policy(liability_limit="  100,000  ")
        b = _policy(2, liability_limit="100,000")
        result = svc.compare(a, b)
        diff = next(d for d in result.scalar_diffs if d.field == "liability_limit")
        assert diff.equal is True

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "Documents a known gap: HistoryService.normalize doesn't strip "
            "commas / $, so '100,000' and '100000' are treated as different. "
            "When normalize is fixed this will start passing — flip the "
            "assertion to `is True` and drop the marker."
        ),
    )
    def test_different_string_formattings_are_currently_treated_as_different(self, svc):
        a = _policy(liability_limit="100,000")
        b = _policy(2, liability_limit="100000")
        result = svc.compare(a, b)
        diff = next(d for d in result.scalar_diffs if d.field == "liability_limit")
        # Pinning the future-correct behavior so the marker auto-flips green
        # once normalization handles thousands separators.
        assert diff.equal is True

    def test_none_vs_value_is_change(self, svc):
        a = _policy(insured_name="Acme")
        b = _policy(2, insured_name=None)
        result = svc.compare(a, b)
        diff = next(d for d in result.scalar_diffs if d.field == "insured_name")
        assert diff.equal is False
        assert diff.value_a == "Acme"
        assert diff.value_b is None

    def test_both_none_is_unchanged(self, svc):
        a = _policy(naic_number=None)
        b = _policy(2, naic_number=None)
        result = svc.compare(a, b)
        diff = next(d for d in result.scalar_diffs if d.field == "naic_number")
        assert diff.equal is True


class TestSelfCompare:
    """Compare a policy against itself — every bucket must be empty and the
    premium delta must be zero. Guards against future defensive-guard edits
    that might short-circuit identical-ID compares incorrectly."""

    def test_self_compare_yields_no_changes(self, svc):
        p = _policy(
            carrier_name="X",
            policy_number="P1",
            premium=1000.0,
            vehicles=[_vehicle("V1"), _vehicle("V2")],
            drivers=[_driver("Jane")],
            coverages=[_coverage("BI", per_person=100000, per_accident=300000)],
            additional_interests=[_interest("Bank A")],
        )
        result = svc.compare(p, p)
        assert result.summary.n_scalar_changed == 0
        assert result.summary.premium_delta == 0.0
        assert result.summary.premium_delta_pct == 0.0
        assert result.vehicles.only_in_a == []
        assert result.vehicles.only_in_b == []
        assert len(result.vehicles.unchanged) == 2
        assert result.drivers.only_in_a == []
        assert result.drivers.only_in_b == []
        assert result.coverages.only_in_a == []
        assert result.coverages.only_in_b == []
        assert result.coverages.limit_changed == []
        assert result.additional_interests.only_in_a == []
        assert result.additional_interests.only_in_b == []


# ---------------------------------------------------------------------------
# Vehicle diff
# ---------------------------------------------------------------------------


class TestVehicleDiff:
    def test_same_vins_unchanged(self, svc):
        a = _policy(vehicles=[_vehicle("VIN1"), _vehicle("VIN2")])
        b = _policy(2, vehicles=[_vehicle("VIN1"), _vehicle("VIN2")])
        result = svc.compare(a, b)
        assert len(result.vehicles.unchanged) == 2
        assert result.vehicles.only_in_a == []
        assert result.vehicles.only_in_b == []

    def test_added_and_removed(self, svc):
        a = _policy(vehicles=[_vehicle("VIN1"), _vehicle("VIN2")])
        b = _policy(2, vehicles=[_vehicle("VIN2"), _vehicle("VIN3")])
        result = svc.compare(a, b)
        # VIN1 only on A; VIN3 only on B; VIN2 on both.
        only_a_vins = {v.vin for v in result.vehicles.only_in_a}
        only_b_vins = {v.vin for v in result.vehicles.only_in_b}
        unchanged_vins = {v.vin for v in result.vehicles.unchanged}
        assert only_a_vins == {"VIN1"}
        assert only_b_vins == {"VIN3"}
        assert unchanged_vins == {"VIN2"}

    def test_empty_fleets(self, svc):
        a = _policy()
        b = _policy(2)
        result = svc.compare(a, b)
        assert result.vehicles == CollectionDiff([], [], [])


# ---------------------------------------------------------------------------
# Driver diff
# ---------------------------------------------------------------------------


class TestDriverDiff:
    def test_same_drivers_unchanged(self, svc):
        a = _policy(drivers=[_driver("Bob", "DL-1")])
        b = _policy(2, drivers=[_driver("Bob", "DL-1")])
        result = svc.compare(a, b)
        assert len(result.drivers.unchanged) == 1
        assert result.drivers.only_in_a == []
        assert result.drivers.only_in_b == []

    def test_different_license_treated_as_different_driver(self, svc):
        a = _policy(drivers=[_driver("Bob", "DL-1")])
        b = _policy(2, drivers=[_driver("Bob", "DL-2")])
        result = svc.compare(a, b)
        assert len(result.drivers.only_in_a) == 1
        assert len(result.drivers.only_in_b) == 1
        assert result.drivers.unchanged == []


# ---------------------------------------------------------------------------
# Coverage diff
# ---------------------------------------------------------------------------


class TestCoverageDiff:
    def test_same_coverages_unchanged(self, svc):
        a = _policy(coverages=[_coverage("BI", per_person=100000, per_accident=300000)])
        b = _policy(
            2,
            coverages=[_coverage("BI", per_person=100000, per_accident=300000)],
        )
        result = svc.compare(a, b)
        assert len(result.coverages.unchanged) == 1
        assert result.coverages.limit_changed == []

    def test_same_code_different_limits_lands_in_limit_changed(self, svc):
        a = _policy(coverages=[_coverage("BI", per_person=100000, per_accident=300000)])
        b = _policy(
            2,
            coverages=[_coverage("BI", per_person=250000, per_accident=500000)],
        )
        result = svc.compare(a, b)
        assert len(result.coverages.limit_changed) == 1
        assert result.coverages.only_in_a == []
        assert result.coverages.only_in_b == []
        cov_a, cov_b = result.coverages.limit_changed[0]
        assert cov_a.per_person == 100000
        assert cov_b.per_person == 250000

    def test_different_codes_are_independent(self, svc):
        a = _policy(coverages=[_coverage("BI")])
        b = _policy(2, coverages=[_coverage("PD")])
        result = svc.compare(a, b)
        assert len(result.coverages.only_in_a) == 1
        assert len(result.coverages.only_in_b) == 1
        assert result.coverages.unchanged == []
        assert result.coverages.limit_changed == []

    def test_vehicle_tied_coverage_keyed_by_vin(self, svc):
        # Two BI coverages on different vehicles are not the same line.
        a = _policy(coverages=[_coverage("BI", vehicle_vin="VIN1")])
        b = _policy(2, coverages=[_coverage("BI", vehicle_vin="VIN2")])
        result = svc.compare(a, b)
        assert len(result.coverages.only_in_a) == 1
        assert len(result.coverages.only_in_b) == 1

    def test_empty_coverages(self, svc):
        result = svc.compare(_policy(), _policy(2))
        assert result.coverages == CoverageDiff([], [], [], [])


# ---------------------------------------------------------------------------
# Additional interests diff
# ---------------------------------------------------------------------------


class TestAdditionalInterestDiff:
    def test_same_interests_unchanged(self, svc):
        a = _policy(additional_interests=[_interest("BankX")])
        b = _policy(2, additional_interests=[_interest("BankX")])
        result = svc.compare(a, b)
        assert len(result.additional_interests.unchanged) == 1


# ---------------------------------------------------------------------------
# Summary KPIs (premium delta math)
# ---------------------------------------------------------------------------


class TestPremiumDelta:
    def test_both_numeric_delta_correct(self, svc):
        a = _policy(premium=1000.0)
        b = _policy(2, premium=1200.0)
        result = svc.compare(a, b)
        assert result.summary.premium_a == 1000.0
        assert result.summary.premium_b == 1200.0
        assert result.summary.premium_delta == pytest.approx(200.0)
        assert result.summary.premium_delta_pct == pytest.approx(20.0)

    def test_negative_delta(self, svc):
        a = _policy(premium=1200.0)
        b = _policy(2, premium=1000.0)
        result = svc.compare(a, b)
        assert result.summary.premium_delta == pytest.approx(-200.0)

    def test_zero_baseline_yields_none_pct(self, svc):
        a = _policy(premium=0)
        b = _policy(2, premium=500)
        result = svc.compare(a, b)
        assert result.summary.premium_delta == 500.0
        # Can't divide by zero — pct must be None, not inf.
        assert result.summary.premium_delta_pct is None

    def test_missing_premium_yields_none(self, svc):
        a = _policy(premium=None)
        b = _policy(2, premium=500)
        result = svc.compare(a, b)
        assert result.summary.premium_delta is None
        assert result.summary.premium_delta_pct is None

    def test_string_premiums_parse(self, svc):
        a = _policy(premium="$1,000.00")
        b = _policy(2, premium="$1,250.00")
        result = svc.compare(a, b)
        assert result.summary.premium_delta == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# End-to-end smoke
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_result_has_correct_policy_ids(self, svc):
        result = svc.compare(_policy(pid=7), _policy(pid=42))
        assert result.policy_a_id == 7
        assert result.policy_b_id == 42

    def test_summary_counts_match_buckets(self, svc):
        a = _policy(
            carrier_name="X",
            premium=1000,
            vehicles=[_vehicle("VIN1"), _vehicle("VIN2")],
            drivers=[_driver("Bob", "DL-1")],
            coverages=[_coverage("BI"), _coverage("PD")],
        )
        b = _policy(
            2,
            carrier_name="Y",  # changed
            premium=1500,
            vehicles=[_vehicle("VIN2"), _vehicle("VIN3")],  # +VIN3, -VIN1
            drivers=[_driver("Carol", "DL-2")],  # different driver
            coverages=[_coverage("BI", per_person=100000)],  # PD removed, BI changed
        )
        result = svc.compare(a, b)
        assert result.summary.n_vehicles_only_in_a == 1  # VIN1
        assert result.summary.n_vehicles_only_in_b == 1  # VIN3
        assert result.summary.n_drivers_only_in_a == 1
        assert result.summary.n_drivers_only_in_b == 1
        assert result.summary.n_coverages_only_in_a == 1  # PD
        assert result.summary.n_coverages_only_in_b == 0
        # BI same code on both sides, different limits → limit_changed
        assert result.summary.n_coverages_limit_changed == 1
        assert result.summary.n_scalar_changed >= 1  # at least carrier_name

    def test_result_is_a_dataclass(self, svc):
        result = svc.compare(_policy(), _policy(2))
        assert isinstance(result, ComparisonResult)
        # Frozen — can't mutate after construction.
        with pytest.raises(Exception):
            result.policy_a_id = 999  # type: ignore[misc]
