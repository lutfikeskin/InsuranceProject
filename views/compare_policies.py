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
# Collection-diff placeholders (real content lands in the next commit)
# ---------------------------------------------------------------------------


def _render_collection_placeholders(result: ComparisonResult) -> None:
    st.markdown("##### Collection differences")
    st.caption(
        "Detailed vehicle / driver / coverage / additional-interest "
        "comparisons are coming in the next commit. The counts above the "
        "table already use this data."
    )
    s = result.summary
    placeholders = [
        ("🚗 Vehicles", s.n_vehicles_only_in_a, s.n_vehicles_only_in_b, len(result.vehicles.unchanged)),
        ("🧑 Drivers", s.n_drivers_only_in_a, s.n_drivers_only_in_b, len(result.drivers.unchanged)),
        ("🛡️ Coverages", s.n_coverages_only_in_a, s.n_coverages_only_in_b, len(result.coverages.unchanged)),
        ("📎 Additional Interests",
         len(result.additional_interests.only_in_a),
         len(result.additional_interests.only_in_b),
         len(result.additional_interests.unchanged)),
    ]
    for label, only_a, only_b, unchanged in placeholders:
        with st.expander(
            f"{label} — {only_a} only on A, {only_b} only on B, {unchanged} unchanged",
            expanded=False,
        ):
            st.caption("Detail tables coming in the next commit.")


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

        result = ComparisonService(session).compare(policy_a, policy_b)

        st.divider()
        _render_kpi_strip(result)
        st.divider()
        _render_scalar_table(result)
        st.divider()
        _render_collection_placeholders(result)
    finally:
        session.close()
