import streamlit as st
import pandas as pd
from services import PolicyService
from database import get_session

def page_dashboard():
    st.title("Dashboard")
    session = get_session(st.session_state.db_engine)
    service = PolicyService(session)
    
    try:
        total_policies, total_vehicles, total_premium = service.get_dashboard_metrics()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Policies", total_policies)
        with col2:
            st.metric("Total Vehicles", total_vehicles)
        with col3:
            st.metric("Total Premium", f"${total_premium:,.2f}")
        
        st.divider()
        
        st.subheader("Recent Policy Activity")
        if total_policies > 0:
            policies = service.get_recent_policies(10)
            data = []
            for p in policies:
                 data.append({
                     "Policy #": p.policy_number,
                     "Insured": p.insured_name,
                     "Carrier": p.carrier_name,
                     "Effective": p.effective_date,
                     "Premium": p.premium,
                     "Vehicles": len(p.vehicles),
                     "Liability": p.liability_limit
                 })
            st.dataframe(pd.DataFrame(data), use_container_width=True)
        else:
            st.info("No policies extracted yet. Start by uploading files in the 'Process Policies' tab.")

    finally:
        session.close()
