import streamlit as st
import pandas as pd
from core.services import PolicyService, UsageService
from core.database import get_session
from views.edit_dialog import edit_policy_dialog
from core.constants import (
    DEFAULT_DAILY_BUDGET,
    APP_DISPLAY_NAME,
    APP_DISPLAY_TAGLINE,
    POLICY_SEARCH_PAGE_LIMIT,
)
from datetime import date

def page_dashboard():
    session = get_session(st.session_state.db_engine)
    service = PolicyService(session)
    usage_service = UsageService(session)
    
    try:
        total_policies, total_vehicles, total_premium = service.get_dashboard_metrics()
        daily_spend = usage_service.get_daily_usage()
        budget_limit = DEFAULT_DAILY_BUDGET
        
        today = date.today()
        hour = pd.Timestamp.now().hour
        greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
        
        st.markdown(f"""
        <div style="background: linear-gradient(90deg, #005AA9 0%, #003366 100%); padding: 30px; border-radius: 15px; margin-bottom: 25px; color: white;">
            <div style="margin:0; font-size: 1.8rem; font-weight: 700; color: white !important;">{APP_DISPLAY_NAME}</div>
            <p style="margin:5px 0 0 0; opacity: 0.85; font-size: 0.95rem;">{APP_DISPLAY_TAGLINE}</p>
            <p style="margin:10px 0 0 0; opacity: 0.8;">{greeting} — Overview for {today.strftime('%A, %B %d, %Y')}.</p>
        </div>
        """, unsafe_allow_html=True)

        m_col1, m_col2, m_col3 = st.columns(3)
        
        with m_col1:
            st.metric("Total Policies", total_policies)
        with m_col2:
            st.metric("Total Vehicles", total_vehicles)
        with m_col3:
            st.metric("Total Premium", f"${total_premium:,.2f}")

        expiring_30 = service.get_expiring_policies(days=30)
        expiring_60 = service.get_expiring_policies(days=60)
        
        # Only show policies in the 31-60 day window for the second bucket
        expiring_31_60 = [p for p in expiring_60 if p not in expiring_30]
        
        if expiring_30 or expiring_31_60:
            st.divider()
            st.subheader("🔔 Expiration Alerts")
            
            alert_col1, alert_col2 = st.columns(2)
            
            with alert_col1:
                if expiring_30:
                    st.error(f"⚠️ **{len(expiring_30)}** {'policy expires' if len(expiring_30) == 1 else 'policies expire'} within **30 days**")
                    with st.expander(f"View {len(expiring_30)} expiring policies", expanded=True):
                        for p in expiring_30:
                            days_left = (p.expiration_date - date.today()).days
                            st.markdown(f"""
                            <div style="border-left: 4px solid #dc3545; padding: 8px 12px; background: #fff5f5; margin-bottom: 8px; border-radius: 0 6px 6px 0;">
                                <div style="display:flex; justify-content:space-between;">
                                    <strong>{p.policy_number}</strong>
                                    <span style="color: #dc3545; font-weight: 600;">{days_left} days left</span>
                                </div>
                                <div style="font-size: 0.85rem; color: #666;">{p.insured_name} • {p.carrier_name}</div>
                                <div style="font-size: 0.8rem; color: #999;">Expires: {p.expiration_date.strftime('%b %d, %Y')}</div>
                            </div>
                            """, unsafe_allow_html=True)
                else:
                    st.success("✅ No policies expiring in the next 30 days")
            
            with alert_col2:
                if expiring_31_60:
                    st.warning(f"📋 **{len(expiring_31_60)}** {'policy expires' if len(expiring_31_60) == 1 else 'policies expire'} in **31-60 days**")
                    with st.expander(f"View {len(expiring_31_60)} upcoming expirations"):
                        for p in expiring_31_60:
                            days_left = (p.expiration_date - date.today()).days
                            st.markdown(f"""
                            <div style="border-left: 4px solid #ffc107; padding: 8px 12px; background: #fffbea; margin-bottom: 8px; border-radius: 0 6px 6px 0;">
                                <div style="display:flex; justify-content:space-between;">
                                    <strong>{p.policy_number}</strong>
                                    <span style="color: #856404; font-weight: 600;">{days_left} days left</span>
                                </div>
                                <div style="font-size: 0.85rem; color: #666;">{p.insured_name} • {p.carrier_name}</div>
                                <div style="font-size: 0.8rem; color: #999;">Expires: {p.expiration_date.strftime('%b %d, %Y')}</div>
                            </div>
                            """, unsafe_allow_html=True)
                else:
                    st.info("No policies expiring in the 31-60 day window")
        else:
            if total_policies > 0:
                st.divider()
                st.success("✅ **All policies are current** — no upcoming expirations in the next 60 days.")

        if total_policies > 0:
            st.divider()
            st.subheader("📊 Portfolio Analytics")
            
            chart_col1, chart_col2 = st.columns(2)
            
            with chart_col1:
                st.markdown("**Policies by Carrier**")
                carrier_data = service.get_carrier_distribution()
                if carrier_data:
                    carrier_df = pd.DataFrame(
                        list(carrier_data.items()), 
                        columns=["Carrier", "Policies"]
                    ).set_index("Carrier")
                    st.bar_chart(carrier_df, color="#005AA9")
                else:
                    st.caption("No carrier data available.")
            
            with chart_col2:
                st.markdown("**Expiration Timeline (Next 6 Months)**")
                timeline_data = service.get_expiration_timeline(months=6)
                if timeline_data and any(v > 0 for v in timeline_data.values()):
                    timeline_df = pd.DataFrame(
                        list(timeline_data.items()),
                        columns=["Month", "Expiring"]
                    ).set_index("Month")
                    st.bar_chart(timeline_df, color="#dc3545")
                else:
                    st.caption("No policies expiring in the next 6 months.")

        st.divider()

        c1, c2 = st.columns([1.5, 1])

        with c1:
            st.subheader("🕒 Recent Activity")
            if total_policies > 0:
                recent_policies = service.get_recent_policies(5)
                for p in recent_policies:
                    with st.container():
                        st.markdown(f"""
                        <div style="border-left: 4px solid #005AA9; padding: 10px 15px; background: #fdfdfd; margin-bottom: 10px; border-radius: 0 8px 8px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                                <div>
                                    <strong style="color: #333;">Extracted: {p.policy_number}</strong><br>
                                    <span style="font-size: 0.85rem; color: #666;">{p.insured_name} • {p.carrier_name}</span>
                                </div>
                                <span style="font-size: 0.75rem; color: #999;">{p.created_at.strftime('%H:%M %p') if p.created_at else 'Just now'}</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.info("No recent activity found.")

        with c2:
            st.subheader("🔍 Quick Lookup")
            if total_policies > 0:
                q_lookup = st.text_input(
                    "Search policy # or insured",
                    "",
                    key="dash_policy_lookup",
                    label_visibility="collapsed",
                    placeholder="Type to search…",
                )
                term_l = q_lookup.strip() or None
                policies_l = service.search_policies(term_l, limit=POLICY_SEARCH_PAGE_LIMIT)
                if not policies_l:
                    st.caption("No matches.")
                else:
                    policy_map = {f"{p.policy_number} | {p.insured_name}": p for p in policies_l}
                    selected_p_key = st.selectbox(
                        "Pick a policy",
                        options=list(policy_map.keys()),
                        label_visibility="collapsed",
                        key="dash_policy_pick",
                    )
                    if selected_p_key:
                        st.caption(f"Showing up to {POLICY_SEARCH_PAGE_LIMIT} newest matches.")
                        if st.button("Edit Policy", type="primary", width="stretch"):
                            edit_policy_dialog(policy_map[selected_p_key], service)
                        if st.button("Open in Create COI", width="stretch"):
                            st.session_state["nav_request"] = "Create COI"
                            st.session_state["coi_policy_id"] = policy_map[selected_p_key].id
                            st.rerun()
            else:
                st.info("Add a policy to enable lookup.")

    finally:
        session.close()
