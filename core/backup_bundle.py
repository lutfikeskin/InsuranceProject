"""Unified local backup bundle for database, COI holders, and telemetry."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from core.database import ApiUsage, AppEvent
from core.db_import import MergeResult, merge_database_from_file, validate_sqlite_db
from modules.coi.holders import HolderMergeResult, export_coi_holders_bytes, merge_coi_holders_from_bytes

BACKUP_FORMAT_VERSION = 1
DEFAULT_DB_PATH = Path("insurance_data.db")


class BackupBundleError(ValueError):
    """Raised when backup bundle cannot be read or applied."""


@dataclass
class TelemetryMergeResult:
    imported_app_events: int = 0
    skipped_app_events: int = 0
    imported_api_usage: int = 0
    skipped_api_usage: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class BackupImportResult:
    database: MergeResult
    holders: HolderMergeResult
    telemetry: TelemetryMergeResult


API_USAGE_FIELDS = (
    "timestamp",
    "model_name",
    "input_tokens",
    "output_tokens",
    "cost",
    "status",
    "request_type",
    "correlation_id",
    "error_message",
    "latency_ms",
)

APP_EVENT_FIELDS = (
    "timestamp",
    "event_name",
    "category",
    "status",
    "correlation_id",
    "object_type",
    "object_id",
    "duration_ms",
    "count_value",
    "value_float",
    "message",
    "metadata_json",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(row, field) for field in fields}


def export_telemetry_payload(session: Session) -> dict[str, Any]:
    """Return telemetry tables as JSON-safe data."""
    return {
        "format": "insurance_telemetry",
        "version": BACKUP_FORMAT_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "api_usage": [_row_dict(row, API_USAGE_FIELDS) for row in session.query(ApiUsage).all()],
        "app_events": [_row_dict(row, APP_EVENT_FIELDS) for row in session.query(AppEvent).all()],
    }


def build_backup_bundle(session: Session, db_path: str | Path = DEFAULT_DB_PATH) -> bytes:
    """Create zip backup with DB, holder JSON, and telemetry JSON."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise BackupBundleError(f"Database file not found: {db_path}")

    telemetry_payload = export_telemetry_payload(session)
    manifest = {
        "format": "insurance_app_backup",
        "version": BACKUP_FORMAT_VERSION,
        "created_at": datetime.utcnow().isoformat(),
        "contents": ["insurance_data.db", "coi_holders.json", "telemetry.json"],
    }

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.write(db_path, "insurance_data.db")
        zf.writestr("coi_holders.json", export_coi_holders_bytes())
        zf.writestr("telemetry.json", json.dumps(telemetry_payload, default=_json_default, indent=2))
    return buffer.getvalue()


def _json_signature(row: dict[str, Any], fields: tuple[str, ...]) -> str:
    normalized = {}
    for field in fields:
        value = row.get(field)
        if isinstance(value, datetime):
            value = value.isoformat()
        normalized[field] = value
    return json.dumps(normalized, sort_keys=True, default=_json_default)


def _existing_signatures(session: Session, model: Any, fields: tuple[str, ...]) -> set[str]:
    return {_json_signature(_row_dict(row, fields), fields) for row in session.query(model).all()}


def _clean_row(raw: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    row = {field: raw.get(field) for field in fields}
    row["timestamp"] = _parse_datetime(row.get("timestamp"))
    return row


def merge_telemetry_payload(session: Session, payload: dict[str, Any]) -> TelemetryMergeResult:
    """Merge telemetry tables, skipping duplicate rows by content signature."""
    if not isinstance(payload, dict):
        raise BackupBundleError("telemetry.json must be a JSON object.")

    result = TelemetryMergeResult()
    usage_signatures = _existing_signatures(session, ApiUsage, API_USAGE_FIELDS)
    event_signatures = _existing_signatures(session, AppEvent, APP_EVENT_FIELDS)

    for idx, raw in enumerate(payload.get("api_usage") or []):
        row = _clean_row(raw, API_USAGE_FIELDS)
        if row is None or row["timestamp"] is None:
            result.errors.append(f"Skipped api_usage row {idx + 1}: invalid row.")
            continue
        signature = _json_signature(row, API_USAGE_FIELDS)
        if signature in usage_signatures:
            result.skipped_api_usage += 1
            continue
        session.add(ApiUsage(**row))
        usage_signatures.add(signature)
        result.imported_api_usage += 1

    for idx, raw in enumerate(payload.get("app_events") or []):
        row = _clean_row(raw, APP_EVENT_FIELDS)
        if row is None or row["timestamp"] is None or not row.get("event_name"):
            result.errors.append(f"Skipped app_events row {idx + 1}: invalid row.")
            continue
        signature = _json_signature(row, APP_EVENT_FIELDS)
        if signature in event_signatures:
            result.skipped_app_events += 1
            continue
        session.add(AppEvent(**row))
        event_signatures.add(signature)
        result.imported_app_events += 1

    session.commit()
    return result


def import_backup_bundle(target_engine, telemetry_session: Session, data: bytes) -> BackupImportResult:
    """Import unified zip backup into live app data stores."""
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BackupBundleError("Backup file must be a valid .zip bundle.") from exc

    with zf:
        names = set(zf.namelist())
        required = {"insurance_data.db", "coi_holders.json", "telemetry.json"}
        missing = required - names
        if missing:
            raise BackupBundleError(f"Backup is missing: {', '.join(sorted(missing))}")

        os.makedirs(".cache", exist_ok=True)
        db_temp = None
        try:
            fd, db_temp = tempfile.mkstemp(suffix=".db", dir=".cache")
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(zf.read("insurance_data.db"))
            validate_sqlite_db(db_temp)
            database_result = merge_database_from_file(target_engine, db_temp)

            holders_result = merge_coi_holders_from_bytes(zf.read("coi_holders.json"))

            telemetry_payload = json.loads(zf.read("telemetry.json").decode("utf-8"))
            telemetry_result = merge_telemetry_payload(telemetry_session, telemetry_payload)
        except json.JSONDecodeError as exc:
            telemetry_session.rollback()
            raise BackupBundleError(f"Invalid telemetry JSON: {exc}") from exc
        finally:
            if db_temp and os.path.exists(db_temp):
                os.unlink(db_temp)

    return BackupImportResult(
        database=database_result,
        holders=holders_result,
        telemetry=telemetry_result,
    )
