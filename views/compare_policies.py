"""
Compare Policies page — side-by-side diff of two saved policies.

This commit is the skeleton: two pickers, the KPI strip, and the scalar
diff table. Collection-diff expanders (vehicles / drivers / coverages /
additional interests) land in the next commit; for now those sections
show "details in next release" placeholders so the page renders cleanly.

Layout:
- Title + caption.
- Two columns of pickers (Policy A on the left, Policy B on the right).
- Empty-state instruction when either picker is unset.
- KPI strip (4 metrics) when both are picked.
- "Different customers" warning caption when the two policies don't
  share a customer_id.
- Scalar diff table with a "Δ" emoji column to make changed rows pop.
- Placeholder expanders for the four collection sections.

Data comes from `ComparisonService.compare()`; no SQL lives here.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from core.comparison_service import (
    ComparisonResult,
    ComparisonService,
    ScalarDiff,
)
from core.database import Policy, get_session
from core.logger import logger
from core.services import PolicyService


# ---------------------------------------------------------------------------
# Picker helpers
# ---------------------------------------------------------------------------


def _policy_picker_options(policies: list[Policy]) -> dict[int, str]:
    """Map policy.id -> label string for the selectbox.

    Label format keeps the most useful identity fields together so the
    broker doesn't have to drill into a customer to find a specific
    renewal year. Example:
        "Acme Trucking — Progressive — AB-12345 — exp Dec 31, 2025"
    """
    out: dict[int, str] = {}
    for p in policies:
        bits = [
            (p.insured_name or "(no customer)").strip(),
            (p.carrier_name or "—").strip(),
            (p.policy_number or "(no policy #)").strip(),
        ]
        if p.expiration_date:
            bits.append(f"exp {p.expiration_date.strftime('%b %d, %Y')}")
        out[p.id] = " — ".join(bits)
    return out


def _render_picker(
    label: str,
    options: dict[int, str],
    *,
    key: str,
    exclude_id: Optional[int] = None,
) -> Optional[int]:
    """Selectbox over the available policies, returning the chosen
    policy_id or None when nothing is picked.

    `exclude_id` lets us hide the policy already chosen on the other
    side so the broker can't accidentally compare a policy against
    itself."""
    if exclude_id is not None:
        options = {pid: lbl for pid, lbl in options.items() if pid != exclude_id}
    keys = [None, *options.keys()]
    return st.selectbox(
        label,
        options=keys,
        format_func=lambda pid: "— pick a policy —" if pid is None else options[pid],
        key=key,
    )


# ---------------------------------------------------------------------------
# KPI strip
# ---------------------------------------------------------------------------


def _render_kpi_strip(result: ComparisonResult) -> None:
    s = result.summary
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Scalar fields changed",
        s.n_scalar_changed,
        help="Number of rows in the table below where Policy A and "
        "Policy B differ.",
    )
    k2.metric(
        "Vehicles Δ",
        f"+{s.n_vehicles_only_in_b} / −{s.n_vehicles_only_in_a}",
        help=f"{s.n_vehicles_only_in_b} only on Policy B, "
        f"{s.n_vehicles_only_in_a} only on Policy A.",
    )
    k3.metric(
        "Drivers Δ",
        f"+{s.n_drivers_only_in_b} / −{s.n_drivers_only_in_a}",
    )
    # Premium delta — handle None gracefully (missing premium on either side).
    if s.premium_delta is None:
        prem_display = "—"
        prem_help = "Premium not parseable on at least one policy."
    elif s.premium_delta_pct is None:
        # Zero baseline → show dollar delta only.
        sign = "+" if s.premium_delta >= 0 else "−"
        prem_display = f"{sign}${abs(s.premium_delta):,.0f}"
        prem_help = "Cannot compute %% — Policy A premium is zero."
    else:
        sign = "+" if s.premium_delta >= 0 else "−"
        prem_display = f"{sign}${abs(s.premium_delta):,.0f}"
        prem_help = f"Policy A: ${s.premium_a:,.2f} → Policy B: ${s.premium_b:,.2f}"
    k4.metric(
        "Premium Δ",
        prem_display,
        delta=(
            f"{s.premium_delta_pct:+.1f}%"
            if s.premium_delta_pct is not None
            else None
        ),
        # Premium going up is "bad" for the broker; flip Streamlit's default
        # so a positive delta renders red and a drop renders green.
        delta_color="inverse",
        help=prem_help,
    )


# ---------------------------------------------------------------------------
# Scalar diff table
# ---------------------------------------------------------------------------


def _scalar_diffs_to_dataframe(scalar_diffs: list[ScalarDiff]) -> pd.DataFrame:
    """Display shape: Δ marker + label + A value + B value, sorted with
    the changed rows on top so the broker doesn't have to scroll past
    identical rows to find what moved."""
    rows = []
    for d in scalar_diffs:
        rows.append(
            {
                "Δ": "" if d.equal else "🟡",
                "Field": d.label,
                "Policy A": "—" if d.value_a is None else str(d.value_a),
                "Policy B": "—" if d.value_b is None else str(d.value_b),
            }
        )
    df = pd.DataFrame(rows)
    # Changed rows first; then alphabetically within each group.
    return df.sort_values(by=["Δ", "Field"], ascending=[False, True]).reset_index(drop=True)


def _render_scalar_table(result: ComparisonResult) -> None:
    df = _scalar_diffs_to_dataframe(result.scalar_diffs)
    st.markdown("##### Field-by-field comparison")
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "Δ": st.column_config.TextColumn(
                width="small",
                help="🟡 marks a field where Policy A and Policy B differ.",
            ),
            "Field": st.column_config.TextColumn(width="medium"),
            "Policy A": st.column_config.TextColumn(width="large"),
            "Policy B": st.column_config.TextColumn(width="large"),
        },
    )


# ---------------------------------------------------------------------------
# Collection-diff detail tables
# ---------------------------------------------------------------------------


def _get(row, *attrs, default=None):
    """Attribute-or-key access. Mirrors the helper in the email drafter so
    the same code works on ORM objects, dicts, and SimpleNamespace mocks."""
    last_idx = len(attrs) - 1
    for idx, attr in enumerate(attrs):
        if row is None:
            return default
        if isinstance(row, dict):
            if attr in row:
                row = row[attr]
            else:
                return default
        else:
            row = getattr(row, attr, None)
            if row is None and idx < last_idx:
                return default
    return row if row is not None else default


def _cell(row, *attrs, default: str = "—") -> str:
    """`_get` + stringification with an em-dash for None.

    Why this exists: pandas + pyarrow demands a uniform column type when
    Streamlit renders a dataframe. If one row's "CSL" is an int (100000)
    and another row's is the "—" placeholder for missing, Arrow refuses
    to convert the column. Coercing every cell to `str` up front sidesteps
    that. Numeric formatting is intentionally raw (no $/commas) because
    these tables are reference views, not statements."""
    value = _get(row, *attrs, default=None)
    if value is None or value == "":
        return default
    return str(value)


def _vehicles_dataframe(rows: list) -> pd.DataFrame:
    # Every cell is a string — see _cell docstring for why.
    return pd.DataFrame(
        [
            {
                "Year": _cell(r, "year"),
                "Make": _cell(r, "make"),
                "Model": _cell(r, "model"),
                "VIN": _cell(r, "vin"),
                "GVW": _cell(r, "gvw"),
                "Type": _cell(r, "vehicle_type"),
            }
            for r in rows
        ]
    )


def _drivers_dataframe(rows: list) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Name": _cell(r, "full_name"),
                "License": _cell(r, "license_number"),
                "Excluded": "Yes" if _get(r, "is_excluded") else "No",
            }
            for r in rows
        ]
    )


def _coverages_dataframe(rows: list) -> pd.DataFrame:
    # All limit columns are stringified so numeric carrier values don't
    # collide with the "—" placeholder for missing fields when pyarrow
    # tries to pick a uniform column type.
    return pd.DataFrame(
        [
            {
                "Code": _cell(r, "coverage_code"),
                "Family": _cell(r, "family"),
                "Type": _cell(r, "type"),
                "Vehicle VIN": _cell(r, "vehicle", "vin"),
                "Per Person": _cell(r, "per_person"),
                "Per Accident": _cell(r, "per_accident"),
                "CSL": _cell(r, "combined_single_limit"),
                "Aggregate": _cell(r, "aggregate"),
                "Deductible": _cell(r, "deductible"),
            }
            for r in rows
        ]
    )


def _coverages_limit_changed_dataframe(pairs: list) -> pd.DataFrame:
    """Side-by-side display for the limit_changed bucket. Each row pairs
    one A coverage with its matching B coverage so the broker can read
    the deltas in place. All cells are strings (limit columns interpolate
    via f-strings, identity columns via _cell)."""
    out = []
    for cov_a, cov_b in pairs:
        out.append(
            {
                "Code": _cell(cov_a, "coverage_code"),
                "Vehicle VIN": _cell(cov_a, "vehicle", "vin"),
                "Per Person (A → B)": (
                    f"{_cell(cov_a, 'per_person')} → {_cell(cov_b, 'per_person')}"
                ),
                "Per Accident (A → B)": (
                    f"{_cell(cov_a, 'per_accident')} → {_cell(cov_b, 'per_accident')}"
                ),
                "CSL (A → B)": (
                    f"{_cell(cov_a, 'combined_single_limit')} → "
                    f"{_cell(cov_b, 'combined_single_limit')}"
                ),
                "Aggregate (A → B)": (
                    f"{_cell(cov_a, 'aggregate')} → {_cell(cov_b, 'aggregate')}"
                ),
                "Deductible (A → B)": (
                    f"{_cell(cov_a, 'deductible')} → {_cell(cov_b, 'deductible')}"
                ),
            }
        )
    return pd.DataFrame(out)


def _interests_dataframe(rows: list) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Name": _cell(r, "name"),
                "Address": _cell(r, "address"),
                "Type": _cell(r, "interest_type"),
            }
            for r in rows
        ]
    )


def _render_sub_table(title: str, df: pd.DataFrame) -> None:
    """One labeled sub-section inside a collection expander. Hides when
    the dataframe is empty so unused sections don't clutter the page."""
    if df is None or df.empty:
        return
    st.markdown(f"**{title}** ({len(df)})")
    st.dataframe(df, width="stretch", hide_index=True)


def _render_collection_details(result: ComparisonResult) -> None:
    """Replace the placeholder expanders with real detail tables.

    Empty buckets are simply omitted from each expander so the page
    doesn't fill up with "0 rows" sections."""
    st.markdown("##### Collection differences")

    s = result.summary

    # --- Vehicles ----------------------------------------------------------
    with st.expander(
        f"🚗 Vehicles — {s.n_vehicles_only_in_a} only on A, "
        f"{s.n_vehicles_only_in_b} only on B, "
        f"{len(result.vehicles.unchanged)} unchanged",
        expanded=(s.n_vehicles_only_in_a + s.n_vehicles_only_in_b) > 0,
    ):
        _render_sub_table("Only on Policy A", _vehicles_dataframe(result.vehicles.only_in_a))
        _render_sub_table("Only on Policy B", _vehicles_dataframe(result.vehicles.only_in_b))
        _render_sub_table("Unchanged (on both)", _vehicles_dataframe(result.vehicles.unchanged))
        if not (result.vehicles.only_in_a or result.vehicles.only_in_b or result.vehicles.unchanged):
            st.caption("Neither policy has any vehicles on file.")

    # --- Drivers -----------------------------------------------------------
    with st.expander(
        f"🧑 Drivers — {s.n_drivers_only_in_a} only on A, "
        f"{s.n_drivers_only_in_b} only on B, "
        f"{len(result.drivers.unchanged)} unchanged",
        expanded=(s.n_drivers_only_in_a + s.n_drivers_only_in_b) > 0,
    ):
        _render_sub_table("Only on Policy A", _drivers_dataframe(result.drivers.only_in_a))
        _render_sub_table("Only on Policy B", _drivers_dataframe(result.drivers.only_in_b))
        _render_sub_table("Unchanged (on both)", _drivers_dataframe(result.drivers.unchanged))
        if not (result.drivers.only_in_a or result.drivers.only_in_b or result.drivers.unchanged):
            st.caption("Neither policy has any drivers on file.")

    # --- Coverages ---------------------------------------------------------
    cov_movement = (
        s.n_coverages_only_in_a + s.n_coverages_only_in_b + s.n_coverages_limit_changed
    )
    with st.expander(
        f"🛡️ Coverages — {s.n_coverages_only_in_a} only on A, "
        f"{s.n_coverages_only_in_b} only on B, "
        f"{s.n_coverages_limit_changed} with changed limits, "
        f"{len(result.coverages.unchanged)} unchanged",
        expanded=cov_movement > 0,
    ):
        _render_sub_table(
            "Limit changed (same line, new numbers)",
            _coverages_limit_changed_dataframe(result.coverages.limit_changed),
        )
        _render_sub_table("Only on Policy A", _coverages_dataframe(result.coverages.only_in_a))
        _render_sub_table("Only on Policy B", _coverages_dataframe(result.coverages.only_in_b))
        _render_sub_table("Unchanged (on both)", _coverages_dataframe(result.coverages.unchanged))
        if not (
            result.coverages.only_in_a
            or result.coverages.only_in_b
            or result.coverages.unchanged
            or result.coverages.limit_changed
        ):
            st.caption("Neither policy has any coverages on file.")

    # --- Additional Interests ---------------------------------------------
    ai = result.additional_interests
    with st.expander(
        f"📎 Additional Interests — {len(ai.only_in_a)} only on A, "
        f"{len(ai.only_in_b)} only on B, "
        f"{len(ai.unchanged)} unchanged",
        expanded=(len(ai.only_in_a) + len(ai.only_in_b)) > 0,
    ):
        _render_sub_table("Only on Policy A", _interests_dataframe(ai.only_in_a))
        _render_sub_table("Only on Policy B", _interests_dataframe(ai.only_in_b))
        _render_sub_table("Unchanged (on both)", _interests_dataframe(ai.unchanged))
        if not (ai.only_in_a or ai.only_in_b or ai.unchanged):
            st.caption("Neither policy has any additional interests on file.")


# ---------------------------------------------------------------------------
# Page entry point
# ---------------------------------------------------------------------------


def page_compare_policies() -> None:
    st.title("🔀 Compare Policies")
    st.caption(
        "Pick two saved policies — usually a renewal and its prior version — "
        "to see what changed."
    )

    session = get_session(st.session_state.db_engine)
    try:
        policies = (
            session.query(Policy)
            .order_by(Policy.insured_name.asc(), Policy.expiration_date.desc())
            .all()
        )
        if not policies:
            st.info(
                "No policies in the database yet. Extract one from "
                "**Process Policies** first."
            )
            return

        options = _policy_picker_options(policies)

        left_col, right_col = st.columns(2)
        with left_col:
            pid_a = _render_picker(
                "Policy A", options, key="compare_picker_a"
            )
        with right_col:
            pid_b = _render_picker(
                "Policy B",
                options,
                key="compare_picker_b",
                exclude_id=pid_a,
            )

        # Auto-pair: when Policy A is set and a confirmed renewal/
        # replacement relationship exists, offer a one-click button to fill
        # in Policy B. Only fires on confirmed relationships so a low-
        # confidence guess from the save flow can't surprise the broker.
        if pid_a is not None and pid_b is None:
            related = PolicyService(session).find_related_policy(pid_a)
            if related is not None and related.id in options:
                if st.button(
                    f"🔗 Auto-pair with prior renewal "
                    f"({options[related.id]})",
                    type="secondary",
                    width="stretch",
                ):
                    st.session_state["compare_picker_b"] = related.id
                    st.rerun()
            elif related is None:
                st.caption(
                    "_No confirmed prior renewal on file for Policy A — "
                    "pick Policy B manually._"
                )

        if pid_a is None or pid_b is None:
            st.info("Pick a policy on both sides to see the comparison.")
            return

        policy_a = session.get(Policy, pid_a)
        policy_b = session.get(Policy, pid_b)
        if policy_a is None or policy_b is None:
            st.error("One of the selected policies could not be loaded.")
            return

        if (
            policy_a.customer_id is not None
            and policy_b.customer_id is not None
            and policy_a.customer_id != policy_b.customer_id
        ):
            st.warning(
                "⚠️ These policies belong to different customers. Comparing "
                "across customers is allowed but is rarely what you want — "
                "make sure this is intentional."
            )

        try:
            result = ComparisonService(session).compare(policy_a, policy_b)

            st.divider()
            _render_kpi_strip(result)
            st.divider()
            _render_scalar_table(result)
            st.divider()
            _render_collection_details(result)
        except Exception as exc:
            logger.exception(
                "Compare page failed for policies %s/%s", pid_a, pid_b
            )
            st.error(
                f"Could not compute comparison: {exc}. "
                "Try refreshing the page — if it persists, check the app log."
            )
    finally:
        session.close()
