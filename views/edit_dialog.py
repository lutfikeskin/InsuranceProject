import streamlit as st
from services import PolicyService

@st.dialog("✏️ Edit Policy Details")
def edit_policy_dialog(policy, service: PolicyService):
    st.write(f"Editing Policy: **{policy.policy_number}**")
    
    with st.form("edit_policy_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            new_insured = st.text_input("Insured Name", value=policy.insured_name)
            new_carrier = st.text_input("Carrier Name", value=policy.carrier_name)
            new_premium = st.text_input("Premium", value=policy.premium)
        
        with col2:
            new_eff = st.date_input("Effective Date", value=policy.effective_date)
            new_exp = st.date_input("Expiration Date", value=policy.expiration_date)
            new_limit = st.text_input("Liability Limit", value=policy.liability_limit)

        st.divider()
        st.write("Address Information")
        new_addr = st.text_input("Address", value=policy.insured_address if policy.insured_address else "")
        c1, c2, c3 = st.columns([2, 1, 1])
        new_city = c1.text_input("City", value=policy.insured_city if policy.insured_city else "")
        new_state = c2.text_input("State Code", value=policy.insured_state_code if policy.insured_state_code else "")
        new_zip = c3.text_input("Zip", value=policy.insured_zip if policy.insured_zip else "")

        submitted = st.form_submit_button("Save Changes", use_container_width=True, type="primary")
        
        if submitted:
            updated_data = {
                "insured_name": new_insured,
                "carrier_name": new_carrier,
                "premium": new_premium,
                "effective_date": new_eff,
                "expiration_date": new_exp,
                "liability_limit": new_limit,
                "insured_address": new_addr,
                "insured_city": new_city,
                "insured_state_code": new_state,
                "insured_zip": new_zip
            }
            
            if service.update_policy(policy, updated_data):
                st.success("Policy updated successfully!")
                st.rerun()
