"""
ComparisonService — pure read-only diff between two saved Policy rows.

Powers the "Compare" page. Returns a structured `ComparisonResult` with
scalar field deltas, collection (vehicle/driver/coverage/additional-interest)
deltas grouped by side, and a `ComparisonSummary` of KPIs for the page's
header strip.

Naming convention is intentionally neutral:
  only_in_a — present in A, absent from B
  only_in_b — present in B, absent from A
  unchanged — present in both with identical signature
A/B don't imply newer/older; the page can label sides however it likes
(by customer, by date, etc.).

Field maps and signature tuples are reused from `HistoryService` so there's
exactly one source of truth for "what counts as a scalar field" and "what
makes two vehicles equal." Trade-off documented in the feature plan:
private-method coupling vs. duplicated lists that drift over time. We
chose coupling so a schema change in HistoryService propagates here on
the next test run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from .database import Policy
from .history_service import HistoryService


# ---------------------------------------------------------------------------
# Result shapes (frozen so callers can't mutate after construction).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScalarDiff:
    field: str          # ORM attribute name, e.g. "carrier_name"
    label: str          # human-readable, e.g. "Carrier name"
    value_a: Any
    value_b: Any
    equal: bool


@dataclass(frozen=True)
class CollectionDiff:
    """Generic diff bucket for vehicles, drivers, additional_interests."""
    only_in_a: list
    only_in_b: list
    unchanged: list


@dataclass(frozen=True)
class CoverageDiff:
    """Coverages get an extra `limit_changed` bucket — same coverage_code
    on both sides but the limit / deductible numbers differ."""
    only_in_a: list
    only_in_b: list
    unchanged: list
    limit_changed: list  # list of (coverage_a, coverage_b) tuples


@dataclass(frozen=True)
class ComparisonSummary:
    n_scalar_changed: int
    n_vehicles_only_in_a: int
    n_vehicles_only_in_b: int
    n_drivers_only_in_a: int
    n_drivers_only_in_b: int
    n_coverages_only_in_a: int
    n_coverages_only_in_b: int
    n_coverages_limit_changed: int
    premium_a: Optional[float]
    premium_b: Optional[float]
    premium_delta: Optional[float]      # b - a; None when either side is unparseable
    premium_delta_pct: Optional[float]  # 100*(b-a)/a; None when a is 0 or unparseable


@dataclass(frozen=True)
class ComparisonResult:
    policy_a_id: int
    policy_b_id: int
    scalar_diffs: list  # list[ScalarDiff]
    vehicles: CollectionDiff
    drivers: CollectionDiff
    coverages: CoverageDiff
    additional_interests: CollectionDiff
    summary: ComparisonSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _humanize_label(attr: str) -> str:
    """ORM attribute name -> human-readable column header.

    'naic_number' -> 'NAIC Number'
    'has_full_collision' -> 'Has Full Collision'
    """
    parts = attr.split("_")
    # Special-case common acronyms so they aren't title-cased into 'Naic'.
    upper = {"naic", "gl", "um", "uim", "pip", "vin"}
    out = [p.upper() if p in upper else p.capitalize() for p in parts]
    return " ".join(out)


def _parse_premium(value) -> Optional[float]:
    """Best-effort float coercion. Returns None when unparseable.
    Mirrors views/renewals.py:_parse_premium but returns None (not 0.0) so
    the summary can distinguish 'missing' from 'zero'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ComparisonService:
    def __init__(self, session: Session):
        self.session = session
        # HistoryService owns the field map and the signature tuples. We
        # instantiate it with the same session so we can call its sig methods;
        # none of those methods actually touch the session.
        self._hs = HistoryService(session)

    # -- public ------------------------------------------------------------

    def compare(self, policy_a: Policy, policy_b: Policy) -> ComparisonResult:
        """Diff two saved Policy rows. Both arguments must be ORM objects
        already loaded from the session."""
        scalar_diffs = self._scalar_diffs(policy_a, policy_b)
        vehicles = self._collection_diff(
            policy_a.vehicles or [], policy_b.vehicles or [], self._hs._vehicle_sig
        )
        drivers = self._collection_diff(
            policy_a.drivers or [], policy_b.drivers or [], self._hs._driver_sig
        )
        coverages = self._coverage_diff(
            policy_a.coverages or [], policy_b.coverages or []
        )
        additional_interests = self._collection_diff(
            policy_a.additional_interests or [],
            policy_b.additional_interests or [],
            self._hs._additional_interest_sig,
        )
        summary = self._summary(
            policy_a, policy_b, scalar_diffs, vehicles, drivers, coverages
        )
        return ComparisonResult(
            policy_a_id=policy_a.id,
            policy_b_id=policy_b.id,
            scalar_diffs=scalar_diffs,
            vehicles=vehicles,
            drivers=drivers,
            coverages=coverages,
            additional_interests=additional_interests,
            summary=summary,
        )

    # -- scalar ------------------------------------------------------------

    def _scalar_diffs(self, policy_a: Policy, policy_b: Policy) -> list[ScalarDiff]:
        """One ScalarDiff per attribute in HistoryService.SCALAR_FIELD_MAP."""
        diffs = []
        # SCALAR_FIELD_MAP is {json_key: attr}. We use the attr (the ORM side).
        seen: set = set()
        for _json_key, attr in HistoryService.SCALAR_FIELD_MAP.items():
            if attr in seen:
                continue
            seen.add(attr)
            value_a = getattr(policy_a, attr, None)
            value_b = getattr(policy_b, attr, None)
            # Normalize for equality so '100,000' and 100000 don't count
            # as different (same normalization HistoryService uses on saves).
            norm_a = self._hs._normalize(value_a)
            norm_b = self._hs._normalize(value_b)
            equal = norm_a == norm_b
            diffs.append(
                ScalarDiff(
                    field=attr,
                    label=_humanize_label(attr),
                    value_a=value_a,
                    value_b=value_b,
                    equal=equal,
                )
            )
        return diffs

    # -- generic collection diff (vehicles, drivers, additional_interests) -

    def _collection_diff(self, rows_a, rows_b, sig_func) -> CollectionDiff:
        """Diff two row lists by their signature tuple. Returns rows
        (not sigs) so the UI can render the actual fields."""
        # Build sig -> first-seen-row maps so the UI can display the
        # underlying object after the diff math.
        a_by_sig: dict = {}
        for r in rows_a:
            a_by_sig.setdefault(sig_func(r), r)
        b_by_sig: dict = {}
        for r in rows_b:
            b_by_sig.setdefault(sig_func(r), r)

        a_sigs = set(a_by_sig.keys())
        b_sigs = set(b_by_sig.keys())

        only_in_a = [a_by_sig[s] for s in a_sigs - b_sigs]
        only_in_b = [b_by_sig[s] for s in b_sigs - a_sigs]
        unchanged = [a_by_sig[s] for s in a_sigs & b_sigs]
        return CollectionDiff(
            only_in_a=only_in_a, only_in_b=only_in_b, unchanged=unchanged
        )

    # -- coverages with limit_changed bucket -------------------------------

    def _coverage_diff(self, rows_a, rows_b) -> CoverageDiff:
        """Coverage diff with an extra `limit_changed` bucket — same
        (coverage_code, vehicle_vin) on both sides but different limits."""
        sig_full = self._hs._coverage_sig

        def _ident(cov):
            """Identity key for 'same coverage line' — only the type/code
            and which vehicle it's tied to. Limits are deliberately excluded
            so a changed limit moves into the 'limit_changed' bucket
            instead of falsely flagging as add+remove."""
            if isinstance(cov, dict):
                vehicle_vin = cov.get("vehicle_vin")
                return (
                    cov.get("coverage_code"),
                    cov.get("family"),
                    cov.get("type") or cov.get("display_name"),
                    vehicle_vin,
                )
            vehicle = getattr(cov, "vehicle", None)
            return (
                getattr(cov, "coverage_code", None),
                getattr(cov, "family", None),
                getattr(cov, "type", None),
                getattr(vehicle, "vin", None),
            )

        a_by_id: dict = {}
        for r in rows_a:
            a_by_id.setdefault(_ident(r), r)
        b_by_id: dict = {}
        for r in rows_b:
            b_by_id.setdefault(_ident(r), r)

        a_ids = set(a_by_id.keys())
        b_ids = set(b_by_id.keys())

        only_in_a = [a_by_id[i] for i in a_ids - b_ids]
        only_in_b = [b_by_id[i] for i in b_ids - a_ids]

        unchanged = []
        limit_changed = []
        for ident in a_ids & b_ids:
            cov_a = a_by_id[ident]
            cov_b = b_by_id[ident]
            if sig_full(cov_a) == sig_full(cov_b):
                unchanged.append(cov_a)
            else:
                limit_changed.append((cov_a, cov_b))

        return CoverageDiff(
            only_in_a=only_in_a,
            only_in_b=only_in_b,
            unchanged=unchanged,
            limit_changed=limit_changed,
        )

    # -- summary -----------------------------------------------------------

    def _summary(
        self,
        policy_a: Policy,
        policy_b: Policy,
        scalar_diffs: list[ScalarDiff],
        vehicles: CollectionDiff,
        drivers: CollectionDiff,
        coverages: CoverageDiff,
    ) -> ComparisonSummary:
        n_scalar_changed = sum(1 for d in scalar_diffs if not d.equal)
        prem_a = _parse_premium(getattr(policy_a, "premium", None))
        prem_b = _parse_premium(getattr(policy_b, "premium", None))
        if prem_a is None or prem_b is None:
            delta = None
            delta_pct = None
        else:
            delta = prem_b - prem_a
            if prem_a == 0:
                delta_pct = None  # can't divide by zero baseline
            else:
                delta_pct = 100.0 * delta / prem_a
        return ComparisonSummary(
            n_scalar_changed=n_scalar_changed,
            n_vehicles_only_in_a=len(vehicles.only_in_a),
            n_vehicles_only_in_b=len(vehicles.only_in_b),
            n_drivers_only_in_a=len(drivers.only_in_a),
            n_drivers_only_in_b=len(drivers.only_in_b),
            n_coverages_only_in_a=len(coverages.only_in_a),
            n_coverages_only_in_b=len(coverages.only_in_b),
            n_coverages_limit_changed=len(coverages.limit_changed),
            premium_a=prem_a,
            premium_b=prem_b,
            premium_delta=delta,
            premium_delta_pct=delta_pct,
        )
