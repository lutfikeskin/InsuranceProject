import pytest

from core.review_model import ExtractionRun, ReviewTask, UploadedDocument
from core.review_service import ReviewWorkflowService


def _result(policy_type="commercial_auto"):
    return {
        "classification": {
            "document_type": "declarations_page",
            "policy_type": policy_type,
            "confidence": "high",
        },
        "policy": {"policy_number": "P1"},
        "coverages": [],
        "vehicles": [],
        "drivers": [],
        "policy_data_source": "full_policy",
    }


def test_create_upload_records_hash_and_size(mock_db_session):
    service = ReviewWorkflowService(mock_db_session)

    upload = service.create_upload(
        filename="policy.pdf",
        file_bytes=b"pdf bytes",
        content_type="application/pdf",
    )

    assert upload.id is not None
    assert upload.filename == "policy.pdf"
    assert upload.byte_size == len(b"pdf bytes")
    assert len(upload.file_hash) == 64
    assert mock_db_session.query(UploadedDocument).count() == 1


def test_record_extraction_run_snapshots_routing_metadata(mock_db_session):
    service = ReviewWorkflowService(mock_db_session)
    upload = service.create_upload(filename="policy.pdf", file_bytes=b"pdf bytes")

    run = service.record_extraction_run(
        upload_id=upload.id,
        status="succeeded",
        result=_result("commercial_auto"),
        usage={"source": "api", "model": "gemini-test"},
        force_refresh=True,
    )

    assert run.status == "succeeded"
    assert run.upload_id == upload.id
    assert run.document_type == "declarations_page"
    assert run.policy_type == "commercial_auto"
    assert run.policy_data_source == "full_policy"
    assert run.cache_source == "api"
    assert run.model_name == "gemini-test"
    assert run.force_refresh == 1
    assert run.completed_at is not None
    assert mock_db_session.query(ExtractionRun).count() == 1


def test_failed_extraction_requires_error_message(mock_db_session):
    service = ReviewWorkflowService(mock_db_session)
    upload = service.create_upload(filename="policy.pdf", file_bytes=b"pdf bytes")

    with pytest.raises(ValueError, match="error_message"):
        service.record_extraction_run(upload_id=upload.id, status="failed")


def test_create_review_task_and_record_save_decision(mock_db_session):
    service = ReviewWorkflowService(mock_db_session)
    upload = service.create_upload(filename="policy.pdf", file_bytes=b"pdf bytes")
    result = _result()
    run = service.record_extraction_run(
        upload_id=upload.id,
        status="succeeded",
        result=result,
    )

    task = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=result,
        notes="review carefully",
    )
    updated = service.record_decision(
        task_id=task.id,
        decision="save_new",
        human_edits={"policy": {"premium": "$1,000"}},
        notes="saved after review",
    )

    assert task.id is not None
    assert updated.status == "saved"
    assert updated.decision == "save_new"
    assert updated.human_edits == {"policy": {"premium": "$1,000"}}
    assert updated.notes == "saved after review"
    assert updated.reviewed_at is not None
    assert mock_db_session.query(ReviewTask).count() == 1


def test_update_decision_requires_target_policy_id(mock_db_session):
    service = ReviewWorkflowService(mock_db_session)
    upload = service.create_upload(filename="policy.pdf", file_bytes=b"pdf bytes")
    result = _result()
    run = service.record_extraction_run(
        upload_id=upload.id,
        status="succeeded",
        result=result,
    )
    task = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=result,
    )

    with pytest.raises(ValueError, match="target_policy_id"):
        service.record_decision(task_id=task.id, decision="update_existing")


def test_list_pending_tasks_returns_only_pending_in_order(mock_db_session):
    service = ReviewWorkflowService(mock_db_session)
    upload = service.create_upload(filename="policy.pdf", file_bytes=b"pdf bytes")
    result = _result()
    run = service.record_extraction_run(
        upload_id=upload.id,
        status="succeeded",
        result=result,
    )
    first = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=result,
    )
    second = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=result,
    )
    service.record_decision(task_id=first.id, decision="skip")

    pending = service.list_pending_tasks()

    assert [task.id for task in pending] == [second.id]

def test_list_tasks_filter_and_limit(mock_db_session):
    service = ReviewWorkflowService(mock_db_session)
    upload = service.create_upload(filename="policy.pdf", file_bytes=b"pdf bytes")
    result = _result()
    run = service.record_extraction_run(
        upload_id=upload.id,
        status="succeeded",
        result=result,
    )
    first = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=result,
    )
    second = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=result,
    )
    service.record_decision(task_id=first.id, decision="skip")

    assert [task.id for task in service.list_tasks(status="pending")] == [second.id]
    assert [task.id for task in service.list_tasks(status="skipped")] == [first.id]
    assert [task.id for task in service.list_tasks(status=None, limit=1)] == [first.id]


def test_queue_counts_include_closed_tasks(mock_db_session):
    service = ReviewWorkflowService(mock_db_session)
    upload = service.create_upload(filename="policy.pdf", file_bytes=b"pdf bytes")
    result = _result()
    run = service.record_extraction_run(
        upload_id=upload.id,
        status="succeeded",
        result=result,
    )
    pending = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=result,
    )
    skipped = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=result,
    )
    failed = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=result,
    )
    service.record_decision(task_id=skipped.id, decision="skip")
    service.mark_task_failed(failed.id, "bad payload")

    counts = service.queue_counts()

    assert counts["pending"] == 1
    assert counts["skipped"] == 1
    assert counts["failed"] == 1
    assert counts["saved"] == 0
    assert counts["total"] == 3
    assert service.get_task(pending.id).id == pending.id
