import streamlit as st
import pandas as pd
from core.services import PolicyService
from core.database import get_session
from utils.exporter import create_excel_report

from views.edit_dialog import edit_policy_dialog
from core.constants import POLICY_SEARCH_PAGE_LIMIT, POLICY_DELETE_CANDIDATE_LIMIT

def page_database(api_key):
    st.title("🗃️ Policy Database")
    st.markdown("Search, view, and edit all previously extracted insurance data.")
    
    session = get_session(st.session_state.db_engine)
    service = PolicyService(session)
    
    try:
        col_search, _ = st.columns([3, 1])
        with col_search:
            search_query = st.text_input(
                "🔍 Search by Policy # or Insured Name",
                "",
                key="db_policy_search",
                help=f"Server-side search. Leave empty to show the {POLICY_SEARCH_PAGE_LIMIT} most recent policies.",
            )
        term = search_query.strip() or None
        policies = service.search_policies(term, limit=POLICY_SEARCH_PAGE_LIMIT)
        total_match = service.count_policies(term)
        if total_match > len(policies):
            st.caption(
                f"Showing {len(policies)} of {total_match} matching policies. Refine your search to narrow results."
            )
        elif term and policies and total_match <= len(policies):
            st.caption(
                f"{len(policies)} matching polic{'y' if len(policies) == 1 else 'ies'} (up to {POLICY_SEARCH_PAGE_LIMIT} shown)."
            )

        if not policies:
            st.info("No records found in database for this search.")
            return

        with st.expander("💬 Chat with your Data (AI Search)", expanded=False):
            st.info("Ask complex questions like: 'Show me all policies with premium over $5000' or 'List all Mack trucks'.")
            
            c_chat_in, c_chat_btn = st.columns([4, 1])
            with c_chat_in:
                user_question = st.text_input("Ask a question about your policies:", key="data_chat_input", label_visibility="collapsed", placeholder="e.g. Policies expiring next month...")
            with c_chat_btn:
                ask_submitted = st.button("Ask AI", type="secondary", width='stretch')

            if "ai_search_results" not in st.session_state:
                st.session_state.ai_search_results = None
                st.session_state.ai_debug_sql = None

            if ask_submitted and user_question:
                with st.spinner("Analyzing Database Schema & Generating SQL..."):
                        results, debug_sql = service.ask_your_data(user_question, api_key)
                        st.session_state.ai_search_results = results
                        st.session_state.ai_debug_sql = debug_sql
            
            if st.session_state.ai_search_results is not None:
                results = st.session_state.ai_search_results
                debug_sql = st.session_state.ai_debug_sql
                
                if results:
                    st.success(f"Found {len(results)} results")
                    
                    with st.expander("🛠️ View Generated SQL code"):
                        st.code(debug_sql, language="sql")

                    res_df = pd.DataFrame(results)
                    
                    if not res_df.empty:
                        res_df.columns = [col.replace('_', ' ').title() for col in res_df.columns]
                        
                        show_all_ai_cols = st.checkbox("Show all raw columns", value=False, key="ai_show_all")
                        
                        display_df = res_df
                        should_fit_cols = False
                        
                        if not show_all_ai_cols:
                            whitelist = [
                                "Policy Number", "Insured Name", "Carrier Name", "Status", 
                                "Effective Date", "Expiration Date", "Premium", "Liability Limit"
                            ]
                            
                            present_whitelist = [c for c in whitelist if c in res_df.columns]
                            
                            if len(present_whitelist) > 0:
                                display_df = res_df[present_whitelist]
                                should_fit_cols = True
                            else:
                                priority_cols = [c for c in res_df.columns if "Id" not in c and "Signal" not in c]
                                if priority_cols:
                                    display_df = res_df[priority_cols]
                                    should_fit_cols = True

                        from st_aggrid import AgGrid, GridOptionsBuilder
                        gb_res = GridOptionsBuilder.from_dataframe(display_df)
                        gb_res.configure_default_column(sortable=True, filterable=True, resizable=True)
                        gb_res.configure_pagination(paginationAutoPageSize=False, paginationPageSize=10)
                        res_grid_options = gb_res.build()
                        
                        AgGrid(
                            display_df,
                            gridOptions=res_grid_options,
                            height=300,
                            theme='streamlit',
                            fit_columns_on_grid_load=should_fit_cols,
                            key="ai_search_results_grid"
                        )
                    else:
                        st.warning("Query returned empty result.")
                else:
                     st.warning("Query executed successfully but returned no results.")
                     with st.expander("🛠️ View Generated SQL code"):
                        st.code(debug_sql, language="sql")
            elif ask_submitted:
                 pass 

        
        st.divider()

        data_list = []
        export_data = []
        def parse_limit(val_str):
            if not val_str:
                return 0.0
            s = str(val_str).lower().strip()
            multiplier = 1.0
            if "k" in s:
                multiplier = 1000.0
            elif "m" in s:
                multiplier = 1000000.0
            import re
            clean = re.sub(r"[^\d.]", "", s)
            try:
                return float(clean) * multiplier
            except ValueError:
                return 0.0

        for p in policies:
            completeness = PolicyService.compute_completeness_score(
                {
                    "carrier_name": p.carrier_name,
                    "policy_number": p.policy_number,
                    "effective_date": str(p.effective_date) if p.effective_date else None,
                    "expiration_date": str(p.expiration_date) if p.expiration_date else None,
                    "insured_name": p.insured_name,
                    "liability_limit": p.liability_limit,
                    "naic_number": p.naic_number,
                    "insured_address": p.insured_address,
                    "cargo_limit": p.cargo_limit,
                },
                p.document_type,
            )
            eligibility_status = "✅ Eligible"
            eligibility_text = "Eligible"
            liab_val = parse_limit(p.liability_limit)
            cargo_val = parse_limit(p.cargo_limit)
            if liab_val < 1000000 or cargo_val < 100000:
                eligibility_status = "⚠️ Not Eligible"
                eligibility_text = "Not eligible"

            v_types = [v.vehicle_type for v in p.vehicles if v.vehicle_type]
            v_types_unique = sorted(list(set(v_types)))
            v_types_str = ", ".join(v_types_unique) if v_types_unique else "N/A"

            status_raw = p.status if p.status else "Active"
            status_icon = "✅" if status_raw.lower() == "active" else "⚠️"
            status_display = f"{status_icon} {status_raw}"
            status_text = "Active" if status_raw.lower() == "active" else f"Non-active ({status_raw})"

            data_list.append({
                "ID": p.id,
                "Status": status_display,
                "StatusText": status_text,
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
                "Vehicle Types": v_types_str,
                "Drivers": len(p.drivers),
                "Effective": p.effective_date.strftime("%Y-%m-%d") if p.effective_date else "N/A",
                "Expiration": p.expiration_date.strftime("%Y-%m-%d") if p.expiration_date else "N/A",
                "Premium": p.premium,
                "Auto Liability": p.liability_limit,
                "Cargo": p.cargo_limit,
                "Cargo Ded": p.cargo_deductible,
                "GL Limit": p.general_liability_limit,
                "UM/UIM": p.um_uim_limit,
                "Med Pay": p.med_pay_limit,
                "Comp Ded": p.comp_deductible,
                "Coll Ded": p.coll_deductible,
                "Has GL": "✅" if p.has_general_liability else "❌",
                "Comp/Coll": "✅" if p.has_full_collision else "❌",
                "Expedite": eligibility_status,
                "Eligibility": eligibility_text,
                "Type": p.policy_type,
                "Confidence": p.classification_confidence,
                "Completeness": f"{completeness['score']} ({'ready' if completeness['coi_ready'] else 'review'})",
            })

            dict_data = {
                "policy": {
                    "carrier_name": p.carrier_name,
                    "naic_number": p.naic_number,
                    "policy_number": p.policy_number,
                    "effective_date": str(p.effective_date),
                    "expiration_date": str(p.expiration_date),
                    "account_type": p.account_type,
                    "policy_type": p.policy_type,
                    "status": status_raw,
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
                    "vehicle_types_summary": v_types_str,
                    "cargo_limit": p.cargo_limit,
                    "cargo_deductible": p.cargo_deductible,
                    "has_full_collision": p.has_full_collision,
                    "has_general_liability": p.has_general_liability,
                    "has_auto_liability": p.has_auto_liability,
                },
            }
            dict_data["vehicles"] = [
                {
                    "year": v.year,
                    "make": v.make,
                    "model": v.model,
                    "vin": v.vin,
                    "gvw": v.gvw,
                    "type": v.vehicle_type,
                    "chassis": v.chassis,
                    "body": v.body,
                }
                for v in p.vehicles
            ]
            dict_data["coverages"] = [
                {"type": c.type, "coverage_code": c.coverage_code, "family": c.family} for c in p.coverages
            ]
            dict_data["drivers"] = [
                {"full_name": d.full_name, "license_number": d.license_number} for d in p.drivers
            ]
            dict_data["additional_interests"] = [
                {"name": a.name, "address": a.address} for a in p.additional_interests
            ]
            export_data.append(dict_data)

        if not data_list:
            st.warning("No policy rows to display.")
            return

        from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode

        df = pd.DataFrame(data_list)

        all_cols = list(df.columns)
        strict_defaults = [
            "Status",
            "StatusText",
            "Policy#",
            "Carrier",
            "Insured",
            "Effective",
            "Premium",
            "Auto Liability",
            "Cargo",
            "Vehicles",
            "Drivers",
            "Eligibility",
        ]
        default_cols = [c for c in strict_defaults if c in all_cols]

        c_title, c_popover = st.columns([6, 1])
        with c_title:
            st.subheader("📋 Policy Records")

        with c_popover:
            with st.popover("⚙️ Columns"):
                st.markdown("**Select Columns to Show**")
                cols_to_show = st.multiselect(
                    "Visible Columns", all_cols, default=default_cols, label_visibility="collapsed"
                )

        if not cols_to_show:
            st.warning("Please select at least one column to display.")
            return

        df_visible = df[cols_to_show]

        gb = GridOptionsBuilder.from_dataframe(df_visible)
        gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
        gb.configure_side_bar()
        gb.configure_default_column(
            groupable=True,
            valueFormatter="x.toLocaleString()",
            filterable=True,
            sortable=True,
            resizable=True,
        )
        gb.configure_selection("single", use_checkbox=True)
        gridOptions = gb.build()

        grid_response = AgGrid(
            df,
            gridOptions=gridOptions,
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            fit_columns_on_grid_load=False,
            height=600,
            width="100%",
            theme="streamlit",
        )

        selected = grid_response["selected_rows"]

        st.divider()
        c_foot_1, c_foot_2, c_foot_3 = st.columns([1, 1, 2])

        with c_foot_1:
            excel_all = create_excel_report(export_data)
            st.download_button(
                "📥 Export Current View",
                data=excel_all,
                file_name="insurance_database.xlsx",
                width="stretch",
            )

        with c_foot_2:
            with open("insurance_data.db", "rb") as f:
                st.download_button(
                    "💾 Backup Database",
                    data=f.read(),
                    file_name="insurance_data.db",
                    width="stretch",
                )

        with c_foot_3:
            has_selection = False
            sel_row = None
            if selected is not None:
                if isinstance(selected, pd.DataFrame) and not selected.empty:
                    has_selection = True
                    sel_row = selected.iloc[0]
                elif isinstance(selected, list) and len(selected) > 0:
                    has_selection = True
                    sel_row = selected[0]

            if has_selection:
                p_id = sel_row.get("ID")
                target_pol = next((p for p in policies if p.id == p_id), None)
                if target_pol:
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button(
                            f"✏️ Edit Policy #{target_pol.policy_number}",
                            type="primary",
                            width="stretch",
                        ):
                            edit_policy_dialog(target_pol, service)
                    with b2:
                        if st.button("📄 Open in Create COI", width="stretch"):
                            st.session_state["nav_request"] = "Create COI"
                            st.session_state["coi_policy_id"] = target_pol.id
                            st.rerun()
            else:
                st.button("✏️ Select a policy above to edit", disabled=True, width="stretch")

        if not term:
            st.divider()
            with st.expander("🗑️ Danger Zone: Delete Policies"):
                del_candidates = service.search_policies(None, limit=POLICY_DELETE_CANDIDATE_LIMIT)
                policy_map_del = {
                    f"{p.policy_number} | {p.insured_name}": p for p in del_candidates
                }
                selected_to_delete = st.multiselect(
                    f"Select policies to delete (up to {POLICY_DELETE_CANDIDATE_LIMIT} most recent shown)",
                    options=list(policy_map_del.keys()),
                )
                confirm_numbers = st.text_input(
                    "Type the policy numbers to confirm, comma-separated (same set as selected, any order)",
                    key="db_delete_confirm_numbers",
                    help="Must match exactly the policy numbers of your selection.",
                )

                def _norm_policy_confirm(s: str) -> str:
                    parts = [x.strip() for x in s.replace(";", ",").split(",") if x.strip()]
                    return ",".join(sorted(parts))

                expected = ""
                if selected_to_delete:
                    nums = [policy_map_del[k].policy_number for k in selected_to_delete]
                    expected = _norm_policy_confirm(",".join(nums))
                typed = _norm_policy_confirm(confirm_numbers)
                delete_ok = bool(selected_to_delete) and typed == expected and expected

                if selected_to_delete and not delete_ok:
                    st.caption("Confirmation must list the same policy numbers as the selection.")

                if st.button(
                    f"Permanently delete {len(selected_to_delete)} item(s)",
                    type="primary",
                    disabled=not delete_ok,
                ):
                    for k in selected_to_delete:
                        pol = policy_map_del[k]
                        service.delete_policy(pol)
                    st.success("Deleted!")
                    st.rerun()

    finally:
        session.close()
