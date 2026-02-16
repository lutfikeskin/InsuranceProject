import streamlit as st
import pandas as pd
from core.constants import VEHICLE_TYPES, INTEREST_TYPES, VIN_REGEX
import json
from core.services import PolicyService
from core.database import get_session, Policy, Vehicle, Driver, Coverage, AdditionalInterest
from modules.extraction import process_pdf
from utils.vehicle_utils import refine_vehicle_type
from utils.naic_utils import get_naic_for_carrier
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

    def get_source_help(field_name, field_locations):
        """Helper to generate tooltip text for a field."""
        if not field_locations:
            return None
        formatted_key = field_name
        # Map simple keys to field_locations keys if different
        # Currently the pipeline saves keys like "premium", "policy_number" directly.
        
        for loc in field_locations:
             if loc.get("field") == field_name:
                 page = loc.get("page_number")
                 # bbox = loc.get("bbox") # Optional: Add bbox details if valuable
                 return f"Found on Page {page}"
        return None

    with tab_upload:
        expanded_upload = not (bool(st.session_state["review_queue"]) or bool(st.session_state["temp_extracted"]))
        
        with st.expander("Step 1: Upload & Extract", expanded=expanded_upload):
            if not api_key:
                 st.warning("⚠️ Access Restricted: Please add your Gemini API Key in Settings to proceed.")
            
            uploaded_files = st.file_uploader("Drop PDF files here", type=["pdf"], accept_multiple_files=True)
            
            if not uploaded_files:
                st.info("👆 **Tip:** You can select multiple PDF files at once. The AI will process them sequentially.")
                
            if st.button("Start Extraction", type="primary") and uploaded_files:
                force_refresh = st.checkbox("Force Refresh (Bypass Cache)", value=False, help="Enable this to re-process files even if they were processed before.")
                
                if not api_key:
                    st.error("Missing Gemini API Key. Please add it in Settings.")
                    return

                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total_files = len(uploaded_files)
                files_map = {f.name: f.getvalue() for f in uploaded_files}
                
                # Sequential processing to allow live logging (Better UX)
                for i, (fname, content) in enumerate(files_map.items()):
                    # progress_bar.progress((i) / total_files) # Optional
                    
                    with st.status(f"Processing `{fname}`...", expanded=True) as status:
                        def update_status(msg):
                            status.write(msg)
                            
                        try:
                            # 0. Check Session Cache (UI Level)
                            existing = next((item for item in st.session_state["temp_extracted"] if item["filename"] == fname), None)
                            if existing and not force_refresh:
                                status.write("Loaded from session memory.")
                                status.update(label=f"`{fname}` Already Loaded", state="complete", expanded=False)
                                continue

                            # Pass callback to extractor
                            data, usage, error_msg = process_pdf(content, api_key, status_callback=update_status, force_refresh=force_refresh)
                            
                            if data:
                                st.session_state["temp_extracted"].append({
                                    "filename": fname,
                                    "pdf_bytes": content,
                                    "data": data
                                })
                                status.update(label=f"`{fname}` Processed Successfully!", state="complete", expanded=False)
                            else:
                                status.update(label=f"Extraction Failed for `{fname}`", state="error", expanded=True)
                                st.error(f"Error: {error_msg}")
                                
                        except Exception as e:
                            status.update(label=f"Error processing `{fname}`", state="error", expanded=True)
                            st.error(f"Exception: {e}")
                    
                    progress_bar.progress((i+1) / total_files)
                
                status_text.text("Extraction Complete! Choose an action below.")

        # Decision Section (Inside Tab 1)
        if st.session_state["temp_extracted"]:
            st.divider()
            st.subheader(f"Extraction Complete ({len(st.session_state['temp_extracted'])} files)")
            st.info("What would you like to do with these policies?")
            
            d_col1, d_col2 = st.columns(2)
            
            if d_col1.button("🔍 Review Individually (Side-by-Side)", width='stretch'):
                st.session_state["review_queue"].extend(st.session_state["temp_extracted"])
                st.session_state["temp_extracted"] = []
                st.rerun()
                
            if d_col2.button("💾 Save All to Database (Skip Review)", type="primary", width='stretch'):
                processed_count = 0
                skipped_count = 0
                updated_count = 0
                session = get_session(st.session_state.db_engine)
                service = PolicyService(session)
                
                try:
                    for item in st.session_state["temp_extracted"]:
                        # Check for duplicates before saving
                        pol_num = item['data'].get('policy', {}).get('policy_number', '')
                        existing = service.check_duplicate(pol_num) if pol_num else None
                        
                        success, msg = service.save_policy_from_extraction(item['data'])
                        
                        if success:
                            if existing:
                                updated_count += 1
                            else:
                                processed_count += 1
                        else:
                            skipped_count += 1
                            st.toast(msg, icon="⚠️")
                    
                    # Summary message
                    parts = []
                    if processed_count:
                        parts.append(f"**{processed_count}** new {'policy' if processed_count == 1 else 'policies'} saved")
                    if updated_count:
                        parts.append(f"**{updated_count}** existing {'policy' if updated_count == 1 else 'policies'} updated")
                    if skipped_count:
                        parts.append(f"**{skipped_count}** skipped (no changes)")
                    
                    st.success(" • ".join(parts) if parts else "No changes made.")
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
            
            # New Manual Inputs
            n1, n2, n3, n4, n5 = st.columns(5)
            m_um = n1.text_input("UM/UIM")
            m_med = n2.text_input("Med Pay")
            m_pip = n3.text_input("PIP")
            m_comp = n4.text_input("Comp Ded")
            m_coll = n5.text_input("Coll Ded")
            
            f1, f2, f3 = st.columns(3)
            m_gl = f1.checkbox("Has General Liabilities", value=True)
            m_auto = f2.checkbox("Has Auto Liabilities", value=True)
            m_coll = f3.checkbox("Has Full Collision", value=False)
            
            st.markdown("*Required Fields")
            submitted_manual = st.form_submit_button("💾 Save Manual Policy", type="primary", width='stretch')
            
            if submitted_manual:
                if not m_pol_num or not m_ins_name:
                    st.error("Policy Number and Insured Name are required.")
                else:
                    session = get_session(st.session_state.db_engine)
                    service = PolicyService(session)
                    try:
                        # Determine Account Type logic matches service
                        from core.services import ACCOUNT_TYPE_BY_POLICY
                        acc_type = ACCOUNT_TYPE_BY_POLICY.get(m_type, "Commercial")
                        
                        policy_payload = {
                            "carrier_name": m_carrier,
                            "naic_number": m_naic,
                            "policy_number": m_pol_num,
                            "effective_date": m_eff,
                            "expiration_date": m_exp,
                            "insured_name": m_ins_name,
                            "insured_address": m_ins_addr,
                            "insured_city": m_city,
                            "insured_state_code": m_state,
                            "insured_zip": m_zip,
                            "premium": m_premium,
                            "liability_limit": m_liab,
                            "general_liability_limit": m_gl_limit,
                            "cargo_limit": m_cargo,
                            "cargo_deductible": m_cargo_ded,
                            "um_uim_limit": m_um,
                            "med_pay_limit": m_med,
                            "pip_limit": m_pip,
                            "comp_deductible": m_comp,
                            "coll_deductible": m_coll,
                            "has_general_liability": m_gl,
                            "has_auto_liability": m_auto,
                            "has_full_collision": m_coll,
                            "policy_type": m_type,
                            "account_type": acc_type,
                            "classification_confidence": m_conf,
                            "classification_signals": ["Manual Entry"]
                        }
                        
                        policy = service.create_policy_from_dict(policy_payload)
                        
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
            # Highlights Toggle
            show_highlights = st.toggle("✨ Show Field Locations", value=False, help="Highlight extracted fields on the PDF. May affect performance.")
            
            annotations = []
            if show_highlights:
                locs = p.get('field_locations', [])
                for loc in locs:
                    page = loc.get('page_number', 1)
                    bbox = loc.get('bbox') # [ymin, xmin, ymax, xmax] 0-1000 scale
                    
                    if bbox and len(bbox) == 4:
                        # Streamlit PDF Viewer expects [x, y, width, height] in some versions or direct PDF coords?
                        # The standard format for many PDF tools is [x, y, width, height].
                        # Gemini returns [ymin, xmin, ymax, xmax] on 1000x1000 scale.
                        # We need to map this. For now, we will try a simple red rectangle wrapper.
                        # Note: st_pdf_viewer annotations support might differ. 
                        # Assuming simple rectangular highlight support:
                        annotations.append({
                            "page": page,
                            "x": bbox[1], # xmin
                            "y": bbox[0], # ymin
                            "width": bbox[3] - bbox[1], # xmax - xmin
                            "height": bbox[2] - bbox[0], # ymax - ymin
                            "color": "rgba(255, 0, 0, 0.3)",
                            "type": "rect"
                        })

            pdf_viewer(input=current_item['pdf_bytes'], width=600, height=800, annotations=annotations if show_highlights else [])
            
        with c_form:
            st.markdown("#### Verify Extracted Data")
            with st.form(key=f"review_form_{fname}"):
                c1, c2 = st.columns(2)
                
                # Metadata for Tooltips (Global fetch inside form)
                locs = p.get('field_locations', [])
                
                r_carrier = c1.text_input("Carrier", value=p.get('carrier_name', ''), help=get_source_help("carrier_name", locs))
                r_pol_num = c2.text_input("Policy Number", value=p.get('policy_number', ''), help=get_source_help("policy_number", locs))
                
                # Show Classification Info
                classification = current_item['data'].get('classification', {})
                cc1, cc2 = st.columns(2)
                r_type = cc1.text_input("Policy Type", value=classification.get('policy_type', ''), disabled=True)
                r_conf = cc2.text_input("Confidence", value=classification.get('confidence', ''), disabled=True)
                
                c3, c4 = st.columns(2)
                
                # Auto-fill NAIC if missing
                current_naic = p.get('naic_number', '')
                if not current_naic:
                    current_naic = get_naic_for_carrier(p.get('carrier_name', ''))
                
                # Metadata for Tooltips
                locs = p.get('field_locations', [])
                
                r_naic = c3.text_input("NAIC Code", value=current_naic)
                
                # Premium with Audit & Tooltip
                prem_help = get_source_help("premium", locs)
                audit_meta = p.get("premium_audit", {})
                
                # Premium Label with Indicator
                prem_label = "Premium"
                if audit_meta.get("confidence") == "low":
                    prem_label += " ⚠️ (Check Split/Installment)"
                elif audit_meta.get("confidence") == "high":
                    prem_label += " ✅"

                r_premium = c3.text_input(prem_label, value=p.get('premium', ''), help=prem_help)
                
                if audit_meta and audit_meta.get("confidence") == "low":
                    st.caption(f"**Audit Flag:** {audit_meta.get('flag')}")
                r_eff = c4.text_input("Effective Date", value=p.get('effective_date', ''), help=get_source_help("effective_date", locs))
                r_exp = c4.text_input("Expiration Date", value=p.get('expiration_date', ''), help=get_source_help("expiration_date", locs))
                
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
                
                # New Review Inputs
                st.markdown("##### Additional Coverages")
                rc1, rc2, rc3, rc4, rc5 = st.columns(5)
                r_um = rc1.text_input("UM/UIM", value=p.get('um_uim_limit', ''))
                r_med = rc2.text_input("Med Pay", value=p.get('med_pay_limit', ''))
                r_pip = rc3.text_input("PIP", value=p.get('pip_limit', ''))
                r_comp = rc4.text_input("Comp Ded", value=p.get('comp_deductible', ''))
                r_coll = rc5.text_input("Coll Ded", value=p.get('coll_deductible', ''))
                
                r_gl = st.checkbox("Has GL", value=p.get('has_general_liability', True))
                r_auto = st.checkbox("Has Auto", value=p.get('has_auto_liability', True))
                r_status = st.selectbox("Status", ["Active", "Pending", "Quote", "Expired"], index=0)

                st.divider()
                st.markdown("#### Detailed Inventory (Editable)")
                t1, t2, t3, t4 = st.tabs(["🚙 Vehicles", "👤 Drivers", "🛡️ Coverages", "🏢 Additional Interests"])

                with t1:
                    v_data = current_item['data'].get('vehicles', [])
                    v_df = pd.DataFrame(v_data)
                    # Helper to ensures columns exist
                    for col in ["year", "make", "model", "vin", "type", "gvw"]:
                        if col not in v_df.columns: v_df[col] = None
                    
                    edited_v = st.data_editor(
                        v_df,
                        num_rows="dynamic",
                        column_config={
                            "year": st.column_config.NumberColumn("Year", min_value=1900, max_value=2030, format="%d"),
                            "make": st.column_config.TextColumn("Make", required=True),
                            "model": st.column_config.TextColumn("Model"),
                            "vin": st.column_config.TextColumn("VIN", max_chars=17, validate=VIN_REGEX),
                            "type": st.column_config.SelectboxColumn("Type", options=VEHICLE_TYPES),
                            "gvw": st.column_config.NumberColumn("GVW", format="%d")
                        },
                        width='stretch',
                        key=f"edt_v_{fname}"
                    )

                with t2:
                    d_data = current_item['data'].get('drivers', [])
                    d_df = pd.DataFrame(d_data)
                    for col in ["full_name", "license_number", "is_excluded"]:
                        if col not in d_df.columns: d_df[col] = None
                        
                    edited_d = st.data_editor(
                        d_df,
                        num_rows="dynamic",
                        column_config={
                            "full_name": st.column_config.TextColumn("Driver Name", required=True),
                            "license_number": st.column_config.TextColumn("License #"),
                            "is_excluded": st.column_config.CheckboxColumn("Excluded?", default=False)
                        },
                        width='stretch',
                        key=f"edt_d_{fname}"
                    )
                
                with t3:
                    c_data = current_item['data'].get('coverages', [])
                    # Flatten current extracted limits for editor if needed or present as is
                    c_rows = []
                    for c in c_data:
                         row = {
                             "type": c.get('display_name') or c.get('type'),
                             "coverage_code": c.get('coverage_code'),
                             "per_occurrence": c.get('limits', {}).get('per_occurrence'),
                             "aggregate": c.get('limits', {}).get('aggregate'),
                             "combined_single_limit": c.get('limits', {}).get('combined_single_limit'),
                             "deductible": c.get('deductible')
                         }
                         c_rows.append(row)
                    
                    c_df = pd.DataFrame(c_rows)
                    if c_df.empty:
                        c_df = pd.DataFrame(columns=["type", "coverage_code", "per_occurrence", "aggregate", "combined_single_limit", "deductible"])

                    edited_c = st.data_editor(
                        c_df,
                        num_rows="dynamic",
                        column_config={
                            "type": st.column_config.TextColumn("Coverage Type", required=True),
                            "coverage_code": st.column_config.TextColumn("Code"),
                            "per_occurrence": st.column_config.NumberColumn("Occ Limit", format="$%d"),
                            "aggregate": st.column_config.NumberColumn("Agg Limit", format="$%d"),
                            "combined_single_limit": st.column_config.NumberColumn("CSL", format="$%d"),
                            "deductible": st.column_config.NumberColumn("Ded", format="$%d"),
                        },
                        width='stretch',
                        key=f"edt_c_{fname}"
                    )

                with t4:
                    ai_data = current_item['data'].get('additional_interests', [])
                    ai_df = pd.DataFrame(ai_data)
                    for col in ["name", "address", "interest_type"]:
                        if col not in ai_df.columns: ai_df[col] = None

                    edited_ai = st.data_editor(
                        ai_df,
                        num_rows="dynamic",
                        column_config={
                            "name": st.column_config.TextColumn("Entity Name", required=True),
                            "address": st.column_config.TextColumn("Address"),
                            "interest_type": st.column_config.SelectboxColumn(
                                "Interest Type", 
                                options=INTEREST_TYPES
                            )
                        },
                        width='stretch',
                        key=f"edt_ai_{fname}"
                    )

                st.markdown("---")
                
                # Duplicate detection warning
                b_col_warn = st.container()
                
                b_col1, b_col2, b_col3 = st.columns([1, 1, 1])
                saved = b_col1.form_submit_button("💾 Save", type="secondary")
                save_next = b_col2.form_submit_button("💾⏩ Save & Next", type="primary")
                discarded = b_col3.form_submit_button("🗑️ Discard")
                
                if saved or save_next:
                    session = get_session(st.session_state.db_engine)
                    service = PolicyService(session)
                    try:
                        # Check for duplicate before saving
                        existing = service.check_duplicate(r_pol_num)
                        if existing:
                            b_col_warn.warning(
                                f"⚡ **Duplicate Detected:** Policy `{r_pol_num}` already exists "
                                f"(Insured: {existing.insured_name}, Carrier: {existing.carrier_name}). "
                                f"Saving will **update** the existing record."
                            )
                        
                        # Construct flattened dictionary for factory
                        policy_payload = {
                            "carrier_name": r_carrier,
                            "naic_number": r_naic,
                            "policy_number": r_pol_num,
                            "effective_date": r_eff, # Factory handles parsing
                            "expiration_date": r_exp,
                            "insured_name": r_ins_name,
                            "insured_address": r_ins_addr,
                            "insured_city": r_ins_city,
                            "insured_state_code": r_ins_state,
                            "insured_zip": r_ins_zip,
                            "liability_limit": r_liab,
                            "general_liability_limit": r_gl_limit,
                            "cargo_limit": r_cargo,
                            "cargo_deductible": r_cargo_ded,
                            "um_uim_limit": r_um,
                            "med_pay_limit": r_med,
                            "pip_limit": r_pip,
                            "comp_deductible": r_comp,
                            "coll_deductible": r_coll,
                            "has_general_liability": r_gl,
                            "has_auto_liability": r_auto,
                            "account_type": p.get('account_type'),
                            "policy_type": classification.get('policy_type'),
                            "classification_confidence": classification.get('confidence'),
                            "classification_signals": classification.get('signals', []),
                            "business_name": p.get('business_name'),
                            "premium": r_premium,
                            "financial_responsibility_name": p.get('financial_responsibility_name'),
                            "has_full_collision": p.get('has_full_collision'),
                            "status": r_status,
                            
                            # Collections (Editor DFs converted to list of dicts)
                            "vehicles": edited_v.to_dict('records') if not edited_v.empty else [],
                            "drivers": edited_d.to_dict('records') if not edited_d.empty else [],
                            "coverages": edited_c.to_dict('records') if not edited_c.empty else [],
                            "additional_interests": edited_ai.to_dict('records') if not edited_ai.empty else []
                        }
                        
                        policy = service.create_policy_from_dict(policy_payload)

                        # We should use service.save_policy_object
                        success, msg = service.save_policy_object(policy)
                        
                        if success:
                            st.toast(f"✅ Saved {r_pol_num}!")
                            st.session_state["review_queue"].pop(0)
                            st.rerun()
                        else:
                            st.toast(f"⚠️ Could not save: {msg}", icon="⚠️")
                            # If individual save (not next), maybe we show error persistent? 
                            # Toast is fine for now as it doesn't block flow.
                        
                    except Exception as e:
                        st.toast(f"❌ Save failed: {e}", icon="❌")
                    finally:
                        session.close()
                
                if discarded:
                    st.session_state["review_queue"].pop(0)
                    st.rerun()
    else:
        if "review_queue" in st.session_state and isinstance(st.session_state["review_queue"], list):
             st.info("No policies pending review.")
