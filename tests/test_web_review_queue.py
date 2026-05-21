from sqlalchemy import create_engine
import io
from datetime import date, timedelta
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, Policy, Customer
from core.notification_service import NotificationService
from core.review_model import UploadedDocument
from core.review_service import ReviewWorkflowService
from webapp import create_app
import webapp.app as webapp_module


def _result(policy_number="P1"):
    return {
        "classification": {
            "document_type": "declarations_page",
            "policy_type": "commercial_auto",
            "confidence": "high",
        },
        "policy": {
            "policy_number": policy_number,
            "carrier_name": "Progressive",
            "insured_name": "Jane Insured",
        },
        "coverages": [],
        "vehicles": [],
        "drivers": [],
        "policy_data_source": "full_policy",
    }


def _client_with_task():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    service = ReviewWorkflowService(session)
    upload = service.create_upload(filename="policy.pdf", file_bytes=b"pdf bytes")
    run = service.record_extraction_run(
        upload_id=upload.id,
        status="succeeded",
        result=_result(),
    )
    task = service.create_review_task(
        upload_id=upload.id,
        extraction_run_id=run.id,
        extraction_result=_result(),
    )
    session.close()

    app = create_app(session_factory=Session)
    app.config.update(TESTING=True)
    return app.test_client(), Session, task.id

def _dashboard_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        Policy(
            policy_number="DASH-1",
            carrier_name="Carrier A",
            insured_name="Dash User",
            premium="$1,000",
        )
    )
    session.commit()
    session.close()
    app = create_app(session_factory=Session)
    app.config.update(TESTING=True)
    return app.test_client()

def _process_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    app = create_app(session_factory=Session)
    app.config.update(TESTING=True, GEMINI_API_KEY="test-key")
    return app.test_client(), Session

def _compare_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add_all(
        [
            Policy(policy_number="CMP-A", carrier_name="Carrier A", insured_name="Compare User", premium="$100"),
            Policy(policy_number="CMP-B", carrier_name="Carrier B", insured_name="Compare User", premium="$200"),
        ]
    )
    session.commit()
    ids = [policy.id for policy in session.query(Policy).order_by(Policy.id.asc()).all()]
    session.close()
    app = create_app(session_factory=Session)
    app.config.update(TESTING=True)
    return app.test_client(), ids

def _database_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        Policy(policy_number="DB-1", carrier_name="DB Carrier", insured_name="Database User")
    )
    session.commit()
    session.add(Customer(full_name="Customer User"))
    session.commit()
    session.close()
    app = create_app(session_factory=Session)
    app.config.update(TESTING=True)
    return app.test_client(), Session

def _renewals_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    today = date.today()
    session.add_all(
        [
            Policy(policy_number="REN-1", carrier_name="Renew Carrier", insured_name="Renew User", expiration_date=today + timedelta(days=5)),
            Policy(policy_number="REN-2", carrier_name="Renew Carrier", insured_name="Watch User", expiration_date=today + timedelta(days=40)),
        ]
    )
    session.commit()
    session.close()
    app = create_app(session_factory=Session)
    app.config.update(TESTING=True)
    return app.test_client()


def _coi_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    policy = Policy(policy_number="COI-1", carrier_name="COI Carrier", insured_name="COI User")
    session.add(policy)
    session.commit()
    policy_id = policy.id
    session.close()
    app = create_app(session_factory=Session)
    app.config.update(TESTING=True)
    return app.test_client(), policy_id

def _renewals_action_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    today = date.today()
    policy = Policy(policy_number="REN-ACT", carrier_name="Renew Carrier", insured_name="Action User", expiration_date=today + timedelta(days=7))
    session.add(policy)
    session.commit()
    policy_id = policy.id
    session.close()
    app = create_app(session_factory=Session)
    app.config.update(TESTING=True)
    return app.test_client(), Session, policy_id







def test_process_policies_page_renders_form():
    client, _session_factory = _process_client()

    response = client.get("/process-policies")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Process Policies" in body
    assert "Extract and Send to Review Queue" in body


def test_process_policies_post_creates_review_tasks_for_batch(monkeypatch):
    client, Session = _process_client()

    def fake_process_pdf(file_bytes, api_key, status_callback=None, force_refresh=False, user_policy_type=None, allow_non_extractable=False):
        assert api_key == "test-key"
        if file_bytes == b"%PDF-1.4 first":
            return _result("UPLOAD-1"), {"source": "api"}, None
        return None, {"source": "api"}, "Extraction failed"

    monkeypatch.setattr(webapp_module, "process_pdf", fake_process_pdf)

    response = client.post(
        "/process-policies",
        data={
            "pdf_files": [
                (io.BytesIO(b"%PDF-1.4 first"), "first.pdf"),
                (io.BytesIO(b"%PDF-1.4 second"), "second.pdf"),
            ],
            "policy_type": "commercial_auto",
            "force_refresh": "on",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Created Review Tasks" in body
    assert "first.pdf" in body
    assert "Failed Uploads" in body
    assert "second.pdf" in body
    session = Session()
    try:
        tasks = ReviewWorkflowService(session).list_pending_tasks()
        assert len(tasks) == 1
        assert tasks[0].upload.filename == "first.pdf"
        assert tasks[0].extraction_result["policy"]["policy_number"] == "UPLOAD-1"
        failed_upload = session.get(UploadedDocument, 2)
        assert failed_upload is not None
        assert failed_upload.filename == "second.pdf"
        assert failed_upload.storage_uri is not None
    finally:
        session.close()


def test_process_policies_retry_uses_stored_bytes_and_creates_task(monkeypatch):
    client, Session = _process_client()

    def fake_process_pdf(file_bytes, api_key, status_callback=None, force_refresh=False, user_policy_type=None, allow_non_extractable=False):
        if allow_non_extractable:
            assert file_bytes == b"%PDF-1.4 second"
            return _result("RETRY-1"), {"source": "api"}, None
        return None, {"source": "api"}, "Extraction failed"

    monkeypatch.setattr(webapp_module, "process_pdf", fake_process_pdf)

    client.post(
        "/process-policies",
        data={
            "pdf_files": [(io.BytesIO(b"%PDF-1.4 second"), "second.pdf")],
            "policy_type": "commercial_auto",
        },
        content_type="multipart/form-data",
    )

    response = client.post("/process-policies/retry/1")

    assert response.status_code == 302
    assert "/review-queue?task_id=" in response.headers["Location"]
    session = Session()
    try:
        tasks = ReviewWorkflowService(session).list_pending_tasks()
        assert len(tasks) == 1
        assert tasks[0].extraction_result["policy"]["policy_number"] == "RETRY-1"
    finally:
        session.close()


def test_process_policies_save_batch_closes_extractable_tasks(monkeypatch):
    client, Session = _process_client()

    monkeypatch.setattr(
        webapp_module,
        "process_pdf",
        lambda file_bytes, api_key, status_callback=None, force_refresh=False, user_policy_type=None, allow_non_extractable=False: (_result("BATCH-1"), {"source": "api"}, None),
    )

    client.post(
        "/process-policies",
        data={
            "pdf_files": [(io.BytesIO(b"%PDF-1.4 one"), "one.pdf")],
            "policy_type": "commercial_auto",
        },
        content_type="multipart/form-data",
    )

    response = client.post("/process-policies/save-batch", data={"task_ids": ["1"]})

    assert response.status_code == 200
    session = Session()
    try:
        task = ReviewWorkflowService(session).get_task(1)
        assert task.status == "saved"
    finally:
        session.close()

def test_compare_page_renders_comparison_summary():
    client, ids = _compare_client()

    response = client.get(f"/compare?policy_a={ids[0]}&policy_b={ids[1]}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Compare Policies" in body
    assert "Scalar fields changed" in body
    assert "Vehicles" in body
    assert "Coverages" in body


def test_create_coi_page_renders_policy_selection():
    client, policy_id = _coi_client()

    response = client.get(f"/create-coi?q=COI&policy_id={policy_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Create COI" in body
    assert "COI-1" in body
    assert "Generate COI PDF" in body


def test_create_coi_post_returns_pdf(monkeypatch):
    client, policy_id = _coi_client()

    def fake_generate(self, policy_data, holder_data, desc_font_size=8):
        assert policy_data["policy_number"] == "COI-1"
        assert holder_data["name"] == "Holder Co"
        return b"%PDF-1.4 fake coi"

    monkeypatch.setattr(webapp_module.COIGenerator, "generate_coi", fake_generate)

    response = client.post(
        "/create-coi",
        data={
            "q": "COI",
            "policy_id": str(policy_id),
            "holder_name": "Holder Co",
            "holder_address": "123 Main",
            "holder_city": "Austin",
            "holder_state": "TX",
            "holder_zip": "78701",
            "description": "Sample description",
        },
    )

    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF-1.4 fake coi")


def test_create_coi_bulk_mode_returns_zip(monkeypatch):
    client, policy_id = _coi_client()

    monkeypatch.setattr(
        webapp_module,
        "load_companies",
        lambda _path: {"Company A": {"name": "Company A", "address": "1 St", "city": "Austin", "state": "TX", "zip": "78701"}},
    )

    def fake_generate(self, policy_data, holder_data, desc_font_size=8):
        assert holder_data["name"] == "Company A"
        return b"%PDF-1.4 bulk coi"

    monkeypatch.setattr(webapp_module.COIGenerator, "generate_coi", fake_generate)

    response = client.post(
        "/create-coi",
        data={
            "q": "COI",
            "policy_id": str(policy_id),
            "bulk_mode": "on",
            "coi_type": "Certificate Holder",
            "selected_companies": ["Company A"],
        },
    )

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
def test_create_coi_lienholder_requires_selected_vehicle():
    client, policy_id = _coi_client()

    response = client.post(
        "/create-coi",
        data={
            "q": "COI",
            "policy_id": str(policy_id),
            "coi_type": "Lienholder",
            "holder_name": "Lien Holder",
        },
    )

    assert response.status_code == 400
    assert "Lienholder COIs require at least one selected vehicle" in response.get_data(as_text=True)


def test_renewals_page_renders_bucketed_policies():
    client = _renewals_client()

    response = client.get("/renewals")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Renewals" in body
    assert "REN-1" in body
    assert "REN-2" in body


def test_renewals_page_shows_selected_policy_draft_and_logs_contact():
    client, Session, policy_id = _renewals_action_client()

    response = client.get(f"/renewals?policy_id={policy_id}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "REN-ACT" in body
    assert "Email Draft" in body

    response = client.post(
        "/renewals/log-contact",
        data={"policy_id": str(policy_id), "method": "phone", "notes": "Called insured"},
    )
    assert response.status_code == 302
    session = Session()
    try:
        last = NotificationService(session).last_contact(policy_id)
        assert last is not None
        assert last.method == "phone"
        assert last.notes == "Called insured"
    finally:
        session.close()

def test_renewals_draft_download_returns_text_file():
    client, _Session, policy_id = _renewals_action_client()

    response = client.post(
        "/renewals/draft-download",
        data={
            "policy_id": str(policy_id),
            "download_filename": "draft.txt",
            "body": "Hello world",
        },
    )

    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert response.data == b"Hello world"


def test_renewals_log_draft_records_email_draft():
    client, Session, policy_id = _renewals_action_client()

    response = client.post(
        "/renewals/log-draft",
        data={"policy_id": str(policy_id), "to": "insured@example.com"},
    )

    assert response.status_code == 302
    session = Session()
    try:
        last = NotificationService(session).last_contact(policy_id)
        assert last is not None
        assert last.method == "email_draft"
        assert "insured@example.com" in (last.notes or "")
    finally:
        session.close()


def test_database_policy_save_updates_nested_collections():
    client, Session = _database_client()

    response = client.post(
        "/database/policy/1/save",
        data={
            "policy_number": "DB-1",
            "carrier_name": "DB Carrier",
            "insured_name": "Database User",
            "effective_date": "",
            "expiration_date": "",
            "premium": "",
            "vehicles_json": '[{\"vin\": \"VIN-1\", \"make\": \"Ford\", \"model\": \"F150\", \"type\": \"Pickup\"}]',
            "drivers_json": '[{\"full_name\": \"Driver A\", \"license_number\": \"X1\", \"is_excluded\": false}]',
            "coverages_json": '[{\"type\": \"Liability\", \"coverage_code\": \"AUTO_LIAB_CSL\", \"family\": \"auto_liability\", \"limits\": {\"combined_single_limit\": 1000000}}]',
            "additional_interests_json": '[{\"name\": \"Bank A\", \"address\": \"123 Main\", \"interest_type\": \"Loss Payee\"}]',
        },
    )
    assert response.status_code == 200
    session = Session()
    try:
        policy = session.get(Policy, 1)
        assert len(policy.vehicles) == 1
        assert policy.vehicles[0].vin == "VIN-1"
        assert len(policy.drivers) == 1
        assert policy.drivers[0].full_name == "Driver A"
        assert len(policy.coverages) == 1
        assert policy.coverages[0].coverage_code == "AUTO_LIAB_CSL"
        assert len(policy.additional_interests) == 1
        assert policy.additional_interests[0].name == "Bank A"
    finally:
        session.close()


def test_database_policy_detail_and_save_updates_policy():
    client, Session = _database_client()

    response = client.get("/database/policy/1")
    assert response.status_code == 200
    assert "Policy DB-1" in response.get_data(as_text=True)

    response = client.post(
        "/database/policy/1/save",
        data={
            "policy_number": "DB-1A",
            "carrier_name": "DB Carrier Updated",
            "insured_name": "Database User Updated",
            "effective_date": "2026-01-01",
            "expiration_date": "2027-01-01",
            "premium": "$500",
        },
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Updated" in body or "No changes detected" in body
    session = Session()
    try:
        policy = session.get(Policy, 1)
        assert policy is not None
        assert policy.carrier_name == "DB Carrier Updated"
        assert policy.insured_name == "Database User Updated"
    finally:
        session.close()


def test_database_policy_delete_removes_policy():
    client, Session = _database_client()

    response = client.post("/database/policy/1/delete")

    assert response.status_code == 200
    session = Session()
    try:
        assert session.get(Policy, 1) is None
    finally:
        session.close()


def test_database_export_returns_excel_workbook():
    client, _Session = _database_client()

    response = client.get("/database/export?q=DB-1")

    assert response.status_code == 200
    assert response.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def test_database_page_renders_policy_and_customer_tables():
    client, _Session = _database_client()

    response = client.get("/database?q=DB-1&customer_q=Database")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Database" in body
    assert "DB-1" in body
    assert "Database User" in body

def test_dashboard_page_renders_metrics_and_recent_policy():
    client = _dashboard_client()

    response = client.get("/dashboard")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Insurance Document Platform" in body
    assert "Total Policies" in body
    assert "DASH-1" in body
    assert "Dash User" in body
    assert "Create COI" in body
def test_settings_page_updates_runtime_knobs():
    client = _dashboard_client()

    response = client.get("/settings")
    assert response.status_code == 200
    assert "Settings" in response.get_data(as_text=True)

    response = client.post(
        "/settings",
        data={"action": "save", "confidence_gate_threshold": "high", "gemini_api_key": "abc123"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert client.application.config["CONFIDENCE_GATE_THRESHOLD"] == "high"
    assert client.application.config["GEMINI_API_KEY"] == "abc123"

    response = client.post("/settings/reset-usage")
    assert response.status_code == 204

def test_database_customer_detail_and_save_updates_customer():
    client, Session = _database_client()

    response = client.get("/database/customer/1")
    assert response.status_code == 200
    assert "Customer User" in response.get_data(as_text=True)

    response = client.post(
        "/database/customer/1/save",
        data={"full_name": "Updated Customer", "entity_name": "DBA Name", "entity_type": "dba"},
    )
    assert response.status_code == 200
    session = Session()
    try:
        customer = session.get(Customer, 1)
        assert customer is not None
        assert customer.full_name == "Updated Customer"
        assert any(entity.entity_name == "DBA Name" for entity in customer.entities)
    finally:
        session.close()
def test_review_queue_page_renders_pending_task():
    client, _session_factory, task_id = _client_with_task()

    response = client.get("/review-queue")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Review Queue" in body
    assert f"#{task_id}" in body
    assert "policy.pdf" in body
    assert "Jane Insured" in body


def test_review_queue_table_filter_renders_partial():
    client, _session_factory, _task_id = _client_with_task()

    response = client.get("/review-queue/table?status=pending")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "<table" in body
    assert "Progressive" in body


def test_review_queue_detail_renders_selected_task_json():
    client, _session_factory, task_id = _client_with_task()

    response = client.get(f"/review-queue/{task_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f"Task #{task_id}" in body
    assert "P1" in body
    assert "Stored extraction JSON" in body



def test_review_queue_applies_confidence_gate_to_form():
    client, Session, task_id = _client_with_task()
    session = Session()
    try:
        task = ReviewWorkflowService(session).get_task(task_id)
        assert task is not None
        task.extraction_result = {
            **task.extraction_result,
            "policy": {
                **task.extraction_result["policy"],
                "policy_number_confidence": "low",
            },
        }
        session.commit()
    finally:
        session.close()

    client.application.config["CONFIDENCE_GATE_THRESHOLD"] = "high"
    response = client.get(f"/review-queue/{task_id}")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'name="policy_number" value=""' in body
    assert "field(s) were cleared by the confidence gate" in body
def test_skip_route_closes_task_and_returns_refreshed_table():
    client, Session, task_id = _client_with_task()

    response = client.post(f"/review-queue/{task_id}/skip", data={"status": "pending"})

    assert response.status_code == 200
    assert "No review tasks match this filter" in response.get_data(as_text=True)
    session = Session()
    try:
        task = ReviewWorkflowService(session).get_task(task_id)
        assert task.status == "skipped"
        assert task.decision == "skip"
    finally:
        session.close()


def test_fail_route_marks_task_failed():
    client, Session, task_id = _client_with_task()

    response = client.post(f"/review-queue/{task_id}/fail", data={"status": "pending"})

    assert response.status_code == 200
    session = Session()
    try:
        task = ReviewWorkflowService(session).get_task(task_id)
        assert task.status == "failed"
        assert task.notes == "Marked failed from HTMX review queue."
    finally:
        session.close()

def test_save_route_applies_policy_edits_and_closes_task():
    client, Session, task_id = _client_with_task()

    response = client.post(
        f"/review-queue/{task_id}/save",
        data={
            "status": "pending",
            "policy_number": "P1-EDITED",
            "carrier_name": "Edited Carrier",
            "insured_name": "Edited Insured",
            "effective_date": "2026-01-01",
            "expiration_date": "2027-01-01",
            "premium": "$123",
            "vehicles_json": '[{\"vin\": \"VIN123\", \"make\": \"Ford\"}]',
            "drivers_json": '[{\"full_name\": \"Driver One\", \"is_excluded\": false}]',
            "coverages_json": '[{\"coverage_code\": \"AUTO_LIAB_CSL\", \"family\": \"auto_liability\", \"limit_structure\": \"csl\", \"limits\": {\"combined_single_limit\": 1000000}}]',
            "additional_interests_json": '[{\"name\": \"Bank\", \"interest_type\": \"Loss Payee\"}]',
        },
    )

    assert response.status_code == 200
    assert "No review tasks match this filter" in response.get_data(as_text=True)
    session = Session()
    try:
        task = ReviewWorkflowService(session).get_task(task_id)
        assert task.status == "saved"
        assert task.decision == "save_new"
        assert task.human_edits["policy"]["policy_number"] == "P1-EDITED"
        saved_policy = task.target_policy
        assert saved_policy is None
        from core.database import Policy

        policy = session.query(Policy).filter_by(policy_number="P1-EDITED").one()
        assert policy.carrier_name == "Edited Carrier"
        assert policy.insured_name == "Edited Insured"
        assert policy.premium == "$123"

        assert task.human_edits["vehicles"][0]["vin"] == "VIN123"
        assert task.human_edits["drivers"][0]["full_name"] == "Driver One"
        assert task.human_edits["additional_interests"][0]["name"] == "Bank"
    finally:
        session.close()

def test_save_route_rejects_invalid_json_and_keeps_task_pending():
    client, Session, task_id = _client_with_task()

    response = client.post(
        f"/review-queue/{task_id}/save",
        data={
            "status": "pending",
            "policy_number": "P1",
            "carrier_name": "Progressive",
            "insured_name": "Jane Insured",
            "vehicles_json": '{not valid json}',
            "drivers_json": '[]',
            "coverages_json": '[]',
            "additional_interests_json": '[]',
        },
    )

    assert response.status_code == 400
    body = response.get_data(as_text=True)
    assert "vehicles_json contains invalid JSON" in body
    session = Session()
    try:
        task = ReviewWorkflowService(session).get_task(task_id)
        assert task.status == "pending"
        assert task.decision is None
    finally:
        session.close()
