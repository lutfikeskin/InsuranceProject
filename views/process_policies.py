from __future__ import annotations

import copy
import streamlit as st
import pandas as pd
from core.constants import VEHICLE_TYPES, INTEREST_TYPES, VIN_REGEX
import json
from core.services import PolicyService
from datetime import date
from core.database import get_session, Customer
from core.customer_resolver import CustomerResolver
from modules.extraction import process_pdf
from modules.extraction.pipeline import POLICY_TYPE_ENUM
from utils.naic_utils import get_naic_for_carrier
from concurrent.futures import ThreadPoolExecutor, as_completed
from streamlit_pdf_viewer import pdf_viewer

from views.ui_utils import (
    CONFIDENCE_LEGEND_CAPTION,
    build_confidence_map,
    confidence_label as _confidence_label,
)

MAX_PARALLEL_WORKERS = 3

RELATIONSHIP_DISPLAY = {
    "renewal": ("🔄", "Possible Renewal"),
    "canceled_replaced": ("📋", "Possible Replacement"),
    "rewrite": ("✏️", "Possible Rewrite"),
    "same_customer_new_policy": ("👤", "Same Customer, New Policy"),
}


def _carrier_display(carrier_name: str | None, underwriter_name: str | None) -> str:
    carrier = (carrier_name or "").strip()
    underwriter = (underwriter_name or "").strip()
    if underwriter and carrier and underwriter.lower() != carrier.lower():
        return f"{carrier} ({underwriter})"
    return carrier or underwriter or ""


def _dataframe_to_record_list(df: pd.DataFrame) -> list:
    if df is None or df.empty:
        return []
    out = []
    for rec in df.to_dict("records"):
        row = {}
        for k, v in rec.items():
            if v is None:
                row[k] = None
            elif isinstance(v, float) and pd.isna(v):
                row[k] = None
            else:
                row[k] = v
        out.append(row)
    return out


def _coverages_from_editor_rows(c_data: list, edited_c: pd.DataFrame) -> list:
    """Rebuild extraction-style coverage dicts from the flat review data_editor rows."""
    if edited_c is None or edited_c.empty:
        return []
    rows = edited_c.to_dict("records")
    out = []
    for idx, row in enumerate(rows):
        t = (row.get("type") or "").strip()
        if not t:
            continue
        orig = c_data[idx] if idx < len(c_data) and isinstance(c_data[idx], dict) else {}
        limits = dict(orig.get("limits") or {})
        for k in ("per_occurrence", "aggregate", "combined_single_limit", "deductible"):
            v = row.get(k)
            if v is not None and v != "":
                limits[k] = v
        item = {k: v for k, v in orig.items() if k not in ("limits", "display_name", "type")}
        item["display_name"] = t
        item["type"] = t
        item["coverage_code"] = row.get("coverage_code")
        item["limits"] = limits
        if row.get("deductible") is not None and row.get("deductible") != "":
            item["deductible"] = row.get("deductible")
        out.append(item)
    return out


def _stringify_diff_value(value):
    if isinstance(value, (list, tuple)):
        return json.dumps(value, default=str)
    if value is None:
        return ""
    return str(value)


def _render_duplicate_preview(duplicate_info: dict, diff_preview: dict | None):
    status = duplicate_info.get("status")
    existing = duplicate_info.get("existing_policy") or {}
    reason = duplicate_info.get("reason") or ""

    if status == "no_match":
        st.success("No existing policy has this policy number. Saving will create a new policy.")
        return
    if status == "missing_policy_number":
        st.warning("Policy number is missing. Add a policy number before saving when possible.")
        return
    if status == "possible_related_policy":
        st.info("No policy-number duplicate found, but an existing policy may be related.")
    if status == "exact_number_carrier_conflict":
        st.warning(
            "Policy number already exists, but key identity fields differ. Review carefully before updating."
        )
    elif status == "exact_policy_match":
        st.warning("Policy number already exists. Saving will update the current policy.")

    if existing:
        carrier = _carrier_display(existing.get("carrier_name"), existing.get("underwriter_name"))
        st.caption(
            f"Existing: `{existing.get('policy_number')}` | "
            f"{existing.get('insured_name') or 'Unknown insured'} | "
            f"{carrier or 'Unknown carrier'} | "
            f"{existing.get('effective_date') or '?'} to {existing.get('expiration_date') or '?'}"
        )
    if reason:
        st.caption(reason)

    if status == "possible_related_policy" or not diff_preview:
        return
    changes = diff_preview.get("changes") or []
    if not changes:
        st.info("No field-level changes detected against the existing policy.")
        return
    with st.expander(f"Preview changes before updating ({len(changes)} change groups)", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "field": c.get("field"),
                        "existing": _stringify_diff_value(c.get("old_value")),
                        "incoming": _stringify_diff_value(c.get("new_value")),
                    }
                    for c in changes
                ]
            ),
            hide_index=True,
            width='stretch',
        )


def _compute_parallel_workers(total_files: int) -> int:
    """
    Adaptive worker sizing:
    - small batches keep lower concurrency to avoid bursty rate limits
    - larger batches scale up to a conservative cap
    """
    if total_files <= 2:
        return 2
    if total_files <= 6:
        return 2
    return MAX_PARALLEL_WORKERS


def _friendly_extraction_error(message: str | None) -> str:
    if not message:
        return "Extraction failed with no detail. Try Force Refresh or a different PDF."
    m = str(message)
    if "Daily Quota Exceeded" in m or "STOPS:" in m:
        return (
            "Daily API budget was reached. Increase DEFAULT_DAILY_BUDGET in core/constants.py "
            "or reset usage under Settings, then try again."
        )
    if "JSON" in m or "parse" in m.lower() or "Extraction Error" in m:
        return (
            "The model response could not be parsed. Enable **Force Refresh (Bypass Cache)** "
            "and retry; if it persists, try one file at a time."
        )
    if "Quota" in m or "quota" in m:
        return "API quota or rate limit issue. Wait a moment, check your billing, and retry."
    if "API Key" in m or "api" in m.lower() and "key" in m.lower():
        return "API key problem. Add or update your Gemini key in Settings."
    if "invalid policy type" in m.lower():
        return "Invalid policy type selection. Choose a type from the list or use Auto-detect."
    return m


def _policy_type_selectbox_options() -> tuple[list[str], dict[str, str | None]]:
    """Streamlit option strings mapped to API policy_type or None for auto-detect."""
    manual = [pt for pt in POLICY_TYPE_ENUM if pt != "unknown"]
    labels = ["Auto-detect (recommended)"] + [pt.replace("_", " ").title() for pt in manual]
    label_to_value: dict[str, str | None] = {labels[0]: None}
    for pt, lbl in zip(manual, labels[1:]):
        label_to_value[lbl] = pt
    return labels, label_to_value


def _process_one_pdf(
    fname: str,
    content: bytes,
    api_key: str,
    force_refresh: bool,
    user_policy_type: str | None,
):
    """Worker for parallel extraction; each call uses its own stack (process_pdf creates its own client)."""
    try:
        data, usage, error_msg = process_pdf(
            content,
            api_key,
            status_callback=None,
            force_refresh=force_refresh,
            user_policy_type=user_policy_type,
        )
        return fname, data, usage, error_msg, None
    except Exception as e:
        return fname, None, None, None, str(e)


def render_related_policy(match, current_item, service):
    existing = match.get("policy") or {}
    rel_type = match.get("relationship_type")
    confidence = float(match.get("score") or 0.0)
    icon, label = RELATIONSHIP_DISPLAY.get(rel_type, ("🔗", "Related"))
    existing_id = existing.get("id")

    new_p = current_item["data"].get("policy", {})
    expanded_default = confidence > 0.8
    existing_carrier = _carrier_display(
        existing.get("carrier_name"), existing.get("underwriter_name")
    )
    incoming_carrier = _carrier_display(
        new_p.get("carrier_name"), new_p.get("underwriter_name")
    )
    with st.expander(
        f"{icon} {label} — `{existing.get('policy_number')}` "
        f"({existing.get('insured_name')}) — "
        f"{int(confidence * 100)}% match",
        expanded=expanded_default,
    ):
        c1, c2 = st.columns(2)
        c1.markdown(
            f"**Existing**\n\n"
            f"Number: `{existing.get('policy_number')}`\n\n"
            f"Carrier: {existing_carrier}\n\n"
            f"Insured: {existing.get('insured_name')}\n\n"
            f"Type: {existing.get('policy_type')}\n\n"
            f"Effective: {existing.get('effective_date')}\n\n"
            f"Expires: {existing.get('expiration_date')}\n\n"
            f"Status: {existing.get('policy_status', 'unknown')}"
        )
        c2.markdown(
            f"**Incoming**\n\n"
            f"Number: `{new_p.get('policy_number')}`\n\n"
            f"Carrier: {incoming_carrier}\n\n"
            f"Insured: {new_p.get('insured_name')}\n\n"
            f"Type: {current_item['data'].get('classification', {}).get('policy_type')}\n\n"
            f"Effective: {new_p.get('effective_date')}\n\n"
            f"Expires: {new_p.get('expiration_date')}"
        )

        st.divider()
        b1, _, b3 = st.columns(3)

        if rel_type == "renewal":
            if b1.button("🔄 Save as Renewal", key=f"act_renewal_{existing_id}"):
                success, msg = service.save_with_relationship(
                    current_item["data"], existing_id, "renewal"
                )
                if success:
                    st.success("Saved as renewal")
                    st.session_state["review_queue"].pop(0)
                    st.rerun()
                else:
                    st.warning(msg or "Save failed")

        elif rel_type in ("canceled_replaced", "rewrite"):
            if b1.button("📋 Save as Replacement", key=f"act_replace_{existing_id}"):
                success, msg = service.save_with_relationship(
                    current_item["data"], existing_id, rel_type
                )
                if success:
                    st.success("Saved as replacement, old policy marked replaced")
                    st.session_state["review_queue"].pop(0)
                    st.rerun()
                else:
                    st.warning(msg or "Save failed")

        elif rel_type == "same_customer_new_policy":
            if b1.button("👤 Link as Same Customer", key=f"act_link_{existing_id}"):
                success, msg = service.save_with_relationship(
                    current_item["data"], existing_id, "same_customer_new_policy"
                )
                if success:
                    st.success("Saved and linked as same customer")
                    st.session_state["review_queue"].pop(0)
                    st.rerun()
                else:
                    st.warning(msg or "Save failed")

        if b3.button(
            "Ignore",
            key=f"act_ignore_{existing_id}",
            help="Don't link, save as separate",
        ):
            current_item["data"]["_related_policy_candidates"] = [
                m
                for m in (current_item["data"].get("_related_policy_candidates") or [])
                if (m.get("policy") or {}).get("id") != existing_id
            ]
            st.rerun()


def page_process_policies(api_key):
    st.title("📤 Process Policies")
    st.markdown("Upload policies, review the extraction, and save to your database.")
    
    if "review_queue" not in st.session_state:
        st.session_state["review_queue"] = []
    
    if "temp_extracted" not in st.session_state:
        st.session_state["temp_extracted"] = []
    if "batch_telemetry_today" not in st.session_state:
        st.session_state["batch_telemetry_today"] = {
            "day": date.today().isoformat(),
            "files": 0,
            "cache_hits": 0,
            "retries": 0,
            "errors": 0,
        }
        
    tab_upload, tab_manual = st.tabs(["📄 Upload & Extract", "✍️ Manual Entry"])

    def get_source_help(field_name, field_locations):
        """Helper to generate tooltip text for a field."""
        if not field_locations:
            return None
        formatted_key = field_name
        for loc in field_locations:
             if loc.get("field") == field_name:
                 page = loc.get("page_number")
                 return f"Found on Page {page}"
        return None

    # _confidence_label and build_confidence_map were lifted to views/ui_utils.py
    # so future review screens render the same badge convention. The legend
    # caption rendered in Step 2 explains the symbols.
    _build_confidence_map = build_confidence_map

    with tab_upload:
        expanded_upload = not (bool(st.session_state["review_queue"]) or bool(st.session_state["temp_extracted"]))
        
        with st.expander("Step 1: Upload & Extract", expanded=expanded_upload):
            if not api_key:
                 st.warning("⚠️ Access Restricted: Please add your Gemini API Key in Settings to proceed.")

            _ptype_labels, _ptype_map = _policy_type_selectbox_options()
            preferred_default = "Commercial Auto"
            default_index = (
                _ptype_labels.index(preferred_default)
                if preferred_default in _ptype_labels
                else 0
            )
            policy_type_label = st.selectbox(
                "Policy type",
                options=_ptype_labels,
                index=default_index,
                help="Auto-detect runs classification then extraction (two model calls). "
                "A manual type skips classification and uses one extraction call with a scoped coverage registry.",
            )
            user_policy_type = _ptype_map[policy_type_label]

            uploaded_files = st.file_uploader("Drop PDF files here", type=["pdf"], accept_multiple_files=True)
            
            if not uploaded_files:
                st.info("👆 **Tip:** You can select multiple PDF files at once. The AI will process them sequentially.")
                
            opt_c1, opt_c2 = st.columns(2)
            with opt_c1:
                parallel_extract = st.checkbox(
                    "Parallel extraction (adaptive max 2-3 files at a time)",
                    value=False,
                    help="Faster for many PDFs; retry policy is handled centrally in extraction pipeline.",
                )
            with opt_c2:
                force_refresh = st.checkbox(
                    "Force Refresh (Bypass Cache)",
                    value=False,
                    help="Re-process files even if a cached result exists.",
                )

            if st.button("Start Extraction", type="primary") and uploaded_files:
                if not api_key:
                    st.error("Missing Gemini API Key. Please add it in Settings.")
                    return

                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total_files = len(uploaded_files)
                files_map = {f.name: f.getvalue() for f in uploaded_files}
                batch_rows = []

                def _record_batch(fname, ok, detail, source="", retries=0, error_class=""):
                    batch_rows.append(
                        {
                            "filename": fname,
                            "status": "ok" if ok else "error",
                            "detail": detail,
                            "source": source,
                            "retries": retries,
                            "error_class": error_class,
                        }
                    )

                def _classify_error(message: str | None) -> str:
                    m = (message or "").lower()
                    if any(t in m for t in ["quota", "rate limit", "429", "resource exhausted"]):
                        return "rate_limit_or_quota"
                    if "timeout" in m:
                        return "timeout"
                    if "api key" in m or ("api" in m and "key" in m):
                        return "auth"
                    if "json" in m or "parse" in m:
                        return "parse"
                    if m:
                        return "other"
                    return ""

                if parallel_extract and total_files > 1:
                    done = 0
                    worker_count = _compute_parallel_workers(total_files)
                    status_text.text(f"Parallel mode: using {worker_count} workers with retry/backoff.")
                    with ThreadPoolExecutor(max_workers=worker_count) as pool:
                        futures = {
                            pool.submit(
                                _process_one_pdf,
                                fn,
                                files_map[fn],
                                api_key,
                                force_refresh,
                                user_policy_type,
                            ): fn
                            for fn in files_map
                        }
                        for fut in as_completed(futures):
                            fname, data, usage, error_msg, exc = fut.result()
                            retries_used = int((usage or {}).get("llm_retries", 0))
                            done += 1
                            progress_bar.progress(done / total_files)
                            if exc:
                                st.error(f"`{fname}`: {_friendly_extraction_error(exc)}")
                                _record_batch(
                                    fname,
                                    False,
                                    exc,
                                    retries=retries_used,
                                    error_class=_classify_error(exc),
                                )
                            elif data:
                                if usage and usage.get("source") == "cache":
                                    st.info(f"`{fname}`: loaded from extraction cache (no API charge).")
                                rejected = len(data.get("extraction_audit", {}).get("rejected_coverages", []))
                                if rejected:
                                    st.warning(f"`{fname}`: {rejected} coverage entries were rejected by validation rules.")
                                st.session_state["temp_extracted"].append(
                                    {"filename": fname, "pdf_bytes": files_map[fname], "data": data}
                                )
                                _record_batch(
                                    fname,
                                    True,
                                    "extracted",
                                    usage.get("source", "") if usage else "",
                                    retries=retries_used,
                                )
                            else:
                                st.error(f"`{fname}`: {_friendly_extraction_error(error_msg)}")
                                _record_batch(
                                    fname,
                                    False,
                                    error_msg or "",
                                    retries=retries_used,
                                    error_class=_classify_error(error_msg),
                                )
                    status_text.text("Extraction complete (parallel).")
                else:
                    for i, (fname, content) in enumerate(files_map.items()):
                        with st.status(f"Processing `{fname}`...", expanded=True) as status:
                            def update_status(msg):
                                status.write(msg)

                            try:
                                existing = next(
                                    (
                                        item
                                        for item in st.session_state["temp_extracted"]
                                        if item["filename"] == fname
                                    ),
                                    None,
                                )
                                if existing and not force_refresh:
                                    status.write("Loaded from session memory (same upload session).")
                                    status.update(
                                        label=f"`{fname}` Already Loaded",
                                        state="complete",
                                        expanded=False,
                                    )
                                    _record_batch(fname, True, "session_memory", "", retries=0)
                                    continue

                                data, usage, error_msg = process_pdf(
                                    content,
                                    api_key,
                                    status_callback=update_status,
                                    force_refresh=force_refresh,
                                    user_policy_type=user_policy_type,
                                )

                                if usage and usage.get("source") == "cache":
                                    status.write("Loaded from file hash cache (no API call).")

                                if data:
                                    retries_used = int((usage or {}).get("llm_retries", 0))
                                    rejected = len(data.get("extraction_audit", {}).get("rejected_coverages", []))
                                    if rejected:
                                        status.write(f"Validation rejected {rejected} coverage entries (see review).")
                                    st.session_state["temp_extracted"].append(
                                        {"filename": fname, "pdf_bytes": content, "data": data}
                                    )
                                    status.update(
                                        label=f"Processed `{fname}`.",
                                        state="complete",
                                        expanded=False,
                                    )
                                    _record_batch(
                                        fname,
                                        True,
                                        "extracted",
                                        usage.get("source", "") if usage else "",
                                        retries=retries_used,
                                    )
                                else:
                                    status.update(
                                        label=f"Extraction Failed for `{fname}`",
                                        state="error",
                                        expanded=True,
                                    )
                                    friendly = _friendly_extraction_error(error_msg)
                                    status.write(friendly)
                                    st.error(f"`{fname}`: {friendly}")
                                    _record_batch(
                                        fname,
                                        False,
                                        error_msg or "",
                                        retries=0,
                                        error_class=_classify_error(error_msg),
                                    )

                            except Exception as e:
                                status.update(
                                    label=f"Error processing `{fname}`",
                                    state="error",
                                    expanded=True,
                                )
                                friendly = _friendly_extraction_error(str(e))
                                status.write(friendly)
                                st.error(f"`{fname}`: {friendly}")
                                _record_batch(
                                    fname,
                                    False,
                                    str(e),
                                    retries=0,
                                    error_class=_classify_error(str(e)),
                                )

                        progress_bar.progress((i + 1) / total_files)

                    status_text.text("Extraction complete! Choose an action below.")

                if batch_rows:
                    rep = pd.DataFrame(batch_rows)
                    st.subheader("Batch report")
                    st.dataframe(rep, hide_index=True, use_container_width=True)
                    today_key = date.today().isoformat()
                    telem = st.session_state.get("batch_telemetry_today", {})
                    if telem.get("day") != today_key:
                        telem = {
                            "day": today_key,
                            "files": 0,
                            "cache_hits": 0,
                            "retries": 0,
                            "errors": 0,
                        }
                    telem["files"] += int(len(rep))
                    telem["cache_hits"] += int((rep["source"] == "cache").sum()) if "source" in rep else 0
                    telem["retries"] += int(rep["retries"].sum()) if "retries" in rep else 0
                    telem["errors"] += int((rep["status"] == "error").sum()) if "status" in rep else 0
                    st.session_state["batch_telemetry_today"] = telem
                    if len(rep) > 1:
                        cache_hits = int((rep["source"] == "cache").sum()) if "source" in rep else 0
                        total_retries = int(rep["retries"].sum()) if "retries" in rep else 0
                        error_total = int((rep["status"] == "error").sum()) if "status" in rep else 0
                        st.caption(
                            f"Batch telemetry: cache_hits={cache_hits}, total_retries={total_retries}, errors={error_total}"
                        )
                    if len(batch_rows) > 1:
                        st.download_button(
                            "Download batch report (CSV)",
                            data=rep.to_csv(index=False).encode("utf-8"),
                            file_name="extraction_batch_report.csv",
                            mime="text/csv",
                            key="batch_report_csv",
                        )

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
                        if item["data"].get("extractable") is False:
                            skipped_count += 1
                            st.toast(
                                f"Skipped {item['filename']}: {item['data'].get('message', 'document not extractable')}",
                                icon="⚠️",
                            )
                            continue
                        duplicate_info = service.detect_duplicate_for_extraction(item["data"])
                        if duplicate_info.get("status") == "exact_number_carrier_conflict":
                            st.session_state["review_queue"].append(item)
                            skipped_count += 1
                            st.toast(
                                f"Sent {item['filename']} to review: {duplicate_info.get('reason')}",
                                icon="⚠️",
                            )
                            continue
                        
                        success, msg = service.save_policy_from_extraction(item['data'])
                        
                        if success:
                            if duplicate_info.get("status") == "exact_policy_match":
                                updated_count += 1
                            else:
                                processed_count += 1
                        else:
                            skipped_count += 1
                            st.toast(msg, icon="⚠️")
                    
                    parts = []
                    if processed_count:
                        parts.append(f"**{processed_count}** new {'policy' if processed_count == 1 else 'policies'} saved")
                    if updated_count:
                        parts.append(f"**{updated_count}** existing {'policy' if updated_count == 1 else 'policies'} updated")
                    if skipped_count:
                        parts.append(f"**{skipped_count}** skipped or routed to review")
                    
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
                m_underwriter = st.text_input("Underwriter Name (Legal Entity)")
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
                        from core.services import ACCOUNT_TYPE_BY_POLICY
                        acc_type = ACCOUNT_TYPE_BY_POLICY.get(m_type, "Commercial")
                        
                        policy_payload = {
                            "carrier_name": m_carrier,
                            "underwriter_name": m_underwriter,
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
                        else:
                            st.error(f"Error: {msg}")
                            
                    except Exception as e:
                        st.error(f"Save failed: {e}")
                    finally:
                        session.close()

    if st.session_state["review_queue"]:
        st.divider()
        st.subheader(f"Step 2: Review & Save ({len(st.session_state['review_queue'])} remaining)")
        
        current_item = st.session_state["review_queue"][0]
        p = current_item['data'].get('policy', {})
        fname = current_item['filename']
        
        c_pdf, c_form = st.columns([1, 1])
        
        with c_pdf:
            st.markdown(f"**Viewing:** `{fname}`")
            render_text = st.toggle(
                "Selectable text",
                value=True,
                key=f"pdf_render_text_{fname}",
                help=(
                    "PDF viewer display only: lets you select/copy text in the preview when supported. "
                    "Does not run extraction again or change saved policy data."
                ),
            )
            pdf_viewer(
                input=current_item['pdf_bytes'],
                width="100%",
                height=850,
                zoom_level=None,
                render_text=render_text,
                resolution_boost=1,
                viewer_align="center",
                show_page_separator=True,
            )
            
        with c_form:
            st.markdown("#### Verify Extracted Data")
            st.caption(CONFIDENCE_LEGEND_CAPTION)
            classification = current_item['data'].get('classification', {})
            document_type = (
                current_item['data'].get('document_type')
                or classification.get('document_type')
                or "unknown"
            )
            is_extractable = current_item['data'].get('extractable', True)

            if not is_extractable:
                st.error(current_item['data'].get('message', "This document type is not extractable yet."))
                st.info(f"Document type detected: `{document_type}`")
                if st.button("Skip This Document", key=f"skip_non_extractable_{fname}", type="primary"):
                    st.session_state["review_queue"].pop(0)
                    st.rerun()
                st.stop()

            if document_type == "renewal_declarations":
                st.info("Renewal declarations detected. Review effective/expiration dates carefully before saving.")
            if document_type in ("certificate_of_insurance", "memorandum"):
                st.info("COI/Memorandum detected: vehicle and driver schedules are extracted when present.")
            if document_type == "endorsement":
                st.info("Endorsement detected: metadata-only capture. No policy row will be created.")
                endorsement = current_item["data"].get("endorsement") or {}
                with st.form(key=f"review_endorsement_form_{fname}"):
                    endorsement_options = [
                        "additional_insured",
                        "excluded_driver",
                        "coverage_change",
                        "vehicle_add",
                        "vehicle_delete",
                        "cargo_amendment",
                        "premium_change",
                        "other",
                    ]
                    default_endorsement_type = endorsement.get("endorsement_type")
                    default_endorsement_idx = (
                        endorsement_options.index(default_endorsement_type)
                        if default_endorsement_type in endorsement_options
                        else 0
                    )
                    e_type = st.selectbox(
                        "Endorsement Type",
                        options=endorsement_options,
                        index=default_endorsement_idx,
                    )
                    e_parent_number = st.text_input(
                        "Parent Policy Number",
                        value=endorsement.get("parent_policy_number", ""),
                    )
                    e_form_number = st.text_input(
                        "Endorsement Form Number",
                        value=endorsement.get("endorsement_form_number", ""),
                    )
                    e_effective = st.text_input(
                        "Effective Date",
                        value=endorsement.get("effective_date", ""),
                    )
                    e_summary = st.text_area(
                        "Changes Summary",
                        value=endorsement.get("changes_summary", ""),
                        height=120,
                    )

                    session = get_session(st.session_state.db_engine)
                    service = PolicyService(session)
                    all_policies = service.search_policies(None, limit=5000, offset=0)
                    matched_parent = service.get_policy_by_number(e_parent_number) if e_parent_number else None
                    if matched_parent:
                        st.success(
                            f"Matched parent policy: {matched_parent.policy_number} ({matched_parent.insured_name})"
                        )
                        selected_parent_number = matched_parent.policy_number
                    else:
                        st.warning("No parent policy match found. Select one manually.")
                        policy_choices = [""] + [
                            f"{p.policy_number} | {p.insured_name or 'Unknown'}"
                            for p in all_policies
                            if p.policy_number
                        ]
                        selected_choice = st.selectbox(
                            "Manual Parent Policy Selection",
                            options=policy_choices,
                            index=0,
                        )
                        selected_parent_number = selected_choice.split(" | ")[0] if selected_choice else e_parent_number

                    b_col1, b_col2, b_col3 = st.columns([1, 1, 1])
                    saved_endorsement = b_col1.form_submit_button("💾 Save", type="secondary")
                    save_next_endorsement = b_col2.form_submit_button("💾⏩ Save & Next", type="primary")
                    discard_endorsement = b_col3.form_submit_button("🗑️ Discard")

                    if saved_endorsement or save_next_endorsement:
                        try:
                            payload = {
                                "classification": classification,
                                "policy_data_source": "endorsement_summary",
                                "endorsement": {
                                    "parent_policy_number": selected_parent_number,
                                    "endorsement_type": e_type,
                                    "endorsement_form_number": e_form_number,
                                    "effective_date": e_effective,
                                    "changes_summary": e_summary,
                                    "file_hash": endorsement.get("file_hash"),
                                },
                            }
                            success, msg = service.save_policy_from_extraction(payload)
                            if success:
                                st.toast("✅ Endorsement saved.")
                                st.session_state["review_queue"].pop(0)
                                st.rerun()
                            st.toast(f"⚠️ Could not save endorsement: {msg}", icon="⚠️")
                        except Exception as e:
                            st.toast(f"❌ Save failed: {e}", icon="❌")
                        finally:
                            session.close()
                    elif discard_endorsement:
                        session.close()
                        st.session_state["review_queue"].pop(0)
                        st.rerun()
                    else:
                        session.close()
                st.stop()

            coi_summary = current_item["data"].get("coi_summary") or {}
            coi_policies = coi_summary.get("policies") or []
            if coi_policies:
                st.markdown("##### COI Policies Detected")
                list_rows = []
                for idx, row in enumerate(coi_policies):
                    if not isinstance(row, dict):
                        continue
                    list_rows.append(
                        {
                            "index": idx,
                            "policy_type": row.get("policy_type"),
                            "carrier_name": _carrier_display(
                                row.get("carrier_name"),
                                row.get("underwriter_name"),
                            ),
                            "underwriter_name": row.get("underwriter_name"),
                            "policy_number": row.get("policy_number"),
                            "effective_date": row.get("effective_date"),
                            "expiration_date": row.get("expiration_date"),
                        }
                    )
                if list_rows:
                    st.dataframe(pd.DataFrame(list_rows), hide_index=True, width='stretch')
                    selected_policy_idx = st.selectbox(
                        "Select COI policy row to review",
                        options=list(range(len(list_rows))),
                        format_func=lambda i: f"{list_rows[i].get('policy_number') or 'no_policy_number'} ({list_rows[i].get('carrier_name') or 'unknown_carrier'})",
                        key=f"coi_policy_pick_{fname}",
                    )
                    selected_row = coi_policies[selected_policy_idx] if selected_policy_idx < len(coi_policies) else {}
                    selected_limits = selected_row.get("limits") if isinstance(selected_row.get("limits"), dict) else {}
                    p = {
                        **p,
                        "carrier_name": selected_row.get("carrier_name"),
                        "underwriter_name": selected_row.get("underwriter_name"),
                        "naic_number": selected_row.get("naic_number"),
                        "policy_number": selected_row.get("policy_number"),
                        "effective_date": selected_row.get("effective_date"),
                        "expiration_date": selected_row.get("expiration_date"),
                        "liability_limit": selected_limits.get("liability_limit"),
                        "general_liability_limit": selected_limits.get("general_liability_limit"),
                        "cargo_limit": selected_limits.get("cargo_limit"),
                        "cargo_deductible": selected_limits.get("cargo_deductible"),
                        "um_uim_limit": selected_limits.get("um_uim_limit"),
                        "med_pay_limit": selected_limits.get("med_pay_limit"),
                        "pip_limit": selected_limits.get("pip_limit"),
                        "comp_deductible": selected_limits.get("comp_deductible"),
                        "coll_deductible": selected_limits.get("coll_deductible"),
                    }

            variant_status = current_item["data"].get("variant_status")
            if variant_status == "new_carrier":
                st.warning(
                    "⚠️ **New carrier layout detected.** After saving, consider generating a golden file for regression testing."
                )
            elif variant_status == "new_layout_variant":
                st.info(
                    "ℹ️ **New layout variant of known carrier.** Verify fields carefully — this format hasn't been extracted before."
                )
            elif variant_status == "new_policy_type_variant":
                st.info(
                    "ℹ️ **New policy type for this carrier.** Verify fields carefully."
                )

            confidence_map = _build_confidence_map(
                p,
                p.get("field_confidences")
                or current_item["data"].get("field_confidences")
                or current_item["data"].get("policy", {}).get("field_confidences"),
            )
            low_fields = [k for k, v in confidence_map.items() if v == "low"]
            medium_fields = [k for k, v in confidence_map.items() if v == "medium"]
            if low_fields:
                st.markdown(
                    "<div style='background-color:#fff7d6;padding:8px 10px;border-radius:6px;border:1px solid #f0d77a;'>"
                    "⚠️ <b>Low-confidence fields detected.</b> Please verify highlighted values before saving."
                    "</div>",
                    unsafe_allow_html=True,
                )
            elif medium_fields:
                st.caption("◐ Some fields are medium confidence. Verify if ambiguous.")

            completeness = PolicyService.compute_completeness_score(p, document_type)
            coi_badge = "✅ COI Ready" if completeness["coi_ready"] else "⚠️ COI Needs Review"
            st.caption(
                f"Completeness Score: **{completeness['score']}** | {coi_badge} | "
                f"Missing required: {len(completeness['missing_required'])} | "
                f"Missing recommended: {len(completeness['missing_recommended'])}"
            )

            c1, c2 = st.columns(2)
            
            locs = p.get('field_locations', [])
            
            r_carrier = c1.text_input(_confidence_label("Carrier (Brand)", "carrier_name", confidence_map), value=p.get('carrier_name', ''), help=get_source_help("carrier_name", locs))
            r_underwriter = c2.text_input("Underwriter (Legal Entity)", value=p.get("underwriter_name", ""))
            r_pol_num = c2.text_input(_confidence_label("Policy Number", "policy_number", confidence_map), value=p.get('policy_number', ''), help=get_source_help("policy_number", locs))
            
            cc1, cc2 = st.columns(2)
            r_type = cc1.text_input("Policy Type", value=classification.get('policy_type', ''), disabled=True)
            r_conf = cc2.text_input("Confidence", value=classification.get('confidence', ''), disabled=True)
            
            c3, c4 = st.columns(2)
            
            current_naic = p.get('naic_number', '')
            if not current_naic:
                current_naic = get_naic_for_carrier(p.get('carrier_name', ''))
            
            locs = p.get('field_locations', [])
            
            r_naic = c3.text_input("NAIC Code", value=current_naic)
            
            prem_help = get_source_help("premium", locs)
            premium_audit = (
                (current_item["data"].get("audits") or {}).get("premium")
                or {}
            )
            
            prem_label = _confidence_label("Premium", "premium", confidence_map)
            audit_flag = premium_audit.get("flag")
            if audit_flag == "PLAUSIBLE":
                prem_label += " ✅"
            elif audit_flag in {"POSSIBLE_INSTALLMENT", "UNUSUALLY_HIGH"}:
                prem_label += " ⚠️"

            r_premium = c3.text_input(prem_label, value=p.get('premium', ''), help=prem_help)
            
            if audit_flag == "PLAUSIBLE":
                st.success(
                    f"Premium audit: PLAUSIBLE ({premium_audit.get('per_vehicle', 'n/a')} per vehicle)"
                )
            elif audit_flag in {"POSSIBLE_INSTALLMENT", "UNUSUALLY_HIGH"}:
                st.warning(
                    premium_audit.get("reason")
                    or f"Premium audit warning: {audit_flag}"
                )
            elif audit_flag in {"MISSING_DATA", "SKIP"}:
                st.caption(
                    premium_audit.get("reason")
                    or f"Premium audit: {audit_flag}"
                )
            r_eff = c4.text_input(_confidence_label("Effective Date", "effective_date", confidence_map), value=p.get('effective_date', ''), help=get_source_help("effective_date", locs))
            r_exp = c4.text_input(_confidence_label("Expiration Date", "expiration_date", confidence_map), value=p.get('expiration_date', ''), help=get_source_help("expiration_date", locs))
            
            st.divider()
            r_ins_name = st.text_input(_confidence_label("Insured Name", "insured_name", confidence_map), value=p.get('insured_name', ''))
            r_ins_addr = st.text_input("Insured Address", value=p.get('insured_address', ''))
            ic1, ic2, ic3 = st.columns(3)
            r_ins_city = ic1.text_input("City", value=p.get('insured_city', ''))
            r_ins_state = ic2.text_input("State", value=p.get('insured_state_code', ''))
            r_ins_zip = ic3.text_input("Zip", value=p.get('insured_zip', ''))
            
            st.divider()
            r_liab = st.text_input(_confidence_label("Auto Liability Limit", "liability_limit", confidence_map), value=p.get('liability_limit', ''))
            r_gl_limit = st.text_input("GL Limit", value=p.get('general_liability_limit', ''))
            r_cargo = st.text_input(_confidence_label("Cargo Limit", "cargo_limit", confidence_map), value=p.get('cargo_limit', ''))
            r_cargo_ded = st.text_input("Cargo Ded", value=p.get('cargo_deductible', ''))
            
            st.markdown("##### Additional Coverages")
            rc1, rc2, rc3, rc4, rc5 = st.columns(5)
            r_um = rc1.text_input("UM/UIM", value=p.get('um_uim_limit', ''))
            r_med = rc2.text_input("Med Pay", value=p.get('med_pay_limit', ''))
            r_pip = rc3.text_input("PIP", value=p.get('pip_limit', ''))
            r_comp = rc4.text_input("Comp Ded", value=p.get('comp_deductible', ''))
            r_coll = rc5.text_input("Coll Ded", value=p.get('coll_deductible', ''))
            
            r_gl = st.checkbox("Has GL", value=bool(p.get('has_general_liability')))
            r_auto = st.checkbox("Has Auto", value=bool(p.get('has_auto_liability')))
            r_status = st.selectbox("Status", ["Active", "Pending", "Quote", "Expired"], index=0)

            st.divider()
            st.markdown("#### Detailed Inventory (Editable)")
            v_data = current_item['data'].get('vehicles') or []
            d_data = current_item['data'].get('drivers') or []
            show_vehicle_tab = len(v_data) > 0
            show_driver_tab = len(d_data) > 0

            tab_defs = []
            if show_vehicle_tab:
                tab_defs.append(("vehicles", "🚙 Vehicles"))
            if show_driver_tab:
                tab_defs.append(("drivers", "👤 Drivers"))
            tab_defs.extend([
                ("coverages", "🛡️ Coverages"),
                ("additional_interests", "🏢 Additional Interests"),
            ])
            tab_views = dict(zip([k for k, _ in tab_defs], st.tabs([label for _, label in tab_defs])))

            edited_v = pd.DataFrame(v_data) if show_vehicle_tab else pd.DataFrame()
            edited_d = pd.DataFrame(d_data) if show_driver_tab else pd.DataFrame()

            if show_vehicle_tab:
                with tab_views["vehicles"]:
                    v_df = pd.DataFrame(v_data)
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

            if show_driver_tab:
                with tab_views["drivers"]:
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
            
            with tab_views["coverages"]:
                c_data = current_item['data'].get('coverages', [])
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

            with tab_views["additional_interests"]:
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
            st.subheader("👤 Customer")
            st.caption(
                "Customer matching uses the insured name, policy number, and drivers from the fields above."
            )
            confirm_key = f"confirm_customer_id_{fname}"
            owner_widget_key = f"commercial_owner_input_{fname}"
            owner_storage_key = f"commercial_owner_name_{fname}"
            if confirm_key not in st.session_state:
                st.session_state[confirm_key] = None
            if owner_storage_key not in st.session_state:
                st.session_state[owner_storage_key] = ""

            policy_type = (classification or {}).get("policy_type", "")
            data_for_resolve = copy.deepcopy(current_item["data"])
            rp = data_for_resolve.setdefault("policy", {})
            rp["insured_name"] = r_ins_name
            rp["policy_number"] = r_pol_num
            data_for_resolve["classification"] = dict(classification or {})
            if not edited_d.empty:
                data_for_resolve["drivers"] = _dataframe_to_record_list(edited_d)
            embedded_owner = CustomerResolver.extract_embedded_owner_name(r_ins_name)

            customer_session = get_session(st.session_state.db_engine)
            try:
                resolved = CustomerResolver(customer_session).resolve(data_for_resolve)
                conf = resolved.get("confidence")
                res_customer = resolved.get("customer")

                if conf == "confirmed" and res_customer is not None:
                    customer = customer_session.query(Customer).get(res_customer.id)
                    if customer:
                        st.success(f"✅ Matched to: **{customer.full_name}**")
                        other_pols = [
                            op
                            for op in (customer.policies or [])
                            if (op.policy_number or "") != (r_pol_num or "").strip()
                        ]
                        if other_pols:
                            st.caption("Their other policies with us:")
                            for op in other_pols[:5]:
                                icon = (
                                    "✅"
                                    if (op.policy_status or "").lower() == "active"
                                    else "⏰"
                                )
                                st.markdown(
                                    f"{icon} `{op.policy_number}` {op.policy_type} "
                                    f"— {_carrier_display(op.carrier_name, getattr(op, 'underwriter_name', None))}"
                                )
                elif conf == "suggested" and res_customer is not None:
                    customer = customer_session.query(Customer).get(res_customer.id)
                    if customer:
                        st.warning(
                            f"⚠️ Possible match: **{customer.full_name}** — "
                            f"{resolved.get('match_reason', 'Needs review')}"
                        )
                        c1, c2 = st.columns(2)
                        if c1.button("✅ Yes, same customer", key=f"yes_customer_{fname}"):
                            st.session_state[confirm_key] = customer.id
                        if c2.button("❌ No, different person", key=f"no_customer_{fname}"):
                            st.session_state[confirm_key] = None
                        chosen = st.session_state.get(confirm_key)
                        if chosen == customer.id:
                            st.success("Will link to this customer on save.")
                        elif chosen is None:
                            st.caption("Will not auto-link this suggestion.")
                else:
                    st.info("🆕 New customer will be created")
                    if policy_type != "personal_auto":
                        if embedded_owner:
                            st.success(f"Owner detected from DBA: **{embedded_owner['owner_name']}**")
                            st.caption("The full insured/DBA name will be saved as a business entity.")
                            st.session_state[owner_storage_key] = ""
                        else:
                            st.markdown("**Commercial — who is the owner?**")
                            owner_name = st.text_input(
                                "Owner / Principal Name",
                                placeholder="e.g. Ayaz Demir",
                                key=owner_widget_key,
                            )
                            if owner_name.strip():
                                st.session_state[owner_storage_key] = owner_name.strip()
                            else:
                                st.session_state[owner_storage_key] = ""
            finally:
                customer_session.close()

            related = (current_item["data"].get("_related_policy_candidates") or [])[:3]
            if related:
                st.divider()
                st.subheader("🔗 Potential Related Policies")
                st.caption("Found existing policies that may be related to this one.")
                relationship_session = get_session(st.session_state.db_engine)
                relationship_service = PolicyService(relationship_session)
                try:
                    for match in related:
                        render_related_policy(match, current_item, relationship_service)
                finally:
                    relationship_session.close()

            st.divider()
            
            b_col_warn = st.container()

            review_extraction_result = copy.deepcopy(current_item["data"])
            pol_save = review_extraction_result.setdefault("policy", {})
            pol_save.update(
                {
                    "carrier_name": r_carrier,
                    "underwriter_name": r_underwriter,
                    "naic_number": r_naic,
                    "policy_number": r_pol_num,
                    "effective_date": r_eff,
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
                    "account_type": p.get("account_type"),
                    "document_type": document_type,
                    "premium": r_premium,
                    "business_name": p.get("business_name"),
                    "financial_responsibility_name": p.get("financial_responsibility_name"),
                    "has_full_collision": p.get("has_full_collision"),
                    "status": r_status,
                    "field_confidences": confidence_map,
                }
            )
            review_extraction_result["classification"] = dict(classification or {})
            review_extraction_result["vehicles"] = _dataframe_to_record_list(edited_v)
            review_extraction_result["drivers"] = _dataframe_to_record_list(edited_d)
            review_extraction_result["coverages"] = _coverages_from_editor_rows(c_data, edited_c)
            review_extraction_result["additional_interests"] = _dataframe_to_record_list(edited_ai)
            review_extraction_result["_review_confirm_customer_id"] = st.session_state.get(confirm_key)
            review_extraction_result["_review_commercial_owner_name"] = (
                (st.session_state.get(owner_storage_key) or "").strip()
            )

            if (
                review_extraction_result.get("policy_data_source") == "coi_summary"
                and (review_extraction_result.get("coi_summary") or {}).get("policies")
            ):
                review_extraction_result.pop("coi_summary", None)
                review_extraction_result["policy_data_source"] = (
                    document_type or "certificate_of_insurance"
                )

            duplicate_info = {"status": "no_match"}
            diff_preview = None
            duplicate_session = get_session(st.session_state.db_engine)
            duplicate_service = PolicyService(duplicate_session)
            try:
                duplicate_info = duplicate_service.detect_duplicate_for_extraction(review_extraction_result)
                existing_id = duplicate_info.get("existing_policy_id")
                if existing_id:
                    existing_policy = duplicate_service.get_policy_by_id(existing_id)
                    if existing_policy:
                        diff_preview = duplicate_service.preview_update_from_extraction(
                            existing_policy,
                            review_extraction_result,
                        )
            finally:
                duplicate_session.close()

            with b_col_warn:
                _render_duplicate_preview(duplicate_info, diff_preview)
            
            b_col1, b_col2, b_col3 = st.columns([1, 1, 1])
            duplicate_status = duplicate_info.get("status")
            has_existing_policy = duplicate_status in {
                "exact_policy_match",
                "exact_number_carrier_conflict",
            }
            primary_label = "Update Current Policy" if has_existing_policy else "Create New Policy"
            next_label = "Update & Next" if has_existing_policy else "Create & Next"
            saved = b_col1.button(primary_label, type="secondary", key=f"save_review_{fname}")
            save_next = b_col2.button(next_label, type="primary", key=f"save_next_review_{fname}")
            discarded = b_col3.button("🗑️ Discard", key=f"discard_review_{fname}")
            if has_existing_policy:
                st.caption("To create a separate policy entry instead, edit the incoming policy number first.")
            
            if saved or save_next:
                session = get_session(st.session_state.db_engine)
                service = PolicyService(session)
                try:
                    review_extraction_result["_duplicate_action"] = (
                        "update_existing" if has_existing_policy else "create_new"
                    )
                    success, msg = service.save_policy_from_extraction(review_extraction_result)
                    
                    if success:
                        st.toast(f"✅ Saved {r_pol_num}!")
                        st.session_state.pop(confirm_key, None)
                        st.session_state.pop(owner_storage_key, None)
                        st.session_state["review_queue"].pop(0)
                        st.rerun()
                    else:
                        st.toast(f"⚠️ Could not save: {msg}", icon="⚠️")
                    
                except Exception as e:
                    st.toast(f"❌ Save failed: {e}", icon="❌")
                finally:
                    session.close()
            
            if discarded:
                st.session_state.pop(confirm_key, None)
                st.session_state.pop(owner_storage_key, None)
                st.session_state["review_queue"].pop(0)
                st.rerun()
    else:
        if "review_queue" in st.session_state and isinstance(st.session_state["review_queue"], list):
             st.info("No policies pending review.")
