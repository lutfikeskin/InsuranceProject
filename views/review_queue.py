from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from core.database import get_session
from core.review_model import ReviewTask
from core.review_service import ReviewWorkflowService
from core.services import PolicyService


STATUS_OPTIONS = ["pending", "saved", "skipped", "failed", "all"]


def _policy_summary(result: dict[str, Any]) -> dict[str, Any]:
    policy = result.get("policy") if isinstance(result, dict) else {}
    classification = result.get("classification") if isinstance(result, dict) else {}
    if not isinstance(policy, dict):
        policy = {}
    if not isinstance(classification, dict):
        classification = {}
    return {
        "carrier": policy.get("carrier_name") or "—",
        "policy_number": policy.get("policy_number") or "—",
        "insured": policy.get("insured_name") or "—",
        "document_type": classification.get("document_type") or result.get("document_type") or "—",
        "policy_type": classification.get("policy_type") or "—",
        "policy_data_source": result.get("policy_data_source") or "—",
    }


def _tasks_to_dataframe(tasks: list[ReviewTask]) -> pd.DataFrame:
    rows = []
    for task in tasks:
        result = task.extraction_result or {}
        summary = _policy_summary(result if isinstance(result, dict) else {})
        upload = task.upload
        run = task.extraction_run
        rows.append(
            {
                "Task ID": task.id,
                "Status": task.status,
                "Decision": task.decision or "—",
                "Filename": upload.filename if upload else "—",
                "Policy #": summary["policy_number"],
                "Insured": summary["insured"],
                "Carrier": summary["carrier"],
                "Document": summary["document_type"],
                "Type": summary["policy_type"],
                "Source": summary["policy_data_source"],
                "Created": task.created_at,
                "Run ID": run.id if run else None,
            }
        )
    return pd.DataFrame(rows)


def _select_task(tasks: list[ReviewTask], selected_id: int | None) -> ReviewTask | None:
    if not tasks:
        return None
    if selected_id is not None:
        for task in tasks:
            if task.id == selected_id:
                return task
    return tasks[0]


def _render_task_detail(task: ReviewTask) -> None:
    result = task.extraction_result or {}
    if not isinstance(result, dict):
        st.error("Stored extraction result is not a JSON object.")
        return

    summary = _policy_summary(result)
    st.markdown("#### Selected Review Task")
    c1, c2, c3 = st.columns(3)
    c1.metric("Policy #", summary["policy_number"])
    c2.metric("Carrier", summary["carrier"])
    c3.metric("Type", summary["policy_type"])
    st.caption(
        f"Task `{task.id}` · Status `{task.status}` · "
        f"Document `{summary['document_type']}` · Source `{summary['policy_data_source']}`"
    )
    if task.notes:
        st.info(task.notes)

    with st.expander("Stored extraction JSON", expanded=False):
        st.code(json.dumps(result, indent=2, default=str), language="json")


def page_review_queue() -> None:
    st.title("Review Queue")
    st.caption(
        "Durable review tasks recovered from the database. This is the backend bridge "
        "that the future HTMX/Jinja UI will reuse."
    )

    session = get_session(st.session_state.db_engine)
    try:
        review_service = ReviewWorkflowService(session)
        counts = review_service.queue_counts()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Pending", counts.get("pending", 0))
        m2.metric("Saved", counts.get("saved", 0))
        m3.metric("Skipped", counts.get("skipped", 0))
        m4.metric("Failed", counts.get("failed", 0))

        status = st.selectbox("Status", STATUS_OPTIONS, index=0)
        tasks = review_service.list_tasks(status=None if status == "all" else status, limit=200)
        if not tasks:
            st.info("No review tasks match this filter.")
            return

        df = _tasks_to_dataframe(tasks)
        st.dataframe(df, hide_index=True, width="stretch")

        selected_id = st.selectbox(
            "Select task",
            [int(task.id) for task in tasks],
            format_func=lambda task_id: f"Task #{task_id}",
        )
        task = _select_task(tasks, selected_id)
        if task is None:
            return

        _render_task_detail(task)

        if task.status != "pending":
            st.info("This task is already closed.")
            return

        result = task.extraction_result if isinstance(task.extraction_result, dict) else {}
        if result.get("extractable") is False:
            st.warning("This stored document was classified as non-extractable. Save is disabled; skip or reprocess it from Process Policies.")

        c_save, c_skip, c_fail = st.columns(3)
        if c_save.button("Save Stored Extraction", type="primary", disabled=result.get("extractable") is False):
            policy_service = PolicyService(session)
            duplicate_info = policy_service.detect_duplicate_for_extraction(result)
            decision = "update_existing" if duplicate_info.get("status") == "exact_policy_match" else "save_new"
            target_policy_id = None
            if decision == "update_existing":
                target_policy_id = (duplicate_info.get("existing_policy") or {}).get("id")
            success, msg = policy_service.save_policy_from_extraction(result)
            if success:
                review_service.record_decision(
                    task_id=task.id,
                    decision=decision,
                    human_edits=result,
                    target_policy_id=target_policy_id,
                    notes="Saved from durable review queue page.",
                )
                st.success("Saved stored extraction.")
                st.rerun()
            else:
                st.warning(msg or "Save failed.")

        if c_skip.button("Mark Skipped"):
            review_service.record_decision(
                task_id=task.id,
                decision="skip",
                notes="Skipped from durable review queue page.",
            )
            st.success("Marked skipped.")
            st.rerun()

        if c_fail.button("Mark Failed"):
            review_service.mark_task_failed(task.id, "Marked failed from durable review queue page.")
            st.success("Marked failed.")
            st.rerun()
    finally:
        session.close()
