import streamlit as st
import pandas as pd
import os
from sqlalchemy.orm import Session
from database import init_db, Policy, Vehicle, Coverage, Driver, get_session
from extractor import process_pdf
from exporter import create_excel_report

# Page Config
st.set_page_config(page_title="Insurance Doc Intelligence", layout="wide")

st.title("📄 Insurance Policy Intelligent Extractor")

# Custom CSS for Truckers National Branding
st.markdown("""
<style>
    /* Main Background override to ensure white */
    .stApp {
        background-color: #FFFFFF;
    }
    
    /* Header Styling */
    h1, h2, h3 {
        color: #005AA9 !important; /* Brand Blue */
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    /* Button Styling */
    .stButton > button {
        background-color: #005AA9 !important;
        color: white !important;
        border-radius: 6px;
        border: none;
        font-weight: 600;
    }
    .stButton > button:hover {
        background-color: #5DA8DC !important; /* Lighter Blue on hover */
        color: white !important;
    }
    
    /* Stats Box Styling */
    div[data-testid="stMetricValue"] {
        color: #005AA9;
    }
    
    /* Tab Container Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
        background-color: transparent;
    }
    
    /* Individual Tab Styling */
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #F7F7F7 !important;
        border-radius: 8px 8px 0px 0px !important;
        padding-left: 20px !important;
        padding-right: 20px !important;
        border: 1px solid #EDEDF1 !important;
        border-bottom: none !important;
        color: #162634 !important;
        font-weight: 500 !important;
    }
    
    /* Active Tab Styling */
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        background-color: #005AA9 !important;
        color: white !important;
        border: 1px solid #005AA9 !important;
    }
    
    /* Hover Effect */
    .stTabs [data-baseweb="tab"]:hover {
        color: #005AA9 !important;
        background-color: #E6F4FF !important;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar - Configuration
st.sidebar.header("Configuration")

# Try to get API Key from secrets or env, else ask user
api_key = os.getenv("GEMINI_API_KEY") 
try:
    if not api_key and "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
except FileNotFoundError:
    pass # st.secrets might fail if no secrets file exists locally

if not api_key:
    api_key = st.sidebar.text_input("Enter Gemini API Key", type="password")
    if not api_key:
        st.sidebar.warning("API Key is required to proceed.")
else:
    st.sidebar.success("API Key Loaded")

# Initialize DB
if 'db_engine' not in st.session_state:
    st.session_state.db_engine = init_db()

# Main Interface
tab1, tab2 = st.tabs(["📤 Process Policies", "🗄️ Database History"])

with tab1:
    uploaded_files = st.file_uploader("Upload Insurance Policy PDFs", type=["pdf"], accept_multiple_files=True)

    if st.button("Process Policies") and uploaded_files:
        if not api_key:
            st.error("Please provide an API Key.")
            st.stop()

        progress_bar = st.progress(0)
        status_text = st.empty()
        
        processed_data = [] # To hold data for the report
        
        session = get_session(st.session_state.db_engine)
        
        try:
            # Concurrent Processing
            import concurrent.futures
            
            total_input_tokens = 0
            total_output_tokens = 0
            
            total_files = len(uploaded_files)
            
            # We use a ThreadPoolExecutor to process files in parallel
            # Reduced from 5 to 2 to prevent hitting API Rate Limits (429) which causes exponential backoff (slowing things down)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                # Prepare futures
                future_to_file = {
                    executor.submit(process_pdf, file.getvalue(), api_key): file 
                    for file in uploaded_files
                }
                
                completed_count = 0
                
                for future in concurrent.futures.as_completed(future_to_file):
                    uploaded_file = future_to_file[future]
                    completed_count += 1
                    
                    status_text.text(f"Processed {completed_count}/{total_files}: {uploaded_file.name}")
                    progress_bar.progress(completed_count / total_files)
                    
                    try:
                        data, usage = future.result()
                        
                        if data:
                            processed_data.append(data)
                            
                            # Token Stats
                            if usage:
                                total_input_tokens += usage.prompt_token_count
                                total_output_tokens += usage.candidates_token_count
                            
                            # Save to DB (Single threaded write for safety, though SQLite handles it reasonable reasonably well, sequential is safer here or use a lock)
                            # Since we are in the main thread loop of as_completed, this IS sequential writing.
                            p_data = data.get('policy', {})
                            
                            existing = session.query(Policy).filter_by(policy_number=p_data.get('policy_number')).first()
                            if existing:
                                 st.toast(f"Skipped duplicate: {p_data.get('policy_number')}", icon="⚠️")
                            else:
                                # Helper for safe date conversion
                                effective_dt = pd.to_datetime(p_data.get('effective_date'), errors='coerce')
                                expiration_dt = pd.to_datetime(p_data.get('expiration_date'), errors='coerce')

                                policy = Policy(
                                    carrier_name=p_data.get('carrier_name'),
                                    policy_number=p_data.get('policy_number'),
                                    effective_date=effective_dt.date() if pd.notnull(effective_dt) else None,
                                    expiration_date=expiration_dt.date() if pd.notnull(expiration_dt) else None,
                                    account_type=p_data.get('account_type'),
                                    insured_name=p_data.get('insured_name'),
                                    business_name=p_data.get('business_name'),
                                    premium=p_data.get('premium'),
                                    state=p_data.get('state'),
                                    financial_responsibility_name=p_data.get('financial_responsibility_name'),
                                    liability_limit=p_data.get('liability_limit'),
                                    cargo_limit=p_data.get('cargo_limit'),
                                    has_full_collision=p_data.get('has_full_collision')
                                )
                                
                                # Vehicles
                                for v_data in data.get('vehicles', []):
                                    vehicle = Vehicle(
                                        year=v_data.get('year'),
                                        make=v_data.get('make'),
                                        model=v_data.get('model'),
                                        vin=v_data.get('vin'),
                                        gvw=v_data.get('gvw'),
                                        vehicle_type=v_data.get('type')
                                    )
                                    policy.vehicles.append(vehicle)
                                
                                # Coverages
                                for c_data in data.get('coverages', []):
                                    coverage = Coverage(
                                        type=c_data.get('type'),
                                        limit_per_person=c_data.get('limit_person'),
                                        limit_per_accident=c_data.get('limit_accident'),
                                        deductible=c_data.get('deductible')
                                    )
                                    policy.coverages.append(coverage)
                                    
                                # Drivers
                                for d_data in data.get('drivers', []):
                                    driver = Driver(
                                        full_name=d_data.get('full_name'),
                                        license_number=d_data.get('license_number'),
                                        is_excluded=d_data.get('is_excluded')
                                    )
                                    policy.drivers.append(driver)
                                    
                                session.add(policy)
                                session.commit()
                        
                        else:
                            st.error(f"Failed to extract data from {uploaded_file.name}")
                    except Exception as exc:
                        st.error(f"File {uploaded_file.name} generated an exception: {exc}")

            status_text.text("Processing Complete!")
            st.success(f"Successfully processed {len(processed_data)} policies.")
            
            # Display Stats
            st.info(f"📊 **Token Usage**: {total_input_tokens} Input / {total_output_tokens} Output. (Avg ~{int(total_input_tokens/total_files) if total_files else 0} per doc)")
            
            # Display Summary
            if processed_data:
                st.subheader("Extracted Policies Summary")
                
                # Define standard columns to ensure they are always present
                POLICY_COLUMNS = [
                    "carrier_name", "policy_number", "effective_date", "expiration_date",
                    "account_type", "insured_name", "business_name", "premium", "state",
                    "financial_responsibility_name", "liability_limit", "cargo_limit", "has_full_collision"
                ]
                
                df_summary = pd.DataFrame([d['policy'] for d in processed_data])
                # Reindex ensure all columns exist, fill missing with None/NaN which shows as empty in st.dataframe
                df_summary = df_summary.reindex(columns=POLICY_COLUMNS)
                
                st.dataframe(df_summary)
                
                # Generate Report
                excel_data = create_excel_report(processed_data)
                
                st.download_button(
                    label="📥 Download Excel Report",
                    data=excel_data,
                    file_name="insurance_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        except Exception as e:
            session.rollback()
            st.error(f"An error occurred: {e}")
        finally:
            session.close()

with tab2:
    st.header("🗄️ Database History")
    
    if st.button("🔄 Refresh Data"):
        st.rerun()

    session = get_session(st.session_state.db_engine)
    try:
        policies = session.query(Policy).all()
        
        if not policies:
            st.info("No policies found in database.")
        else:
            # Convert to DataFrame for display
            data_list = []
            full_export_data = [] # Reconstruct complex object for exporter logic
            
            for p in policies:
                # Flat dictionary for table view
                row = {
                    "ID": p.id,
                    "Policy Number": p.policy_number,
                    "Carrier": p.carrier_name,
                    "Insured": p.insured_name,
                    "Premium": p.premium,
                    "Effective": p.effective_date,
                    "Vehicles": len(p.vehicles)
                }
                data_list.append(row)
                
                # Reconstruct full object for Excel Export reuse
                policy_dict = {
                    "policy": {
                        "carrier_name": p.carrier_name,
                        "policy_number": p.policy_number,
                        "effective_date": str(p.effective_date), # Exporter expects these
                        "expiration_date": str(p.expiration_date),
                        "account_type": p.account_type,
                        "insured_name": p.insured_name,
                        "business_name": p.business_name,
                        "premium": p.premium,
                        "state": p.state,
                        "financial_responsibility_name": p.financial_responsibility_name,
                        "liability_limit": p.liability_limit,
                        "cargo_limit": p.cargo_limit,
                        "has_full_collision": p.has_full_collision
                    },
                    "vehicles": [
                        {"year": v.year, "make": v.make, "model": v.model, "vin": v.vin, "gvw": v.gvw, "type": v.vehicle_type} 
                        for v in p.vehicles
                    ],
                    "coverages": [
                         {"type": c.type, "limit_person": c.limit_per_person, "limit_accident": c.limit_per_accident, "deductible": c.deductible}
                         for c in p.coverages
                    ],
                    "drivers": [
                        {"full_name": d.full_name, "license_number": d.license_number, "is_excluded": d.is_excluded}
                        for d in p.drivers
                    ]
                }
                full_export_data.append(policy_dict)

            df = pd.DataFrame(data_list)
            st.dataframe(df, width='stretch')
            
            # Export All
            excel_data_all = create_excel_report(full_export_data)
             
            st.download_button(
                label="📥 Export All to Excel",
                data=excel_data_all,
                file_name="full_insurance_history.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_all"
            )
            
            # DB Download
            if os.path.exists("insurance_data.db"):
                with open("insurance_data.db", "rb") as f:
                    db_bytes = f.read()
                    st.download_button(
                        label="💾 Download Database File",
                        data=db_bytes,
                        file_name="insurance_data.db",
                        mime="application/x-sqlite3",
                        key="download_db"
                    )

    except Exception as e:
        st.error(f"Error reading database: {e}")
    finally:
        session.close()
