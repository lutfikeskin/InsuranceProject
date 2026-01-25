import streamlit as st
import pandas as pd
import os
from sqlalchemy.orm import Session
from database import init_db, Policy, Vehicle, Coverage, Driver, get_session
from extractor import process_pdf
from exporter import create_excel_report
from coi_generator import COIGenerator
from coi_utils import load_companies
from naic_utils import get_naic_for_carrier
from streamlit_option_menu import option_menu

# Page Config
st.set_page_config(
    page_title="Insurance Doc Intelligence", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Premium Look
st.markdown("""
<style>
    /* Main Background */
    .stApp {
        background-color: #F8F9FA;
    }
    
    /* Hide Streamlit Branding */
    #MainMenu {visibility: visible;}
    footer {visibility: hidden;}
    header {background: rgba(255, 255, 255, 0);}
    
    /* Modern Card Container */
    .css-1r6slb0, .stMetric {
        background: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    
    /* Navigation Sidebar Styling Override */
    [data-testid="stSidebar"] {
        background-color: #FFFFFF;
        border-right: 1px solid #E0E0E0;
    }
    
    /* Brand Header */
    .brand-header {
        padding: 20px 0;
        text-align: center;
        border-bottom: 1px solid #F0F0F0;
        margin-bottom: 20px;
    }
    
    /* Titles */
    h1, h2, h3 {
        color: #005AA9 !important;
        font-family: 'Inter', -apple-system, sans-serif;
        font-weight: 700;
    }
    
    /* Custom Sidebar Nav padding */
    .nav-container {
        padding: 10px;
    }
    
    /* Hide Header Anchors */
    [data-testid="stHeaderActionElements"] {
        display: none;
    }
    
</style>
""", unsafe_allow_html=True)

# Initialize DB
if 'db_engine' not in st.session_state:
    st.session_state.db_engine = init_db()

# --- Global Logic / Settings Helper ---
api_key = st.session_state.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))

# If not in session, try secrets
if not api_key:
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
            st.session_state["GEMINI_API_KEY"] = api_key
    except:
        pass

# --- Settings Dialog ---
@st.dialog("⚙️ Application Settings")
def settings_modal():
    st.write("Configure your application settings below.")
    current_key = st.session_state.get("GEMINI_API_KEY", "")
    new_key = st.text_input("Gemini API Key", value=current_key if current_key else "", type="password", help="Enter your Google Gemini API Key for policy extraction.")
    
    if st.button("Save & Refresh", use_container_width=True, type="primary"):
        if new_key:
            st.session_state["GEMINI_API_KEY"] = new_key
            st.success("Settings saved successfully!")
            st.rerun()
        else:
            st.warning("Please enter a valid key.")

# --- Sidebar Navigation ---
with st.sidebar:
    st.markdown('<div class="brand-header"><h3>Truckers National</h3><p style="color: #666; font-size: 0.8rem;">Policy Intelligence Hub</p></div>', unsafe_allow_html=True)
    
    selected = option_menu(
        menu_title=None,
        options=["Dashboard", "Process Policies", "History", "Create COI"],
        icons=["house-fill", "cloud-arrow-up-fill", "database-fill", "file-earmark-pdf-fill"],
        menu_icon="cast",
        default_index=0,
        styles={
            "container": {"padding": "0!important", "background-color": "#fff", "border-radius": "0"},
            "icon": {"color": "#005AA9", "font-size": "18px"}, 
            "nav-link": {
                "font-size": "15px", 
                "text-align": "left", 
                "margin": "5px 0px", 
                "padding": "10px 15px",
                "color": "#444",
                "font-weight": "500",
                "border-radius": "8px"
            },
            "nav-link-selected": {
                "background-color": "#E6F4FF", 
                "color": "#005AA9",
                "font-weight": "600",
                "border-left": "4px solid #005AA9"
            },
        }
    )
    
    st.spacer = st.empty()
    st.markdown("<br>" * 10, unsafe_allow_html=True) # Push settings to bottom
    
    st.divider()
    if st.button("⚙️ Settings", use_container_width=True):
        settings_modal()
    
    if api_key:
        st.success("API Active", icon="✅")
    else:
        st.warning("API Missing", icon="⚠️")

# --- Page Routing & Logic ---

def page_dashboard():
    st.title("📊 Values Dashboard")
    session = get_session(st.session_state.db_engine)
    try:
        total_policies = session.query(Policy).count()
        total_vehicles = session.query(Vehicle).count()
        total_drivers = session.query(Driver).count()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Policies", total_policies)
        with col2:
            st.metric("Total Vehicles", total_vehicles)
        with col3:
            st.metric("Total Drivers", total_drivers)
        
        st.divider()
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.subheader("Recent Policy Activity")
            if total_policies > 0:
                policies = session.query(Policy).order_by(Policy.id.desc()).limit(10).all()
                data = []
                for p in policies:
                     data.append({
                         "Policy #": p.policy_number,
                         "Insured": p.insured_name,
                         "Carrier": p.carrier_name,
                         "Effective": p.effective_date
                     })
                st.table(pd.DataFrame(data))
            else:
                st.info("No policies extracted yet. Start by uploading files in the 'Process Policies' tab.")
                
        with c2:
            st.subheader("Quick Actions")
            if st.button("➕ Extract New Policy", use_container_width=True):
                # We can't change 'selected' from here easily without rerun and state,
                # but we can instruct the user or use a session state trick.
                st.info("Navigate to 'Process Policies' on the left.")
            
            if st.button("📄 Generate COI", use_container_width=True):
                st.info("Navigate to 'Create COI' on the left.")

    finally:
        session.close()

def page_process_policies():
    st.title("📤 Process Policies")
    st.markdown("Upload one or multiple PDF insurance policies to extract and save their data.")
    
    uploaded_files = st.file_uploader("Drop PDF files here", type=["pdf"], accept_multiple_files=True)

    if st.button("Start Extraction", type="primary") and uploaded_files:
        if not api_key:
            st.error("Missing Gemini API Key. Please add it in Settings.")
            return

        progress_bar = st.progress(0)
        status_text = st.empty()
        processed_data = []
        
        session = get_session(st.session_state.db_engine)
        try:
            import concurrent.futures
            total_files = len(uploaded_files)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                futures = {executor.submit(process_pdf, f.getvalue(), api_key): f for f in uploaded_files}
                
                for i, future in enumerate(concurrent.futures.as_completed(futures)):
                    f = futures[future]
                    status_text.text(f"Processing ({i+1}/{total_files}): {f.name}...")
                    progress_bar.progress((i+1) / total_files)
                    
                    try:
                        data, usage = future.result()
                        if data:
                            processed_data.append(data)
                            p_data = data.get('policy', {})
                            
                            existing = session.query(Policy).filter_by(policy_number=p_data.get('policy_number')).first()
                            if existing:
                                st.toast(f"Skipped duplicate: {p_data.get('policy_number')}", icon="⚠️")
                            else:
                                effective_dt = pd.to_datetime(p_data.get('effective_date'), errors='coerce')
                                expiration_dt = pd.to_datetime(p_data.get('expiration_date'), errors='coerce')

                                policy = Policy(
                                    carrier_name=p_data.get('carrier_name'),
                                    naic_number=p_data.get('naic_number'),
                                    policy_number=p_data.get('policy_number'),
                                    effective_date=effective_dt.date() if pd.notnull(effective_dt) else None,
                                    expiration_date=expiration_dt.date() if pd.notnull(expiration_dt) else None,
                                    account_type=p_data.get('account_type'),
                                    insured_name=p_data.get('insured_name'),
                                    business_name=p_data.get('business_name'),
                                    
                                    # Address
                                    insured_address=p_data.get('insured_address'),
                                    insured_city=p_data.get('insured_city'),
                                    insured_state_code=p_data.get('insured_state_code'),
                                    insured_zip=p_data.get('insured_zip'),
                                    
                                    premium=p_data.get('premium'),
                                    state=p_data.get('state'),
                                    financial_responsibility_name=p_data.get('financial_responsibility_name'),
                                    liability_limit=p_data.get('liability_limit'),
                                    cargo_limit=p_data.get('cargo_limit'),
                                    cargo_deductible=p_data.get('cargo_deductible'),
                                    has_full_collision=p_data.get('has_full_collision'),
                                    
                                    has_general_liability=p_data.get('has_general_liability', True),
                                    has_auto_liability=p_data.get('has_auto_liability', True)
                                )
                                
                                # Add Vehicles, Coverages, Drivers
                                for v in data.get('vehicles', []):
                                    policy.vehicles.append(Vehicle(year=v.get('year'), make=v.get('make'), model=v.get('model'), vin=v.get('vin'), gvw=v.get('gvw'), vehicle_type=v.get('type')))
                                for c in data.get('coverages', []):
                                    policy.coverages.append(Coverage(type=c.get('type'), limit_per_person=c.get('limit_person'), limit_per_accident=c.get('limit_accident'), deductible=c.get('deductible')))
                                for d in data.get('drivers', []):
                                    policy.drivers.append(Driver(full_name=d.get('full_name'), license_number=d.get('license_number'), is_excluded=d.get('is_excluded')))
                                
                                session.add(policy)
                                session.commit()
                        else:
                            st.error(f"Extraction failed for {f.name}")
                    except Exception as e:
                        st.error(f"Error processing {f.name}: {e}")

            status_text.text("Extraction Complete!")
            st.success(f"Successfully processed {len(processed_data)} policies.")
            
            if processed_data:
                excel_data = create_excel_report(processed_data)
                st.download_button("📥 Download Excel Report", data=excel_data, file_name="insurance_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
        finally:
            session.close()

def page_history():
    st.title("🗄️ Database History")
    st.markdown("View and export all previously extracted insurance data.")
    
    session = get_session(st.session_state.db_engine)
    try:
        policies = session.query(Policy).all()
        if not policies:
            st.info("No records found in database.")
            return

        data_list = []
        export_data = []
        for p in policies:
            data_list.append({"ID": p.id, "Policy#": p.policy_number, "Carrier": p.carrier_name, "Insured": p.insured_name, "Effective": p.effective_date})
            
            # Reconstruct for exporter
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
                    
                    # Perform deletion
                    try:
                        for pid in ids_to_delete:
                            # Fetch and delete
                            pol = session.query(Policy).get(pid)
                            if pol:
                                session.delete(pol)
                        
                        session.commit()
                        st.success("Policies deleted successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error during deletion: {e}")

    finally:
        session.close()

def page_create_coi():
    st.title("📝 Create COI")
    st.markdown("Generate a Certificate of Insurance using data from an existing policy.")
    
    session = get_session(st.session_state.db_engine)
    try:
        policies = session.query(Policy).all()
        options = {f"{p.policy_number} - {p.insured_name}": p for p in policies}
        
        col_sel, _ = st.columns([2, 1])
        selected_key = col_sel.selectbox("Select Policy", options=list(options.keys()))
        
        if selected_key:
            p = options[selected_key]
            st.info(f"Filling COI for: **{p.insured_name}** ({p.policy_number})")
            
            st.subheader("Certificate Holder Details")
            
            # --- Autocomplete Logic ---
            if "coi_companies" not in st.session_state:
                st.session_state.coi_companies = load_companies("Additionalinsuredcomps.xlsx")

            company_options = ["None"] + sorted(list(st.session_state.coi_companies.keys()))
            
            def on_company_select():
                selected = st.session_state.get("selected_coi_company")
                if selected and selected != "None":
                    comp_data = st.session_state.coi_companies.get(selected, {})
                    st.session_state["h_name"] = comp_data.get("name", "")
                    st.session_state["h_addr"] = comp_data.get("address", "")
                    st.session_state["h_city"] = comp_data.get("city", "")
                    st.session_state["h_state"] = comp_data.get("state", "")
                    st.session_state["h_zip"] = comp_data.get("zip", "")

            st.selectbox("Quick Fill from Company List", options=company_options, key="selected_coi_company", on_change=on_company_select)
            # --------------------------

            c1, c2 = st.columns(2)
            with c1:
                # Initialize state keys if valid
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
                
                # --- Auto-Generate Description Defaults ---
                # We do this here so user can see/edit it before generation
                desc_lines = []
                if p.vehicles:
                    v_str = " ".join([f"[{v.year} {v.make} {v.vin}]" for v in p.vehicles])
                    desc_lines.append(f"Vehicle List: {v_str}")
                if p.drivers:
                    d_str = ", ".join([d.full_name for d in p.drivers])
                    desc_lines.append(f"Driver List: {d_str}")
                desc_lines.append("Radius of Operation: Unlimited")
                desc_lines.append("Certificate Holder is also listed as an additional insured")
                
                default_desc = "\n".join(desc_lines)
                
                # Use a session key to persistence edits, init with default if empty
                if "h_desc_val" not in st.session_state:
                    st.session_state["h_desc_val"] = default_desc
                
                # If the user switches policies (selected_key changes), we might want to reset? 
                # For now, simplistic approach: check if we match the current policy context? 
                # Better: Just load it into the text area default, and if they change it, they change it.
                # Actually, standard streamlit flow:
                
                h_desc = st.text_area("Operations Description", value=default_desc, height=150)
                
            st.divider()
            st.subheader("Insured Details (Edit if needed)")
            
            # Form for Insured Details - pre-filled from Policy but editable
            ic1, ic2 = st.columns(2)
            with ic1:
                i_name = st.text_input("Insured Name", value=p.insured_name if p.insured_name else "")
                i_addr = st.text_input("Insured Address", value=p.insured_address if p.insured_address else "")
                i_city = st.text_input("Insured City", value=p.insured_city if p.insured_city else "")
            with ic2:
                i_state = st.text_input("Insured State", value=p.insured_state_code if p.insured_state_code else "")
                i_zip = st.text_input("Insured Zip", value=p.insured_zip if p.insured_zip else "")

            # st.divider()
            # Policy Logic (Hidden/Auto)
            # We use the extracted values directly
            has_gl = p.has_general_liability if p.has_general_liability is not None else True
            has_auto = p.has_auto_liability if p.has_auto_liability is not None else True

            if st.button("Generate & Download PDF", type="primary"):
                if not h_name:
                    st.error("Holder Name is required.")
                else:
                    gen = COIGenerator()
                    
                    # Compute logic values
                    current_naic = p.naic_number if p.naic_number else get_naic_for_carrier(p.carrier_name)
                    cargo_ded_val = p.cargo_deductible if p.cargo_deductible else "1000"
                    
                    p_data = {
                        "carrier_name": p.carrier_name, 
                        "naic_number": current_naic,
                        "policy_number": p.policy_number, 
                        "effective_date": p.effective_date, 
                        "expiration_date": p.expiration_date, 
                        "liability_limit": p.liability_limit,
                        "cargo_limit": p.cargo_limit,
                        "cargo_deductible": cargo_ded_val,
                        
                        "has_general_liability": has_gl,
                        "has_auto_liability": has_auto,
                        
                        "insured_name": i_name,
                        "insured_address": i_addr,
                        "insured_city": i_city,
                        "insured_state_code": i_state,
                        "insured_zip": i_zip,
                        
                        # Note: description is passed via h_data, so we don't need to generate it here anymore
                        # But we keep empty strings to prevent errors if generator expects keys
                        "vehicle_list_str": "", 
                        "driver_list_str": ""
                    }
                    h_data = {"name": h_name, "address": h_addr, "city": h_city, "state": h_state, "zip": h_zip, "description": h_desc}
                    
                    try:
                        pdf = gen.generate_coi(p_data, h_data)
                        if pdf:
                            st.success("Successfully generated COI!")
                            st.download_button("📥 Download COI PDF", data=pdf, file_name=f"COI_{p.policy_number}.pdf", mime="application/pdf")
                    except Exception as e:
                        st.error(f"Generation failed: {e}")
    finally:
        session.close()

# --- Main Routing ---
if selected == "Dashboard":
    page_dashboard()
elif selected == "Process Policies":
    page_process_policies()
elif selected == "History":
    page_history()
elif selected == "Create COI":
    page_create_coi()
