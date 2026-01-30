import streamlit as st
from core.services import PolicyService
import pandas as pd
from core.constants import POLICY_TYPES, STATUS_OPTIONS, CONFIDENCE_OPTIONS, VEHICLE_TYPES, INTEREST_TYPES, VIN_REGEX

@st.dialog("✏️ Edit Policy Details", width="large")
def edit_policy_dialog(policy, service: PolicyService):
    st.write(f"Editing Policy: **{policy.policy_number}**")
    
    # Define Tabs
    tab_details, tab_vehs, tab_drvs, tab_ais, tab_history = st.tabs(["📝 Details", "🚙 Vehicles", "👤 Drivers", "🏢 Add'l Interests", "📜 History"])
    
    # --- Tab 1: Details (Scalar Fields) ---
    with tab_details:
        with st.form("edit_details_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                new_insured = st.text_input("Insured Name", value=policy.insured_name)
                new_biz = st.text_input("Business Name", value=policy.business_name if policy.business_name else "")
                new_carrier = st.text_input("Carrier Name", value=policy.carrier_name)
                new_naic = st.text_input("NAIC #", value=policy.naic_number if policy.naic_number else "")
                new_premium = st.text_input("Premium", value=policy.premium)
                new_fin_resp = st.text_input("Fin. Resp. Name", value=policy.financial_responsibility_name if policy.financial_responsibility_name else "")
                
                st.divider()
                st.write("📋 Classification")
                curr_type = policy.policy_type if policy.policy_type in POLICY_TYPES else "unknown"
                new_type = st.selectbox("Policy Type", options=POLICY_TYPES, index=POLICY_TYPES.index(curr_type))
                
                curr_conf = policy.classification_confidence if policy.classification_confidence in CONFIDENCE_OPTIONS else "low"
                new_conf = st.selectbox("Confidence", options=CONFIDENCE_OPTIONS, index=CONFIDENCE_OPTIONS.index(curr_conf))
                
                # Status Field
                curr_status = policy.status if policy.status in STATUS_OPTIONS else "Active"
                new_status = st.selectbox("Status", options=STATUS_OPTIONS, index=STATUS_OPTIONS.index(curr_status))

            with col2:
                new_eff = st.date_input("Effective Date", value=policy.effective_date)
                new_exp = st.date_input("Expiration Date", value=policy.expiration_date)
                new_limit = st.text_input("Auto Liability Limit", value=policy.liability_limit)
                new_gl_limit = st.text_input("General Liability Limit", value=policy.general_liability_limit if policy.general_liability_limit else "")
                new_cargo = st.text_input("Cargo Limit", value=policy.cargo_limit if policy.cargo_limit else "")
                new_cargo_ded = st.text_input("Cargo Deductible", value=policy.cargo_deductible if policy.cargo_deductible else "")

            st.divider()
            st.write("📍 Address Information")
            new_addr = st.text_input("Address", value=policy.insured_address if policy.insured_address else "")
            c1, c2, c3 = st.columns([2, 1, 1])
            new_city = c1.text_input("City", value=policy.insured_city if policy.insured_city else "")
            new_state = c2.text_input("State Code", value=policy.insured_state_code if policy.insured_state_code else "")
            new_zip = c3.text_input("Zip", value=policy.insured_zip if policy.insured_zip else "")

            st.divider()
            st.write("⚙️ Coverage Flags")
            cf1, cf2, cf3 = st.columns(3)
            new_coll = cf1.checkbox("Full Collision", value=policy.has_full_collision)
            new_gl = cf2.checkbox("General Liability", value=policy.has_general_liability)
            new_auto = cf3.checkbox("Auto Liability", value=policy.has_auto_liability)

            st.markdown("<br>", unsafe_allow_html=True)
            st.warning("⚠️ **Warning**: Saving details only updates the fields above. Vehicles/Drivers are not affected.")
            
            submitted_details = st.form_submit_button("💾 Save Details", width='stretch', type="primary")
            
            if submitted_details:
                updated_data = {
                    "insured_name": new_insured,
                    "business_name": new_biz,
                    "carrier_name": new_carrier,
                    "naic_number": new_naic,
                    "premium": new_premium,
                    "effective_date": new_eff,
                    "expiration_date": new_exp,
                    "financial_responsibility_name": new_fin_resp,
                    "liability_limit": new_limit,
                    "general_liability_limit": new_gl_limit,
                    "cargo_limit": new_cargo,
                    "cargo_deductible": new_cargo_ded,
                    "insured_address": new_addr,
                    "insured_city": new_city,
                    "insured_state_code": new_state,
                    "insured_zip": new_zip,
                    "has_full_collision": new_coll,
                    "has_general_liability": new_gl,
                    "has_auto_liability": new_auto,
                    "policy_type": new_type,
                    "classification_confidence": new_conf,
                    "status": new_status
                }
                
                # Pass directly (wrapped implicitly by logic or explicit wrap check in logic)
                # Logic: if 'vehicles' not in dict, history_svc ignores collection change. Correct.
                
                result = service.update_policy(policy, updated_data)
                
                if isinstance(result, tuple): success, msg = result
                else: success, msg = result, "Updated."
                
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
                    
    # --- Tab 2: Vehicles ---
    with tab_vehs:
        st.subheader("Manage Vehicles")
        # Prepare Data
        v_data = [{"year": v.year, "make": v.make, "model": v.model, "vin": v.vin, "type": v.vehicle_type, "gvw": v.gvw, "chassis": v.chassis, "body": v.body} for v in policy.vehicles]
        v_df = pd.DataFrame(v_data)
        if v_df.empty: v_df = pd.DataFrame(columns=["year", "make", "model", "vin", "type", "gvw", "chassis", "body"])
        
        with st.form("edit_fleet_form"):
             
             edited_v = st.data_editor(
                 v_df, 
                 num_rows="dynamic", 
                 width='stretch', 
                 key="fleet_editor",
                 column_config={
                     "year": st.column_config.NumberColumn("Year", min_value=1900, max_value=2030, format="%d"),
                     "make": st.column_config.TextColumn("Make", required=True),
                     "model": st.column_config.TextColumn("Model"),
                     "vin": st.column_config.TextColumn("VIN", max_chars=17, validate=VIN_REGEX),
                     "type": st.column_config.SelectboxColumn("Type", options=VEHICLE_TYPES),
                     "gvw": st.column_config.NumberColumn("GVW (lbs)", format="%d"),
                     "chassis": st.column_config.TextColumn("Chassis"),
                     "body": st.column_config.TextColumn("Body")
                 }
             )
             
             save_fleet = st.form_submit_button("💾 Save Fleet Changes", type="primary")
             
             if save_fleet:
                 new_vehs_list = []
                 for _, row in edited_v.iterrows():
                     if pd.isna(row.get('vin')) and pd.isna(row.get('make')): continue
                     new_vehs_list.append({
                         "year": row.get('year'), "make": row.get('make'), "model": row.get('model'),
                         "vin": row.get('vin'), "type": row.get('type'), "gvw": row.get('gvw'),
                         "chassis": row.get('chassis'), "body": row.get('body')
                     })
                 
                 # Send Payload
                 payload = {"vehicles": new_vehs_list}
                 result = service.update_policy(policy, payload)
                 if isinstance(result, tuple): success, msg = result
                 else: success, msg = result, "Updated."
                 if success:
                     st.success(msg)
                     st.rerun()
                 else: st.error(msg)

    # --- Tab 3: Drivers ---
    with tab_drvs:
        st.subheader("Manage Drivers")
        d_data = [{"full_name": d.full_name, "license_number": d.license_number, "is_excluded": d.is_excluded} for d in policy.drivers]
        d_df = pd.DataFrame(d_data)
        if d_df.empty: d_df = pd.DataFrame(columns=["full_name", "license_number", "is_excluded"])
        
        with st.form("edit_drivers_form"):
             edited_d = st.data_editor(
                 d_df, 
                 num_rows="dynamic", 
                 width='stretch', 
                 key="driver_editor",
                 column_config={
                     "full_name": st.column_config.TextColumn("Driver Name", required=True),
                     "license_number": st.column_config.TextColumn("License #"),
                     "is_excluded": st.column_config.CheckboxColumn("Excluded?", default=False)
                 }
             )
             save_drivers = st.form_submit_button("💾 Save Drivers", type="primary")
             if save_drivers:
                  new_d_list = []
                  for _, row in edited_d.iterrows():
                      if pd.isna(row.get('full_name')): continue
                      new_d_list.append({
                          "full_name": row.get('full_name'),
                          "license_number": row.get('license_number'),
                          "is_excluded": row.get('is_excluded')
                      })
                  
                  payload = {"drivers": new_d_list}
                  result = service.update_policy(policy, payload)
                  if isinstance(result, tuple): success, msg = result
                  else: success, msg = result, "Updated."
                  if success:
                     st.success(msg)
                     st.rerun()
                  else: st.error(msg)

    # --- Tab 4: Additional Interests ---
    with tab_ais:
        st.subheader("Manage Additional Interests")
        ai_data = [{"name": a.name, "address": a.address, "interest_type": a.interest_type} for a in policy.additional_interests]
        ai_df = pd.DataFrame(ai_data)
        if ai_df.empty: ai_df = pd.DataFrame(columns=["name", "address", "interest_type"])
        
        with st.form("edit_ais_form"):
             edited_ai = st.data_editor(
                 ai_df, 
                 num_rows="dynamic", 
                 width='stretch', 
                 key="ai_editor",
                 column_config={
                     "name": st.column_config.TextColumn("Entity Name", required=True),
                     "address": st.column_config.TextColumn("Address"),
                     "interest_type": st.column_config.SelectboxColumn(
                         "Interest Type", 
                         options=INTEREST_TYPES
                     )
                 }
             )
             
             save_ais = st.form_submit_button("💾 Save Interests", type="primary")
             
             if save_ais:
                 new_ai_list = []
                 for _, row in edited_ai.iterrows():
                     if pd.isna(row.get('name')): continue
                     new_ai_list.append({
                         "name": row.get('name'), "address": row.get('address'), "interest_type": row.get('interest_type')
                     })
                 
                 payload = {"additional_interests": new_ai_list}
                 result = service.update_policy(policy, payload)
                 if isinstance(result, tuple): success, msg = result
                 else: success, msg = result, "Updated."
                 if success:
                     st.success(msg)
                     st.rerun()
                 else: st.error(msg)

    # --- Tab 5: History ---
    with tab_history:
        st.subheader("Changes Timeline")
        if not policy.history:
             st.info("No history recorded for this policy.")
        else:
             sorted_history = sorted(policy.history, key=lambda x: x.timestamp, reverse=True)
             for h in sorted_history:
                 ts = h.timestamp.strftime("%Y-%m-%d %H:%M:%S") if h.timestamp else "N/A"
                 with st.expander(f"Version {h.policy_version} | {ts} | {h.event_type}", expanded=False):
                     st.caption(f"Source: {h.source}")
                     if h.changes:
                         st.markdown("##### Fields Modified")
                         st.dataframe(pd.DataFrame(h.changes), width=700, hide_index=True)
                     else:
                         st.write("No specific field changes logged.")
