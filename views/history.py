import streamlit as st
import pandas as pd
from services import PolicyService
from database import get_session
from exporter import create_excel_report

def page_history():
    st.title("🗄️ Database History")
    st.markdown("View and export all previously extracted insurance data.")
    
    session = get_session(st.session_state.db_engine)
    service = PolicyService(session)
    
    try:
        policies = service.get_all_policies()
        if not policies:
            st.info("No records found in database.")
            return

        data_list = []
        export_data = []
        for p in policies:
            data_list.append({"ID": p.id, "Policy#": p.policy_number, "Carrier": p.carrier_name, "Insured": p.insured_name, "Effective": p.effective_date})
            
            # Reconstruct for exporter
            # Logic kept similar to original for compatibility with exporter.py
            dict_data = {
                "policy": {"carrier_name": p.carrier_name, "policy_number": p.policy_number, "effective_date": str(p.effective_date), "expiration_date": str(p.expiration_date), "account_type": p.account_type, "insured_name": p.insured_name, "business_name": p.business_name, "premium": p.premium, "state": p.state, "financial_responsibility_name": p.financial_responsibility_name, "liability_limit": p.liability_limit, "cargo_limit": p.cargo_limit, "has_full_collision": p.has_full_collision},
                "vehicles": [{"year": v.year, "make": v.make, "model": v.model, "vin": v.vin, "gvw": v.gvw, "type": v.vehicle_type} for v in p.vehicles],
                "coverages": [{"type": c.type, "limit_person": c.limit_per_person, "limit_accident": c.limit_per_accident, "deductible": c.deductible} for c in p.coverages],
                "drivers": [{"full_name": d.full_name, "license_number": d.license_number, "is_excluded": d.is_excluded} for d in p.drivers]
            }
            export_data.append(dict_data)

        st.dataframe(pd.DataFrame(data_list), use_container_width=True)
        
        c1, c2 = st.columns(2)
        with c1:
            excel_all = create_excel_report(export_data)
            st.download_button("📥 Export Full History to Excel", data=excel_all, file_name="full_insurance_history.xlsx", use_container_width=True)
        with c2:
                with open("insurance_data.db", "rb") as f:
                    st.download_button("💾 Backup SQLite Database", data=f.read(), file_name="insurance_data.db", use_container_width=True)

        st.divider()
        with st.expander("🗑️ Manage Data (Delete Policies)", expanded=False):
            st.warning("Warning: Deleting a policy will permanently remove it and all associated vehicles, drivers, and coverages.")
            
            # Create a map for the multiselect
            policy_map = {f"{p.policy_number} | {p.insured_name}": p.id for p in policies}
            
            selected_to_delete = st.multiselect("Select Policies to Permanently Delete", options=list(policy_map.keys()))
            
            if selected_to_delete:
                if st.button(f"Delete {len(selected_to_delete)} Selected Polic(ies)", type="primary"):
                    ids_to_delete = [policy_map[k] for k in selected_to_delete]
                    
                    try:
                        processed_count = 0
                        for pid in ids_to_delete:
                            # We can improve service to delete by IDs batch, but this is fine
                            pol = service.get_policy_by_id(pid)
                            if pol:
                                service.delete_policy(pol)
                                processed_count += 1
                        
                        st.success(f"Policies deleted successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error during deletion: {e}")

    finally:
        session.close()
