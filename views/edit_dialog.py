import streamlit as st
from core.services import PolicyService

@st.dialog("✏️ Edit Policy Details")
def edit_policy_dialog(policy, service: PolicyService):
    st.write(f"Editing Policy: **{policy.policy_number}**")
    
    with st.form("edit_policy_form"):
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
            new_type = st.selectbox("Policy Type", options=["personal_auto", "commercial_auto", "general_liability", "bop", "commercial_package", "umbrella", "motor_truck_cargo", "unknown"], index=["personal_auto", "commercial_auto", "general_liability", "bop", "commercial_package", "umbrella", "motor_truck_cargo", "unknown"].index(policy.policy_type) if policy.policy_type in ["personal_auto", "commercial_auto", "general_liability", "bop", "commercial_package", "umbrella", "motor_truck_cargo", "unknown"] else 7)
            new_conf = st.selectbox("Confidence", options=["high", "medium", "low"], index=["high", "medium", "low"].index(policy.classification_confidence) if policy.classification_confidence in ["high", "medium", "low"] else 2)
        
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
        st.warning("⚠️ **Warning**: Saving these changes will permanently overwrite the current record in the database.")
        
        submitted = st.form_submit_button("Confirm & Save Changes", use_container_width=True, type="primary")
        
        if submitted:
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
                "classification_confidence": new_conf
            }
            
            if service.update_policy(policy, updated_data):
                st.success("Policy updated successfully!")
                st.rerun()
