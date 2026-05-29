"""Backup and import controls for Settings dialog."""

from __future__ import annotations

import os
import uuid
from datetime import datetime

import streamlit as st

from core.backup_bundle import BackupBundleError, build_backup_bundle, import_backup_bundle
from core.db_import import DbImportError, merge_database_from_file, validate_sqlite_db
from core.telemetry import log_event
from modules.coi.holders import (
    COIHolderError,
    export_coi_holders_bytes,
    holder_library_path_display,
    load_coi_holders,
    merge_coi_holders_from_bytes,
)


def render_unified_backup_section(telemetry=None) -> None:
    st.caption(
        "One local backup file includes insurance_data.db, COI holder library, "
        "and telemetry tables. Import merges records back after restart or move."
    )

    if os.path.exists("insurance_data.db"):
        try:
            backup_bytes = build_backup_bundle(telemetry.session if telemetry else None)
            st.download_button(
                "Backup app data (.zip)",
                data=backup_bytes,
                file_name=f"insurance_app_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip",
                mime="application/zip",
                key="settings_unified_backup_download",
                width="stretch",
            )
        except BackupBundleError as exc:
            st.error(str(exc))
    else:
        st.warning("No insurance_data.db file found in the project root.")

    uploaded_bundle = st.file_uploader(
        "Import app backup (.zip)",
        type=["zip"],
        key="settings_unified_backup_upload",
    )
    if uploaded_bundle is None:
        return

    if st.button(
        "Merge imported app backup",
        type="primary",
        key="settings_unified_backup_merge_btn",
        width="stretch",
    ):
        try:
            result = import_backup_bundle(
                st.session_state.db_engine,
                telemetry.session,
                uploaded_bundle.getvalue(),
            )
            st.session_state.coi_companies = load_coi_holders()
            st.success(
                "Imported backup: "
                f"{result.database.imported_policies} policies, "
                f"{result.database.imported_customers} customers, "
                f"{result.holders.imported} holders, "
                f"{result.telemetry.imported_app_events} app events, "
                f"{result.telemetry.imported_api_usage} API usage rows."
            )
            warnings = []
            warnings.extend(result.database.errors[:5])
            warnings.extend(result.holders.errors[:5])
            warnings.extend(result.telemetry.errors[:5])
            if warnings:
                st.warning("\n".join(warnings[:10]))
            telemetry.record_event(
                "admin_app_backup_merge",
                category="admin",
                status="success",
                count_value=result.database.imported_policies,
                metadata={
                    "imported_customers": result.database.imported_customers,
                    "imported_holders": result.holders.imported,
                    "imported_app_events": result.telemetry.imported_app_events,
                    "imported_api_usage": result.telemetry.imported_api_usage,
                    "skipped_policy_duplicates": result.database.skipped_duplicates,
                    "skipped_holder_duplicates": result.holders.skipped_duplicates,
                    "skipped_app_event_duplicates": result.telemetry.skipped_app_events,
                    "skipped_api_usage_duplicates": result.telemetry.skipped_api_usage,
                },
            )
            log_event(
                "admin_app_backup_merge",
                status="success",
                metadata={
                    "imported_policies": result.database.imported_policies,
                    "imported_holders": result.holders.imported,
                    "imported_app_events": result.telemetry.imported_app_events,
                    "imported_api_usage": result.telemetry.imported_api_usage,
                },
            )
            st.rerun()
        except (BackupBundleError, COIHolderError, DbImportError) as exc:
            if telemetry:
                telemetry.record_event(
                    "admin_app_backup_merge",
                    category="admin",
                    status="failure",
                    message=str(exc),
                )
            log_event("admin_app_backup_merge", level="error", status="failure", message=str(exc))
            st.error(str(exc))


# Legacy split controls kept for direct calls/tests; Settings uses unified section.
def render_database_backup_section(telemetry=None) -> None:
    st.caption(
        "Back up or merge policies from another insurance_data.db file. "
        "Merge skips policies whose policy number already exists."
    )
    if os.path.exists("insurance_data.db"):
        with open("insurance_data.db", "rb") as f:
            st.download_button(
                "Backup database (.db)",
                data=f.read(),
                file_name="insurance_data.db",
                key="settings_db_backup_download",
                width="stretch",
            )
    else:
        st.warning("No insurance_data.db file found in the project root.")

    uploaded_db = st.file_uploader(
        "Import database (.db)",
        type=["db"],
        key="settings_db_import_upload",
    )
    if uploaded_db is None:
        return

    preview = None
    preview_path = None
    try:
        os.makedirs(".cache", exist_ok=True)
        preview_path = os.path.join(".cache", f"import_preview_{uuid.uuid4().hex}.db")
        with open(preview_path, "wb") as tmp:
            tmp.write(uploaded_db.getvalue())
        preview = validate_sqlite_db(preview_path)
        st.caption(
            f"File has {preview.policy_count} policies and "
            f"{preview.customer_count} customers."
        )
    except DbImportError as exc:
        st.error(str(exc))
        return
    finally:
        if preview_path and os.path.exists(preview_path):
            os.unlink(preview_path)

    if st.button(
        "Merge imported database",
        type="primary",
        disabled=preview is None,
        key="settings_db_import_merge_btn",
    ):
        merge_path = None
        try:
            merge_path = os.path.join(".cache", f"import_{uuid.uuid4().hex}.db")
            with open(merge_path, "wb") as tmp:
                tmp.write(uploaded_db.getvalue())
            merge_result = merge_database_from_file(
                st.session_state.db_engine, merge_path
            )
            st.success(
                f"Imported {merge_result.imported_policies} policies, "
                f"skipped {merge_result.skipped_duplicates} duplicates, "
                f"added {merge_result.imported_customers} customers, "
                f"{merge_result.imported_relationships} relationships."
            )
            if merge_result.errors:
                st.warning("\n".join(merge_result.errors[:5]))
            if telemetry:
                telemetry.record_event(
                    "admin_database_merge",
                    category="admin",
                    status="success",
                    count_value=merge_result.imported_policies,
                    metadata={
                        "skipped_duplicates": merge_result.skipped_duplicates,
                        "imported_customers": merge_result.imported_customers,
                        "imported_relationships": merge_result.imported_relationships,
                        "error_count": len(merge_result.errors or []),
                    },
                )
            log_event(
                "admin_database_merge",
                status="success",
                metadata={
                    "imported_policies": merge_result.imported_policies,
                    "skipped_duplicates": merge_result.skipped_duplicates,
                    "imported_customers": merge_result.imported_customers,
                    "imported_relationships": merge_result.imported_relationships,
                },
            )
            st.rerun()
        except DbImportError as exc:
            if telemetry:
                telemetry.record_event(
                    "admin_database_merge",
                    category="admin",
                    status="failure",
                    message=str(exc),
                    metadata={"action": "merge"},
                )
            log_event("admin_database_merge", level="error", status="failure", message=str(exc))
            st.error(str(exc))
        finally:
            if merge_path and os.path.exists(merge_path):
                os.unlink(merge_path)


def render_holder_library_section(telemetry=None) -> None:
    st.caption(
        f"Holder library file: {holder_library_path_display()}. "
        "Saves persist across restarts. Export before moving to another machine."
    )
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Export holder library (JSON)",
            data=export_coi_holders_bytes(),
            file_name="coi_holders.json",
            mime="application/json",
            key="settings_holder_export",
            width="stretch",
        )
    with col2:
        if st.button("Reload holder library", key="settings_holder_reload", width="stretch"):
            st.session_state.coi_companies = load_coi_holders()
            if telemetry:
                telemetry.record_event(
                    "admin_holder_library_reload",
                    category="admin",
                    status="success",
                )
            log_event("admin_holder_library_reload", status="success")
            st.rerun()

    uploaded_json = st.file_uploader(
        "Import holder library (.json)",
        type=["json"],
        key="settings_holder_import_upload",
    )
    if uploaded_json is None:
        return

    if st.button("Merge imported holder library", key="settings_holder_merge_btn"):
        try:
            result = merge_coi_holders_from_bytes(uploaded_json.getvalue())
            st.session_state.coi_companies = load_coi_holders()
            st.success(
                f"Imported {result.imported} holders, "
                f"skipped {result.skipped_duplicates} duplicates."
            )
            if result.errors:
                st.warning("\n".join(result.errors[:5]))
            if telemetry:
                telemetry.record_event(
                    "admin_holder_library_merge",
                    category="admin",
                    status="success",
                    count_value=result.imported,
                    metadata={
                        "skipped_duplicates": result.skipped_duplicates,
                        "error_count": len(result.errors or []),
                    },
                )
            log_event(
                "admin_holder_library_merge",
                status="success",
                metadata={
                    "imported": result.imported,
                    "skipped_duplicates": result.skipped_duplicates,
                },
            )
            st.rerun()
        except COIHolderError as exc:
            if telemetry:
                telemetry.record_event(
                    "admin_holder_library_merge",
                    category="admin",
                    status="failure",
                    message=str(exc),
                )
            log_event("admin_holder_library_merge", level="error", status="failure", message=str(exc))
            st.error(str(exc))
