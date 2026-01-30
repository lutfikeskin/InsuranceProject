import streamlit as st
import pandas as pd
from core.services import PolicyService, UsageService
from core.database import get_session
from st_aggrid import AgGrid, GridOptionsBuilder
from views.edit_dialog import edit_policy_dialog
from core.constants import DEFAULT_DAILY_BUDGET

def page_dashboard():
    session = get_session(st.session_state.db_engine)
    service = PolicyService(session)
    usage_service = UsageService(session)
    
    try:
        total_policies, total_vehicles, total_premium = service.get_dashboard_metrics()
        daily_spend = usage_service.get_daily_usage()
        budget_limit = DEFAULT_DAILY_BUDGET
        
        # --- COMMAND CENTER HEADER ---
        st.markdown(f"""
        <div style="background: linear-gradient(90deg, #005AA9 0%, #003366 100%); padding: 30px; border-radius: 15px; margin-bottom: 25px; color: white;">
            <div style="margin:0; font-size: 1.8rem; font-weight: 700; color: white !important;">🚀 Project Command Center</div>
            <p style="margin:5px 0 0 0; opacity: 0.8;">Welcome back. Here is your platform overview for today.</p>
        </div>
        """, unsafe_allow_html=True)

        # --- METRICS GRID ---
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        
        with m_col1:
            st.metric("Total Policies", total_policies)
        with m_col2:
            st.metric("Total Vehicles", total_vehicles)
        with m_col3:
            st.metric("Total Premium", f"${total_premium:,.2f}")
        with m_col4:
            # Budget awareness
            progress = min(daily_spend / budget_limit, 1.0)
            status_color = "#ff4b4b" if progress > 0.8 else "#28a745"
            st.metric("Daily AI Spend", f"${daily_spend:.4f}", delta=f"{progress*100:.1f}% of budget", delta_color="inverse")

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
                policies = service.get_all_policies()
                policy_map = {f"{p.policy_number} | {p.insured_name}": p for p in policies}
                selected_p_key = st.selectbox("Find policy", options=[""] + list(policy_map.keys()), label_visibility="collapsed")
                
                if selected_p_key:
                    st.success(f"Found: {selected_p_key}")
                    if st.button("Edit Policy", type="primary", width='stretch'):
                        edit_policy_dialog(policy_map[selected_p_key], service)
            else:
                st.info("Add a policy to enable lookup.")

    finally:
        session.close()
