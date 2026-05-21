from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy.orm import Session

from core.review_contract import REVIEW_DECISIONS, validate_review_task_payload
from core.review_model import ExtractionRun, ReviewTask, UploadedDocument
from modules.extraction.contracts import validate_extraction_result_contract


EXTRACTION_RUN_STATUSES = {"pending", "succeeded", "failed"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReviewWorkflowService:
    def __init__(self, session: Session):
        self.session = session

    def create_upload(
        self,
        *,
        filename: str,
        file_bytes: bytes,
        content_type: str | None = None,
        source: str = "manual_upload",
        storage_uri: str | None = None,
    ) -> UploadedDocument:
        if not filename or not filename.strip():
            raise ValueError("filename is required")
        if not isinstance(file_bytes, bytes) or not file_bytes:
            raise ValueError("file_bytes must be non-empty bytes")

        upload = UploadedDocument(
            filename=filename.strip(),
            file_hash=sha256(file_bytes).hexdigest(),
            byte_size=len(file_bytes),
            content_type=content_type,
            source=source,
            storage_uri=storage_uri,
        )
        self.session.add(upload)
        self.session.commit()
        self.session.refresh(upload)
        return upload

    def record_extraction_run(
        self,
        *,
        upload_id: int,
        status: str,
        result: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        error_message: str | None = None,
        force_refresh: bool = False,
    ) -> ExtractionRun:
        if status not in EXTRACTION_RUN_STATUSES:
            raise ValueError(f"unsupported extraction status: {status}")
        upload = self.session.get(UploadedDocument, upload_id)
        if upload is None:
            raise ValueError(f"unknown upload_id: {upload_id}")
        if status == "succeeded":
            contract = validate_extraction_result_contract(result)
            if not contract.ok:
                issue_text = "; ".join(f"{issue.path}: {issue.message}" for issue in contract.issues)
                raise ValueError(f"invalid extraction result: {issue_text}")
        if status == "failed" and not error_message:
            raise ValueError("error_message is required for failed extraction runs")

        classification = (result or {}).get("classification") if isinstance(result, dict) else {}
        policy_data_source = (result or {}).get("policy_data_source") if isinstance(result, dict) else None
        run = ExtractionRun(
            upload_id=upload.id,
            status=status,
            result=result,
            usage=usage,
            error_message=error_message,
            force_refresh=1 if force_refresh else 0,
            cache_source=(usage or {}).get("source") if isinstance(usage, dict) else None,
            model_name=(usage or {}).get("model") if isinstance(usage, dict) else None,
            policy_data_source=policy_data_source,
            document_type=(classification or {}).get("document_type") if isinstance(classification, dict) else None,
            policy_type=(classification or {}).get("policy_type") if isinstance(classification, dict) else None,
            completed_at=_utcnow() if status in {"succeeded", "failed"} else None,
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    def create_review_task(
        self,
        *,
        upload_id: int,
        extraction_run_id: int,
        extraction_result: dict[str, Any],
        notes: str | None = None,
    ) -> ReviewTask:
        run = self.session.get(ExtractionRun, extraction_run_id)
        if run is None:
            raise ValueError(f"unknown extraction_run_id: {extraction_run_id}")
        if run.upload_id != upload_id:
            raise ValueError("extraction_run_id does not belong to upload_id")
        contract = validate_review_task_payload(
            {
                "filename": run.upload.filename if run.upload else "uploaded document",
                "file_hash": run.upload.file_hash if run.upload else "unknown",
                "status": "pending",
                "extraction_result": extraction_result,
            }
        )
        if not contract.ok:
            issue_text = "; ".join(f"{issue.path}: {issue.message}" for issue in contract.issues)
            raise ValueError(f"invalid review task: {issue_text}")

        task = ReviewTask(
            upload_id=upload_id,
            extraction_run_id=extraction_run_id,
            status="pending",
            extraction_result=extraction_result,
            notes=notes,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def record_decision(
        self,
        *,
        task_id: int,
        decision: str,
        human_edits: dict[str, Any] | None = None,
        target_policy_id: int | None = None,
        notes: str | None = None,
    ) -> ReviewTask:
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"unsupported review decision: {decision}")
        task = self.session.get(ReviewTask, task_id)
        if task is None:
            raise ValueError(f"unknown task_id: {task_id}")
        status = "skipped" if decision == "skip" else "saved"
        payload = {
            "filename": task.upload.filename if task.upload else "uploaded document",
            "file_hash": task.upload.file_hash if task.upload else "unknown",
            "status": status,
            "decision": decision,
            "target_policy_id": target_policy_id,
            "extraction_result": task.extraction_result,
            "human_edits": human_edits,
        }
        contract = validate_review_task_payload(payload)
        if not contract.ok:
            issue_text = "; ".join(f"{issue.path}: {issue.message}" for issue in contract.issues)
            raise ValueError(f"invalid review decision: {issue_text}")

        task.status = status
        task.decision = decision
        task.human_edits = human_edits
        task.target_policy_id = target_policy_id
        if notes is not None:
            task.notes = notes
        task.reviewed_at = _utcnow()
        task.updated_at = task.reviewed_at
        self.session.commit()
        self.session.refresh(task)
        return task

    def list_tasks(self, status: str | None = "pending", limit: int = 100) -> list[ReviewTask]:
        query = self.session.query(ReviewTask)
        if status:
            query = query.filter(ReviewTask.status == status)
        return (
            query.order_by(ReviewTask.created_at.asc(), ReviewTask.id.asc())
            .limit(limit)
            .all()
        )

    def list_pending_tasks(self) -> list[ReviewTask]:
        return self.list_tasks(status="pending")

    def queue_counts(self) -> dict[str, int]:
        rows = (
            self.session.query(ReviewTask.status)
            .all()
        )
        counts = {"pending": 0, "saved": 0, "skipped": 0, "failed": 0, "total": 0}
        for (status,) in rows:
            key = status or "pending"
            counts[key] = counts.get(key, 0) + 1
            counts["total"] += 1
        return counts

    def get_task(self, task_id: int) -> ReviewTask | None:
        return self.session.get(ReviewTask, task_id)

    def mark_task_failed(self, task_id: int, error_message: str) -> ReviewTask:
        task = self.session.get(ReviewTask, task_id)
        if task is None:
            raise ValueError(f"unknown task_id: {task_id}")
        task.status = "failed"
        task.notes = error_message
        task.updated_at = _utcnow()
        self.session.commit()
        self.session.refresh(task)
        return task
