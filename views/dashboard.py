import streamlit as st
import pandas as pd
from services import PolicyService
from database import get_session

from views.edit_dialog import edit_policy_dialog

def page_dashboard():
    st.title("📊 Dashboard")
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
        
        # Quick Edit Section
        if total_policies > 0:
            with st.expander("🔍 Quick Search & Edit Policy", expanded=True):
                policies = service.get_all_policies()
                policy_map = {f"{p.policy_number} | {p.insured_name}": p for p in policies}
                selected_p_key = st.selectbox("Select a policy to edit", options=[""] + list(policy_map.keys()))
                
                if selected_p_key:
                    if st.button("Edit Selected Policy", type="primary"):
                        edit_policy_dialog(policy_map[selected_p_key], service)

        st.subheader("Recent Policy Activity")
        if total_policies > 0:
            recent_policies = service.get_recent_policies(10)
            data = []
            for p in recent_policies:
                 # Eligibility Check
                 status = "✅ Eligible"
                 
                 # Parse Liability
                 liab_val = 0
                 if p.liability_limit:
                    import re
                    clean_liab = re.sub(r'[^\d]', '', p.liability_limit)
                    if clean_liab: liab_val = float(clean_liab)
                 
                 # Parse Cargo
                 cargo_val = 0
                 if p.cargo_limit:
                    import re
                    clean_cargo = re.sub(r'[^\d]', '', p.cargo_limit)
                    if clean_cargo: cargo_val = float(clean_cargo)

                 if liab_val < 1000000 or cargo_val < 100000:
                     status = "⚠️ Not Eligible for Expedite"

                 data.append({
                     "Policy #": p.policy_number,
                     "Insured": p.insured_name,
                     "Carrier": p.carrier_name,
                     "Effective": p.effective_date,
                     "Premium": p.premium,
                     "Vehicles": len(p.vehicles),
                     "Liability": p.liability_limit,
                     "Cargo": p.cargo_limit,
                     "Status": status
                 })
            st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
        else:
            st.info("No policies extracted yet. Start by uploading files in the 'Process Policies' tab.")

    finally:
        session.close()
