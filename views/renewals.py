"""
Renewals page — broker-facing view of policies expiring soon.

Read-only in this commit. The next commit wires per-row actions
(generate email draft, mark-as-contacted).

Layout:
- KPI bar (urgent count / total in window / premium at risk / contacted
  this week).
- One expander per urgency bucket: ⚪ Overdue, 🔴 Urgent (0–14d),
  🟡 Warning (15–30d), 🔵 Watch (31–60d).
- Each expander holds a sortable dataframe of policies in that bucket.

Data comes from `PolicyService.get_renewal_buckets()` (bucket placement)
and `NotificationService.count_in_window()` (the "contacted this week"
KPI). No SQL lives in this file.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd
import streamlit as st

from core.database import Policy, get_session
from core.notification_service import NotificationService
from core.services import PolicyService


# ---------------------------------------------------------------------------
# Small helpers (kept local — pure functions used only by this view).
# ---------------------------------------------------------------------------


def _parse_premium(value) -> float:
    """Best-effort float coercion for the 'premium at risk' KPI.

    Returns 0.0 for anything we can't parse so a malformed value
    doesn't poison the sum across many policies."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace("$", "").replace(",", "").strip()
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


def _premium_at_risk(policies: Iterable[Policy]) -> float:
    return sum(_parse_premium(p.premium) for p in policies)


def _policies_to_dataframe(policies: list[Policy]) -> pd.DataFrame:
    """Compact display shape: one row per policy with the columns brokers
    care about. Days-left is the sort anchor."""
    today = date.today()
    rows = []
    for p in policies:
        days_left = (
            (p.expiration_date - today).days if p.expiration_date else None
        )
        rows.append(
            {
                "Customer": p.insured_name or "(no name)",
                "Carrier": p.carrier_name or "—",
                "Policy #": p.policy_number or "—",
                "Type": p.policy_type or "—",
                "Premium": p.premium or "—",
                "Expires": p.expiration_date,
                "Days left": days_left,
            }
        )
    return pd.DataFrame(rows)


def _render_bucket(
    policies: list[Policy],
    title: str,
    hint: str,
    *,
    expanded: bool = True,
) -> None:
    """One expander section for a bucket. Skips rendering when empty so
    the page doesn't show four bare expanders on an idle account."""
    if not policies:
        return
    label = f"{title} — {len(policies)} {'policy' if len(policies) == 1 else 'policies'}"
    with st.expander(label, expanded=expanded):
        st.caption(hint)
        df = _policies_to_dataframe(policies)
        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config={
                "Expires": st.column_config.DateColumn(format="MMM DD, YYYY"),
                "Days left": st.column_config.NumberColumn(format="%d"),
            },
        )


# ---------------------------------------------------------------------------
# Page entry point.
# ---------------------------------------------------------------------------


def page_renewals() -> None:
    st.title("🔔 Renewals")
    st.caption(
        "Policies expiring soon, grouped by urgency. Use this view to plan "
        "your renewal outreach for the next two months."
    )

    session = get_session(st.session_state.db_engine)
    try:
        policy_service = PolicyService(session)
        notif_service = NotificationService(session)

        buckets = policy_service.get_renewal_buckets()
        overdue = buckets["overdue"]
        urgent = buckets["urgent"]
        warning = buckets["warning"]
        watch = buckets["watch"]

        total_in_window = len(overdue) + len(urgent) + len(warning) + len(watch)
        attention_now = len(overdue) + len(urgent)
        premium_at_risk = _premium_at_risk(overdue + urgent)

        week_ago = datetime.utcnow() - timedelta(days=7)
        contacted_this_week = notif_service.count_in_window(week_ago, datetime.utcnow())

        k1, k2, k3, k4 = st.columns(4)
        k1.metric(
            "Needs attention now",
            attention_now,
            help="Overdue policies plus those expiring in the next 14 days.",
        )
        k2.metric(
            "In 60-day window",
            total_in_window,
            help="All policies grouped on this page.",
        )
        k3.metric(
            "Premium at risk",
            f"${premium_at_risk:,.0f}",
            help="Sum of premium across overdue + urgent policies. "
            "Non-numeric premium values are skipped.",
        )
        k4.metric(
            "Contacted this week",
            contacted_this_week,
            help="Renewal-related notification log rows in the last 7 days.",
        )

        st.divider()

        if total_in_window == 0:
            st.success(
                "✅ No policies expiring in the next 60 days. Check back in a "
                "few weeks — or extract a new policy from **Process Policies**."
            )
            return

        _render_bucket(
            overdue,
            "⚪ Overdue",
            "These policies have already expired. If a backdated renewal "
            "is still possible, prioritize these first.",
        )
        _render_bucket(
            urgent,
            "🔴 Urgent (0–14 days)",
            "Contact these customers today. After 14 days a policy is "
            "uncomfortably close to expiring without coverage.",
        )
        _render_bucket(
            warning,
            "🟡 Warning (15–30 days)",
            "Plan outreach over the next week or two.",
            expanded=False,
        )
        _render_bucket(
            watch,
            "🔵 Watch (31–60 days)",
            "On your radar. Worth a heads-up email but not yet urgent.",
            expanded=False,
        )
    finally:
        session.close()
