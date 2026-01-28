import streamlit as st
import pandas as pd
from core.services import PolicyService
from core.database import get_session
from utils.exporter import create_excel_report

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
                        res_df = pd.DataFrame(results)
                        
                        # Format columns to Title Case (e.g., insured_name -> Insured Name)
                        res_df.columns = [col.replace('_', ' ').title() for col in res_df.columns]
                        
                        from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
                        gb_res = GridOptionsBuilder.from_dataframe(res_df)
                        gb_res.configure_default_column(sortable=True, filterable=True, resizable=True)
                        gb_res.configure_pagination(paginationAutoPageSize=True)
                        res_grid_options = gb_res.build()
                        
                        AgGrid(
                            res_df,
                            gridOptions=res_grid_options,
                            height=300,
                            theme='streamlit',
                            fit_columns_on_grid_load=True,
                            key="ai_search_results_grid"
                        )
                    else:
                        st.error(f"Could not answer: {debug_sql}")
        
        data_list = []
        export_data = []
        for p in policies:
            if search_query.lower() in p.policy_number.lower() or search_query.lower() in p.insured_name.lower():
                # Expedite Eligibility Logic
                eligibility_status = "✅ Eligible for Expedite"
                def parse_limit(val_str):
                    if not val_str: return 0.0
                    s = str(val_str).lower().strip()
                    multiplier = 1.0
                    if 'k' in s: multiplier = 1000.0
                    elif 'm' in s: multiplier = 1000000.0
                    
                    import re
                    # Keep digits and decimal points
                    clean = re.sub(r'[^\d.]', '', s)
                    try:
                        return float(clean) * multiplier
                    except:
                        return 0.0

                liab_val = parse_limit(p.liability_limit)
                cargo_val = parse_limit(p.cargo_limit)

                if liab_val < 1000000 or cargo_val < 100000:
                     eligibility_status = "⚠️ Not Eligible for Expedite"

                # Aggregate Vehicle Types
                v_types = [v.vehicle_type for v in p.vehicles if v.vehicle_type]
                v_types_unique = sorted(list(set(v_types)))
                v_types_str = ", ".join(v_types_unique) if v_types_unique else "N/A"
                
                # Policy Status
                pol_status = p.status if p.status else "Active"

                data_list.append({
                    "ID": p.id,
                    "Status": pol_status,
                    "Policy#": p.policy_number, 
                    "Carrier": p.carrier_name, 
                    "NAIC": p.naic_number,
                    "Insured": p.insured_name,
                    "Business Name": p.business_name,
                    "Address": p.insured_address,
                    "City": p.insured_city,
                    "State": p.insured_state_code,
                    "Zip": p.insured_zip,
                    "Vehicles": len(p.vehicles),
                    "Drivers": len(p.drivers),
                    "Effective": p.effective_date.strftime("%Y-%m-%d") if p.effective_date else "N/A",
                    "Expiration": p.expiration_date.strftime("%Y-%m-%d") if p.expiration_date else "N/A",
                    "Premium": p.premium,
                    "Auto Liability": p.liability_limit,
                    "Cargo": p.cargo_limit,
                    "Cargo Ded": p.cargo_deductible,
                    "GL Limit": p.general_liability_limit,
                    "Has GL": "✅" if p.has_general_liability else "❌",
                    "Comp/Coll": "✅" if p.has_full_collision else "❌",
                    "Expedite": eligibility_status,
                    "Type": p.policy_type,
                    "Confidence": p.classification_confidence
                })
                
                # Reconstruct for exporter
                dict_data = {
                    "policy": {
                        "carrier_name": p.carrier_name, 
                        "naic_number": p.naic_number,
                        "policy_number": p.policy_number, 
                        "effective_date": str(p.effective_date), 
                        "expiration_date": str(p.expiration_date), 
                        "account_type": p.account_type, 
                        "policy_type": p.policy_type,
                        "status": pol_status,
                        "classification_confidence": p.classification_confidence,
                        "classification_signals": p.classification_signals,
                        "insured_name": p.insured_name, 
                        "business_name": p.business_name, 
                        "insured_address": p.insured_address,
                        "insured_city": p.insured_city,
                        "insured_state_code": p.insured_state_code,
                        "insured_zip": p.insured_zip,
                        "premium": p.premium, 
                        "state": p.state, 
                        "financial_responsibility_name": p.financial_responsibility_name, 
                        "liability_limit": p.liability_limit, 
                        "general_liability_limit": p.general_liability_limit,
                        "cargo_limit": p.cargo_limit, 
                        "cargo_deductible": p.cargo_deductible,
                        "has_full_collision": p.has_full_collision,
                        "has_general_liability": p.has_general_liability,
                        "has_auto_liability": p.has_auto_liability
                    },
                    "vehicles": [{"year": v.year, "make": v.make, "model": v.model, "vin": v.vin, "gvw": v.gvw, "type": v.vehicle_type, "chassis": v.chassis, "body": v.body} for v in p.vehicles],
                    "coverages": [
                        {
                            "type": c.type, 
                            "coverage_code": c.coverage_code,
                            "family": c.family,
                            "per_person": c.per_person,
                            "per_accident": c.per_accident,
                            "per_occurrence": c.per_occurrence,
                            "combined_single_limit": c.combined_single_limit,
                            "aggregate": c.aggregate,
                            "limit_person": c.limit_per_person, 
                            "limit_accident": c.limit_per_accident, 
                            "deductible": c.deductible
                        } for c in p.coverages
                    ],
                    "drivers": [{"full_name": d.full_name, "license_number": d.license_number, "is_excluded": d.is_excluded} for d in p.drivers],
                    "additional_interests": [{"name": a.name, "address": a.address, "type": a.interest_type} for a in p.additional_interests]
                }
                export_data.append(dict_data)

        if data_list:
            # st.dataframe(pd.DataFrame(data_list), width=1000, hide_index=True)
            from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode
            
            st.markdown("### 📋 Policy Records")
            
            df = pd.DataFrame(data_list) # Restored
            
            # --- Column Visibility Control ---
            all_cols = list(df.columns)
            
            # Start with a strict default set
            strict_defaults = [
                "Status", "Policy#", "Carrier", "Insured", 
                "Effective", "Premium", "Auto Liability", "Cargo", 
                "Vehicles", "Drivers"
            ]
            # Filter to ensure they exist in dataframe
            default_cols = [c for c in strict_defaults if c in all_cols]

            cols_to_show = st.multiselect("Select Columns to Display", all_cols, default=default_cols)
            
            if not cols_to_show:
                st.warning("Please select at least one column.")
                return

            df_visible = df[cols_to_show]
            
            gb = GridOptionsBuilder.from_dataframe(df_visible)
            gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
            gb.configure_side_bar() # Add sidebar for columns
            gb.configure_default_column(groupable=True, valueFormatter="x.toLocaleString()", filterable=True, sortable=True, resizable=True)
            gb.configure_selection('single', use_checkbox=True)
            gridOptions = gb.build()
            
            st.markdown("### 📋 Policy Records")
            grid_response = AgGrid(
                df, 
                gridOptions=gridOptions,
                update_mode=GridUpdateMode.SELECTION_CHANGED, 
                data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
                fit_columns_on_grid_load=False,
                height=500,
                width='100%',
                theme='streamlit'
            )
            
            selected = grid_response['selected_rows']
            
            c1, c2, c3 = st.columns(3)
            with c1:
                excel_all = create_excel_report(export_data)
                st.download_button("📥 Export to Excel", data=excel_all, file_name="insurance_database.xlsx", use_container_width=True)
            with c2:
                with open("insurance_data.db", "rb") as f:
                    st.download_button("💾 Database Backup", data=f.read(), file_name="insurance_data.db", use_container_width=True)
            with c3:
                # Add Edit Trigger via Grid Selection
                # Robust selection check (handle DataFrame vs List)
                has_selection = False
                if selected is not None:
                    if isinstance(selected, pd.DataFrame):
                        if not selected.empty:
                            has_selection = True
                    elif isinstance(selected, list) and len(selected) > 0:
                        has_selection = True

                if has_selection:
                     # Get the first row safely
                     if isinstance(selected, pd.DataFrame):
                         sel_row = selected.iloc[0]
                     else:
                         sel_row = selected[0]

                     # selected is a list of dicts or DataFrame row. We find the policy by ID
                     # If DataFrame row, accessing by key works like dict usually, or explicitly
                     p_id = sel_row['ID']
                     
                     # Find policy object
                     target_pol = next((p for p in policies if p.id == p_id), None)
                     
                     if target_pol:
                         if st.button(f"✏️ Edit Policy {target_pol.policy_number}", type="primary", use_container_width=True):
                             edit_policy_dialog(target_pol, service)
                else:
                    st.info("Select a row above to edit.")

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
