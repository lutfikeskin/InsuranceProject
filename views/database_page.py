import streamlit as st
import pandas as pd
from services import PolicyService
from database import get_session
from exporter import create_excel_report

from views.edit_dialog import edit_policy_dialog

def page_database(api_key):
    st.title("🗃️ Policy Database")
    st.markdown("Search, view, and edit all previously extracted insurance data.")
    
    session = get_session(st.session_state.db_engine)
    service = PolicyService(session)
    
    try:
        policies = service.get_all_policies()
        if not policies:
            st.info("No records found in database.")
            return

        # Sidebar Search / Filter or Top Search
        search_query = st.text_input("Search by Policy # or Insured Name", "")
        
        # --- Chat with Data Feature ---
        with st.expander("💬 Chat with your Data (AI Search)", expanded=False):
            st.info("Ask complex questions like: 'Show me all policies with premium over $5000' or 'List all Mack trucks'.")
            user_question = st.text_input("Ask a question about your policies:", key="data_chat_input")
            
            if st.button("Ask AI", type="secondary"):
                if user_question:
                    # Get API Key passed from app loop
                    with st.spinner("Thinking..."):
                         results, debug_sql = service.ask_your_data(user_question, api_key)
                    
                    if results is not None:
                        st.success(f"Found {len(results)} results")
                        st.dataframe(pd.DataFrame(results), use_container_width=True)
                    else:
                        st.error(f"Could not answer: {debug_sql}")
        
        data_list = []
        export_data = []
        for p in policies:
            if search_query.lower() in p.policy_number.lower() or search_query.lower() in p.insured_name.lower():
                # Status Logic
                status = "✅ Eligible"
                liab_val = 0
                if p.liability_limit:
                    import re
                    clean_liab = re.sub(r'[^\d]', '', p.liability_limit)
                    if clean_liab: liab_val = float(clean_liab)
                
                cargo_val = 0
                if p.cargo_limit:
                    import re
                    clean_cargo = re.sub(r'[^\d]', '', p.cargo_limit)
                    if clean_cargo: cargo_val = float(clean_cargo)

                if liab_val < 1000000 or cargo_val < 100000:
                     status = "⚠️ Not Eligible for Expedite"

                data_list.append({
                    "ID": p.id, 
                    "Policy#": p.policy_number, 
                    "Carrier": p.carrier_name, 
                    "Insured": p.insured_name, 
                    "Effective": p.effective_date,
                    "Premium": p.premium,
                    "Liability": p.liability_limit,
                    "Cargo": p.cargo_limit,
                    "Status": status
                })
                
                # Reconstruct for exporter
                dict_data = {
                    "policy": {"carrier_name": p.carrier_name, "policy_number": p.policy_number, "effective_date": str(p.effective_date), "expiration_date": str(p.expiration_date), "account_type": p.account_type, "insured_name": p.insured_name, "business_name": p.business_name, "premium": p.premium, "state": p.state, "financial_responsibility_name": p.financial_responsibility_name, "liability_limit": p.liability_limit, "cargo_limit": p.cargo_limit, "has_full_collision": p.has_full_collision},
                    "vehicles": [{"year": v.year, "make": v.make, "model": v.model, "vin": v.vin, "gvw": v.gvw, "type": v.vehicle_type} for v in p.vehicles],
                    "coverages": [{"type": c.type, "limit_person": c.limit_per_person, "limit_accident": c.limit_per_accident, "deductible": c.deductible} for c in p.coverages],
                    "drivers": [{"full_name": d.full_name, "license_number": d.license_number, "is_excluded": d.is_excluded} for d in p.drivers]
                }
                export_data.append(dict_data)

        if data_list:
            st.dataframe(pd.DataFrame(data_list), use_container_width=True, hide_index=True)
            
            c1, c2, c3 = st.columns(3)
            with c1:
                excel_all = create_excel_report(export_data)
                st.download_button("📥 Export to Excel", data=excel_all, file_name="insurance_database.xlsx", use_container_width=True)
            with c2:
                with open("insurance_data.db", "rb") as f:
                    st.download_button("💾 Database Backup", data=f.read(), file_name="insurance_data.db", use_container_width=True)
            with c3:
                # Add Edit Trigger here
                policy_map = {f"{p.policy_number} | {p.insured_name}": p for p in policies}
                target_p = st.selectbox("Select Policy to Edit", options=[""] + list(policy_map.keys()), key="db_edit_sel")
                if target_p:
                    if st.button("Edit Selected", type="primary", use_container_width=True):
                        edit_policy_dialog(policy_map[target_p], service)

        else:
            st.warning("No policies match your search.")

        st.divider()
        with st.expander("🗑️ Delete Policies", expanded=False):
            st.warning("Warning: Deletion is permanent.")
            policy_map_del = {f"{p.policy_number} | {p.insured_name}": p.id for p in policies}
            selected_to_delete = st.multiselect("Select Policies to Delete", options=list(policy_map_del.keys()))
            
            if selected_to_delete:
                if st.button(f"Delete {len(selected_to_delete)} Selected", type="primary"):
                    for k in selected_to_delete:
                        pol = service.get_policy_by_id(policy_map_del[k])
                        if pol:
                            service.delete_policy(pol)
                    st.success("Deleted!")
                    st.rerun()

    finally:
        session.close()
