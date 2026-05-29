from __future__ import annotations

from datetime import datetime, timedelta

from core.database import AppEvent, ApiUsage, get_session, init_db
from core.services import UsageService
from core.telemetry import TelemetryService, log_timing, private_hash, redact_payload
from views.telemetry import _build_window, _coi_stats


def test_redact_payload_masks_sensitive_fields(monkeypatch):
    monkeypatch.setenv("TELEMETRY_HASH_SALT", "test-salt")
    payload = {
        "api_key": "AIzaSyExampleSecretValue",
        "policy_number": "POL-12345",
        "vin": "1HGCM82633A004352",
        "insured_name": "Jane Doe",
        "nested": {"email": "jane@example.com"},
    }

    redacted = redact_payload(payload)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["policy_number"].startswith("policy#")
    assert redacted["vin"].startswith("vin#")
    assert redacted["insured_name"].startswith("name#")
    assert redacted["nested"]["email"] == "[REDACTED]"
    assert redacted["policy_number"] == f"policy#{private_hash('POL-12345', length=8)}"


def test_redact_payload_preserves_operational_hashes():
    redacted = redact_payload({"file_hash": "abcdef123456", "layout_fingerprint": "layout-v1"})
    assert redacted["file_hash"] == "abcdef123456"
    assert redacted["layout_fingerprint"] == "layout-v1"


def test_telemetry_service_records_event_with_redacted_metadata(tmp_path):
    db_path = tmp_path / "telemetry.db"
    engine = init_db(str(db_path))
    session = get_session(engine)
    telemetry = TelemetryService(session)

    telemetry.record_event(
        "coi_generated_single",
        category="coi",
        status="success",
        correlation_id="coi_123",
        object_type="policy",
        object_id="42",
        count_value=1,
        message="failure for jane@example.com on policy POL-12345",
        metadata={
            "policy_number": "POL-12345",
            "holder_name": "Jane Doe",
            "output_bytes": 2048,
        },
    )

    event = session.query(AppEvent).one()
    assert event.event_name == "coi_generated_single"
    assert event.category == "coi"
    assert event.status == "success"
    assert event.correlation_id == "coi_123"
    assert event.object_type == "policy"
    assert event.object_id == "42"
    assert event.count_value == 1
    assert event.message == "failure for [EMAIL] on policy [ID]"
    assert event.metadata_json["policy_number"].startswith("policy#")
    assert event.metadata_json["holder_name"].startswith("name#")
    assert event.metadata_json["output_bytes"] == 2048

    session.close()


def test_telemetry_retention_and_summary(tmp_path):
    db_path = tmp_path / "retention.db"
    engine = init_db(str(db_path))
    session = get_session(engine)
    telemetry = TelemetryService(session)

    old_event = AppEvent(
        event_name="old_event",
        category="test",
        status="success",
        timestamp=datetime.utcnow() - timedelta(days=120),
    )
    session.add(old_event)
    session.commit()
    telemetry.record_event(
        "new_event",
        category="test",
        status="success",
        count_value=3,
    )

    deleted = telemetry.purge_old_events(retention_days=90)
    summary = telemetry.get_event_summary(days=30)

    assert deleted == 1
    assert session.query(AppEvent).filter_by(event_name="old_event").count() == 0
    assert any(row["event_name"] == "new_event" and row["count_value"] == 3 for row in summary)
    session.close()


def test_telemetry_coi_stats_counts_bulk_generated_files(tmp_path):
    db_path = tmp_path / "coi_counts.db"
    engine = init_db(str(db_path))
    session = get_session(engine)
    telemetry = TelemetryService(session)

    telemetry.record_event(
        "coi_generated_single",
        category="coi",
        status="success",
        count_value=1,
    )
    telemetry.record_event(
        "coi_generated_bulk",
        category="coi",
        status="success",
        count_value=1,
        metadata={"generated_count": 20, "requested_count": 20},
    )

    stats = _coi_stats(session, _build_window("Last 30 days"))

    assert stats["single"] == 1
    assert stats["bulk"] == 20
    assert stats["total"] == 21
    session.close()


def test_log_timing_yields_elapsed_callable():
    with log_timing("unit_test_timing") as elapsed_ms:
        assert callable(elapsed_ms)
        assert elapsed_ms() >= 0


def test_usage_service_records_failed_usage(tmp_path):
    db_path = tmp_path / "usage.db"
    engine = init_db(str(db_path))
    session = get_session(engine)
    usage = UsageService(session)

    row = usage.log_usage(
        model_name="gemini-3.1-flash-lite",
        input_tokens=0,
        output_tokens=0,
        request_type="classification",
        status="failure",
        correlation_id="llm_abc",
        error_message="model failed",
        latency_ms=321,
    )

    stored = session.query(ApiUsage).one()
    assert stored.id == row.id
    assert stored.status == "failure"
    assert stored.correlation_id == "llm_abc"
    assert stored.error_message == "model failed"
    assert stored.latency_ms == 321
    assert stored.cost == 0

    session.close()
