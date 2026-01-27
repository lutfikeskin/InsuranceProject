import streamlit as st
import pandas as pd
import json
from services import PolicyService
from database import get_session, Policy, Vehicle, Driver, Coverage
from extractor import process_pdf
from vehicle_utils import refine_vehicle_type
import concurrent.futures
from streamlit_pdf_viewer import pdf_viewer

# Highlights disabled for performance

def page_process_policies(api_key):
    st.title("📤 Process Policies")
    st.markdown("Upload policies, review the extraction, and save to your database.")
    
    if "review_queue" not in st.session_state:
        st.session_state["review_queue"] = []
    
    if "temp_extracted" not in st.session_state:
        st.session_state["temp_extracted"] = []
        
    tab_upload, tab_manual = st.tabs(["📄 Upload & Extract", "✍️ Manual Entry"])
    
    with tab_upload:
        expanded_upload = not (bool(st.session_state["review_queue"]) or bool(st.session_state["temp_extracted"]))
        
        with st.expander("Step 1: Upload & Extract", expanded=expanded_upload):
            uploaded_files = st.file_uploader("Drop PDF files here", type=["pdf"], accept_multiple_files=True)

            if st.button("Start Extraction", type="primary") and uploaded_files:
                if not api_key:
                    st.error("Missing Gemini API Key. Please add it in Settings.")
                    return

                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total_files = len(uploaded_files)
                files_map = {f.name: f.getvalue() for f in uploaded_files}
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    futures = {executor.submit(process_pdf, content, api_key): fname for fname, content in files_map.items()}
                    
                    for i, future in enumerate(concurrent.futures.as_completed(futures)):
                        fname = futures[future]
                        status_text.text(f"Processing ({i+1}/{total_files}): {fname}...")
                        progress_bar.progress((i+1) / total_files)
                        
                        try:
                            data, usage, error_msg = future.result()
                            if data:
                                st.session_state["temp_extracted"].append({
                                    "filename": fname,
                                    "pdf_bytes": files_map[fname],
                                    "data": data
                                })
                            else:
                                st.error(f"Extraction failed for {fname}: {error_msg}")
                        except Exception as e:
                            st.error(f"Error processing {fname}: {e}")
                
                status_text.text("Extraction Complete! Choose an action below.")

        # Decision Section (Inside Tab 1)
        if st.session_state["temp_extracted"]:
            st.divider()
            st.subheader(f"✅ Extraction Complete ({len(st.session_state['temp_extracted'])} files)")
            st.info("What would you like to do with these policies?")
            
            d_col1, d_col2 = st.columns(2)
            
            if d_col1.button("🔍 Review Individually (Side-by-Side)", use_container_width=True):
                st.session_state["review_queue"].extend(st.session_state["temp_extracted"])
                st.session_state["temp_extracted"] = []
                st.rerun()
                
            if d_col2.button("💾 Save All to Database (Skip Review)", type="primary", use_container_width=True):
                processed_count = 0
                session = get_session(st.session_state.db_engine)
                service = PolicyService(session)
                
                try:
                    for item in st.session_state["temp_extracted"]:
                        success, msg = service.save_policy_from_extraction(item['data'])
                        
                        if success:
                            processed_count += 1
                        else:
                            st.toast(msg, icon="⚠️")
                    
                    st.success(f"Successfully saved {processed_count} policies!")
                    st.session_state["temp_extracted"] = []
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Bulk Save Error: {e}")
                finally:
                    session.close()

    with tab_manual:
        st.subheader("Manual Policy Entry")
        st.markdown("Manually enter policy details if you cannot upload a PDF.")
        
        with st.form("manual_entry_form"):
            col1, col2 = st.columns(2)
            with col1:
                m_carrier = st.text_input("Carrier Name")
                m_pol_num = st.text_input("Policy Number *")
                m_naic = st.text_input("NAIC Code")
                m_premium = st.text_input("Premium", value="$0.00")
            
            with col2:
                m_eff = st.date_input("Effective Date")
                m_exp = st.date_input("Expiration Date")
                m_type = st.selectbox("Policy Type", options=["personal_auto", "commercial_auto", "general_liability", "bop", "commercial_package", "umbrella", "motor_truck_cargo", "unknown"], index=1)
                m_conf = st.selectbox("Confidence", options=["high", "medium", "low"], index=0)

            st.divider()
            m_ins_name = st.text_input("Insured Name *")
            m_ins_addr = st.text_input("Insured Address")
            ic1, ic2, ic3 = st.columns(3)
            m_city = ic1.text_input("City")
            m_state = ic2.text_input("State")
            m_zip = ic3.text_input("Zip")

            st.divider()
            l1, l2, l3, l4 = st.columns(4)
            m_liab = l1.text_input("Liability Limit")
            m_gl_limit = l2.text_input("GL Limit")
            m_cargo = l3.text_input("Cargo Limit")
            m_cargo_ded = l4.text_input("Cargo Deductible")
            
            f1, f2, f3 = st.columns(3)
            m_gl = f1.checkbox("Has General Liabilities", value=True)
            m_auto = f2.checkbox("Has Auto Liabilities", value=True)
            m_coll = f3.checkbox("Has Full Collision", value=False)
            
            st.markdown("*Required Fields")
            submitted_manual = st.form_submit_button("💾 Save Manual Policy", type="primary", use_container_width=True)
            
            if submitted_manual:
                if not m_pol_num or not m_ins_name:
                    st.error("Policy Number and Insured Name are required.")
                else:
                    session = get_session(st.session_state.db_engine)
                    service = PolicyService(session)
                    try:
                        # Determine Account Type logic matches service
                        from services import ACCOUNT_TYPE_BY_POLICY
                        acc_type = ACCOUNT_TYPE_BY_POLICY.get(m_type, "Commercial")
                        
                        policy = Policy(
                            carrier_name=m_carrier,
                            naic_number=m_naic,
                            policy_number=m_pol_num,
                            effective_date=m_eff,
                            expiration_date=m_exp,
                            insured_name=m_ins_name,
                            insured_address=m_ins_addr,
                            insured_city=m_city,
                            insured_state_code=m_state,
                            insured_zip=m_zip,
                            premium=m_premium,
                            liability_limit=m_liab,
                            general_liability_limit=m_gl_limit,
                            cargo_limit=m_cargo,
                            cargo_deductible=m_cargo_ded,
                            has_general_liability=m_gl,
                            has_auto_liability=m_auto,
                            has_full_collision=m_coll,
                            policy_type=m_type,
                            account_type=acc_type,
                            classification_confidence=m_conf,
                            classification_signals=json.dumps(["Manual Entry"])
                        )
                        
                        success, msg = service.save_policy_object(policy)
                        if success:
                            st.toast(f"Policy {m_pol_num} saved successfully!", icon="✅")
                            # We can't easily clear the form without rerun, but rerun clears the toast.
                            # Just show success.
                        else:
                            st.error(f"Error: {msg}")
                            
                    except Exception as e:
                        st.error(f"Save failed: {e}")
                    finally:
                        session.close()

    # Review Section
    if st.session_state["review_queue"]:
        st.divider()
        st.subheader(f"Step 2: Review & Save ({len(st.session_state['review_queue'])} remaining)")
        
        current_item = st.session_state["review_queue"][0]
        p = current_item['data'].get('policy', {})
        fname = current_item['filename']
        
        c_pdf, c_form = st.columns([1, 1])
        
        with c_pdf:
            st.markdown(f"**Viewing:** `{fname}`")
            # Highlights disabled for performance
            pdf_viewer(input=current_item['pdf_bytes'], width=600, height=800)
            
        with c_form:
            st.markdown("#### Verify Extracted Data")
            with st.form(key=f"review_form_{fname}"):
                c1, c2 = st.columns(2)
                r_carrier = c1.text_input("Carrier", value=p.get('carrier_name', ''))
                r_pol_num = c2.text_input("Policy Number", value=p.get('policy_number', ''))
                
                # Show Classification Info
                classification = current_item['data'].get('classification', {})
                cc1, cc2 = st.columns(2)
                r_type = cc1.text_input("Policy Type", value=classification.get('policy_type', ''), disabled=True)
                r_conf = cc2.text_input("Confidence", value=classification.get('confidence', ''), disabled=True)
                
                c3, c4 = st.columns(2)
                r_naic = c3.text_input("NAIC Code", value=p.get('naic_number', ''))
                r_eff = c4.text_input("Effective Date", value=p.get('effective_date', ''))
                r_exp = c4.text_input("Expiration Date", value=p.get('expiration_date', ''))
                
                st.divider()
                r_ins_name = st.text_input("Insured Name", value=p.get('insured_name', ''))
                r_ins_addr = st.text_input("Insured Address", value=p.get('insured_address', ''))
                ic1, ic2, ic3 = st.columns(3)
                r_ins_city = ic1.text_input("City", value=p.get('insured_city', ''))
                r_ins_state = ic2.text_input("State", value=p.get('insured_state_code', ''))
                r_ins_zip = ic3.text_input("Zip", value=p.get('insured_zip', ''))
                
                st.divider()
                r_liab = st.text_input("Auto Liability Limit", value=p.get('liability_limit', ''))
                r_gl_limit = st.text_input("GL Limit", value=p.get('general_liability_limit', ''))
                r_cargo = st.text_input("Cargo Limit", value=p.get('cargo_limit', ''))
                r_cargo_ded = st.text_input("Cargo Ded", value=p.get('cargo_deductible', ''))
                
                r_gl = st.checkbox("Has GL", value=p.get('has_general_liability', True))
                r_auto = st.checkbox("Has Auto", value=p.get('has_auto_liability', True))

                st.markdown("---")
                b_col1, b_col2 = st.columns(2)
                saved = b_col1.form_submit_button("✅ Save to Database", type="primary")
                discarded = b_col2.form_submit_button("🗑️ Discard")
                
                if saved:
                    session = get_session(st.session_state.db_engine)
                    service = PolicyService(session)
                    try:
                        ef_dt = pd.to_datetime(r_eff, errors='coerce')
                        ex_dt = pd.to_datetime(r_exp, errors='coerce')
                        
                        policy = Policy(
                            carrier_name=r_carrier,
                            naic_number=r_naic,
                            policy_number=r_pol_num,
                            effective_date=ef_dt.date() if pd.notnull(ef_dt) else None,
                            expiration_date=ex_dt.date() if pd.notnull(ex_dt) else None,
                            insured_name=r_ins_name,
                            insured_address=r_ins_addr,
                            insured_city=r_ins_city,
                            insured_state_code=r_ins_state,
                            insured_zip=r_ins_zip,
                            liability_limit=r_liab,
                            general_liability_limit=r_gl_limit,
                            cargo_limit=r_cargo,
                            cargo_deductible=r_cargo_ded,
                            has_general_liability=r_gl,
                            has_auto_liability=r_auto,
                            account_type=p.get('account_type'),
                            policy_type=classification.get('policy_type'),
                            classification_confidence=classification.get('confidence'),
                            classification_signals=json.dumps(classification.get('signals', [])),
                            business_name=p.get('business_name'),
                            premium=p.get('premium'),
                            state=p.get('state'),
                            financial_responsibility_name=p.get('financial_responsibility_name'),
                            has_full_collision=p.get('has_full_collision')
                        )
                        
                        # Add sub-objects
                        for v in current_item['data'].get('vehicles', []):
                            refined = refine_vehicle_type(v.get('year'), v.get('make'), v.get('model'), v.get('vin'), v.get('type'))
                            policy.vehicles.append(Vehicle(
                                year=v.get('year'), 
                                make=v.get('make'), 
                                model=v.get('model'), 
                                vin=v.get('vin'), 
                                gvw=v.get('gvw'), 
                                vehicle_type=refined.get('final_type'),
                                chassis=refined.get('chassis'),
                                body=refined.get('body')
                            ))
                        for d in current_item['data'].get('drivers', []):
                            policy.drivers.append(Driver(full_name=d.get('full_name'), license_number=d.get('license_number'), is_excluded=d.get('is_excluded')))
                        for c in current_item['data'].get('coverages', []):
                             policy.coverages.append(Coverage(
                                 type=c.get('display_name') or c.get('type'), 
                                 coverage_code=c.get('coverage_code'),
                                 family=c.get('family'),
                                 
                                 # New Structured Limits
                                 per_person=c.get('limits', {}).get('per_person'),
                                 per_accident=c.get('limits', {}).get('per_accident'),
                                 per_occurrence=c.get('limits', {}).get('per_occurrence'),
                                 combined_single_limit=c.get('limits', {}).get('combined_single_limit'),
                                 aggregate=c.get('limits', {}).get('aggregate'),
                                 
                                 # Fallback
                                 limit_per_person=c.get('limit_person'), 
                                 limit_per_accident=c.get('limit_accident'), 
                                 deductible=c.get('deductible')
                             ))

                        # We should use service.save_policy_object
                        success, msg = service.save_policy_object(policy)
                        
                        if success:
                            st.success(f"Saved {r_pol_num}!")
                            st.session_state["review_queue"].pop(0)
                            st.rerun()
                        else:
                            st.warning(f"Could not save: {msg}")
                        
                    except Exception as e:
                        st.error(f"Save failed: {e}")
                    finally:
                        session.close()
                
                if discarded:
                    st.session_state["review_queue"].pop(0)
                    st.rerun()
    else:
        if "review_queue" in st.session_state and isinstance(st.session_state["review_queue"], list):
             st.info("No policies pending review.")
