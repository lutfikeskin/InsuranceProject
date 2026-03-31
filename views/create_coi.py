import streamlit as st
import pandas as pd
import io
import zipfile
from core.services import PolicyService, COIService
from core.database import get_session
from modules.coi import COIGenerator, load_companies
from utils.naic_utils import get_naic_for_carrier

def page_create_coi():
    st.title("📝 Create COI")
    st.markdown("Generate a Certificate of Insurance using data from an existing policy.")
    
    session = get_session(st.session_state.db_engine)
    service = PolicyService(session)
    coi_service = COIService()
    
    try:
        policies = service.get_all_policies()
        options = {f"{p.policy_number} - {p.insured_name}": p for p in policies}
        
        col_sel, col_mode = st.columns([2, 1])
        selected_key = col_sel.selectbox("Select Policy", options=list(options.keys()))
        
        # Bulk Mode Toggle
        bulk_mode = col_mode.toggle("Bulk Mode", value=False, help="Generate COIs for multiple companies at once")
        
        if selected_key:
            p = options[selected_key]
            st.info(f"Filling COI for: **{p.insured_name}** ({p.policy_number})")
            
            st.subheader("Certificate Holder Details")
            
            if "coi_companies" not in st.session_state:
                st.session_state.coi_companies = load_companies("data/Additionalinsuredcomps.xlsx")

            company_options = sorted(list(st.session_state.coi_companies.keys()))
            
            if not bulk_mode:
                # SINGLE MODE
                company_options_single = ["None"] + company_options
                
                def on_company_select():
                    selected = st.session_state.get("selected_coi_company")
                    if selected and selected != "None":
                        comp_data = st.session_state.coi_companies.get(selected, {})
                        st.session_state["h_name"] = comp_data.get("name", "")
                        st.session_state["h_addr"] = comp_data.get("address", "")
                        st.session_state["h_city"] = comp_data.get("city", "")
                        st.session_state["h_state"] = comp_data.get("state", "")
                        st.session_state["h_zip"] = comp_data.get("zip", "")

                st.selectbox("Quick Fill from Company List", options=company_options_single, key="selected_coi_company", on_change=on_company_select)

                c1, c2 = st.columns(2)
                with c1:
                    if "h_name" not in st.session_state: st.session_state["h_name"] = ""
                    if "h_addr" not in st.session_state: st.session_state["h_addr"] = ""
                    if "h_city" not in st.session_state: st.session_state["h_city"] = ""
                    
                    h_name = st.text_input("Holder Name", key="h_name")
                    h_addr = st.text_input("Address", key="h_addr")
                    h_city = st.text_input("City", key="h_city")
                with c2:
                    if "h_state" not in st.session_state: st.session_state["h_state"] = ""
                    if "h_zip" not in st.session_state: st.session_state["h_zip"] = ""
                    
                    h_state = st.text_input("State", key="h_state")
                    h_zip = st.text_input("Zip", key="h_zip")
                    
                    # Pre-fill description
                    _, desc_lines = coi_service.prepare_coi_data(p)
                    desc_lines.append("Radius of Operation: Unlimited")
                    desc_lines.append("Certificate Holder is also listed as an additional insured")
                    default_desc = "\n".join(desc_lines)
                    
                    if "h_desc_val" not in st.session_state:
                        st.session_state["h_desc_val"] = default_desc
                    
                    h_desc = st.text_area("Operations Description", value=default_desc, height=150)
                    h_desc_font_size = st.slider("Description Font Size (pt)", min_value=4, max_value=12, value=8, key="single_desc_font")
            else:
                # BULK MODE
                selected_companies = st.multiselect("Select Companies", options=company_options)
                
                # Description for bulk
                _, desc_lines = coi_service.prepare_coi_data(p)
                desc_lines.append("Radius of Operation: Unlimited")
                desc_lines.append("Certificate Holder is also listed as an additional insured")
                default_desc = "\n".join(desc_lines)
                h_desc = st.text_area("Operations Description (applied to all)", value=default_desc, height=150)
                h_desc_font_size = st.slider("Description Font Size (pt)", min_value=4, max_value=12, value=8, key="bulk_desc_font")

                if selected_companies:
                    st.info(f"Selected {len(selected_companies)} companies for bulk generation.")
                
            st.divider()
            st.subheader("Insured Details (Edit if needed)")
            
            ic1, ic2 = st.columns(2)
            with ic1:
                i_name = st.text_input("Insured Name", value=p.insured_name if p.insured_name else "")
                i_addr = st.text_input("Insured Address", value=p.insured_address if p.insured_address else "")
                i_city = st.text_input("Insured City", value=p.insured_city if p.insured_city else "")
            with ic2:
                i_state = st.text_input("Insured State", value=p.insured_state_code if p.insured_state_code else "")
                i_zip = st.text_input("Insured Zip", value=p.insured_zip if p.insured_zip else "")
                
                # NAIC Field
                default_naic = p.naic_number if p.naic_number else get_naic_for_carrier(p.carrier_name)
                i_naic = st.text_input("Insurer NAIC #", value=default_naic)

            st.divider()
            st.subheader("🛡️ Coverages to Include")
            gc1, gc2, gc3 = st.columns(3)
            with gc1:
                ui_has_gl = st.checkbox("General Liability", value=p.has_general_liability if p.has_general_liability is not None else True)
            with gc2:
                ui_has_auto = st.checkbox("Automobile Liability", value=p.has_auto_liability if p.has_auto_liability is not None else True)
            with gc3:
                ui_has_cargo = st.checkbox("Motor Truck Cargo", value=bool(p.cargo_limit))

            # Common generation logic
            def prepare_p_data():
                return {
                    "carrier_name": p.carrier_name, 
                    "naic_number": i_naic, 
                    "policy_number": p.policy_number, 
                    "effective_date": p.effective_date, 
                    "expiration_date": p.expiration_date, 
                    "liability_limit": p.liability_limit,
                    "cargo_limit": p.cargo_limit,
                    "cargo_deductible": p.cargo_deductible if p.cargo_deductible else "1000",
                    "has_general_liability": ui_has_gl,
                    "has_auto_liability": ui_has_auto,
                    "has_cargo": ui_has_cargo,
                    "insured_name": i_name,
                    "insured_address": i_addr,
                    "insured_city": i_city,
                    "insured_state_code": i_state,
                    "insured_zip": i_zip,
                    "vehicle_list_str": "", 
                    "driver_list_str": ""
                }

            if not bulk_mode:
                if st.button("Generate & Download PDF", type="primary"):
                    if not h_name:
                        st.error("Holder Name is required.")
                    else:
                        gen = COIGenerator()
                        p_data = prepare_p_data()
                        h_data = {"name": h_name, "address": h_addr, "city": h_city, "state": h_state, "zip": h_zip, "description": h_desc}
                        
                        try:
                            pdf = gen.generate_coi(p_data, h_data, desc_font_size=h_desc_font_size)
                            if pdf:
                                st.success("Successfully generated COI!")
                                st.download_button("📥 Download COI PDF", data=pdf, file_name=f"COI_{p.policy_number}.pdf", mime="application/pdf")
                        except Exception as e:
                            st.error(f"Generation failed: {e}")
            else:
                if st.button("Generate Bulk COIs", type="primary"):
                    if not selected_companies:
                        st.error("Please select at least one company.")
                    else:
                        gen = COIGenerator()
                        p_data = prepare_p_data()
                        
                        zip_buffer = io.BytesIO()
                        try:
                            with zipfile.ZipFile(zip_buffer, "w") as zf:
                                for comp_name in selected_companies:
                                    comp_data = st.session_state.coi_companies.get(comp_name, {})
                                    h_data = {
                                        "name": comp_data.get("name", ""),
                                        "address": comp_data.get("address", ""),
                                        "city": comp_data.get("city", ""),
                                        "state": comp_data.get("state", ""),
                                        "zip": comp_data.get("zip", ""),
                                        "description": h_desc
                                    }
                                    pdf = gen.generate_coi(p_data, h_data, desc_font_size=h_desc_font_size)
                                    if pdf:
                                        # Sanitize filename
                                        safe_name = "".join([c for c in comp_name if c.isalnum() or c in (' ', '_')]).strip()
                                        zf.writestr(f"COI_{safe_name}.pdf", pdf)
                            
                            st.success(f"Successfully generated {len(selected_companies)} COIs!")
                            st.download_button(
                                "📥 Download All (ZIP)", 
                                data=zip_buffer.getvalue(), 
                                file_name=f"COIs_Bulk_{p.policy_number}.zip", 
                                mime="application/zip"
                            )
                        except Exception as e:
                            st.error(f"Bulk generation failed: {e}")
    finally:
        session.close()
