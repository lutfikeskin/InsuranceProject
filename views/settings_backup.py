"""Backup and import controls for Settings dialog."""

from __future__ import annotations

import os
import uuid

import streamlit as st

from core.db_import import DbImportError, merge_database_from_file, validate_sqlite_db
from modules.coi.holders import (
    COIHolderError,
    export_coi_holders_bytes,
    holder_library_path_display,
    load_coi_holders,
    merge_coi_holders_from_bytes,
)


def render_database_backup_section() -> None:
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
            st.rerun()
        except DbImportError as exc:
            st.error(str(exc))
        finally:
            if merge_path and os.path.exists(merge_path):
                os.unlink(merge_path)


def render_holder_library_section() -> None:
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
            st.rerun()
        except COIHolderError as exc:
            st.error(str(exc))
