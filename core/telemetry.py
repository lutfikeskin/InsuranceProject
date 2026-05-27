from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from sqlalchemy import func

from core.logger import logger
from .database import AppEvent

SENSITIVE_KEYS = {
    "api_key",
    "gemini_api_key",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "policy_number",
    "policy_no",
    "vin",
    "insured_name",
    "business_name",
    "holder_name",
    "address",
    "insured_address",
    "email",
    "primary_email",
    "phone",
    "primary_phone",
    "license_number",
}

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]*)?(?:\(?\d{3}\)?[-.\s]*)\d{3}[-.\s]*\d{4}\b")
VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
API_KEY_RE = re.compile(r"\b(?:AIza[0-9A-Za-z\-_]{20,}|[A-Za-z0-9_\-]{32,})\b")
POLICY_LIKE_RE = re.compile(
    r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9][A-Z0-9-]{5,}\b",
    re.IGNORECASE,
)
DEFAULT_EVENT_RETENTION_DAYS = int(os.getenv("APP_EVENT_RETENTION_DAYS", "90"))


def new_correlation_id(prefix: str = "evt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def short_hash(value: Any, *, length: int = 12) -> str:
    raw = str(value).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:length]


def private_hash(value: Any, *, length: int = 8) -> str:
    """Hash sensitive business identifiers, optionally salted for deployed environments."""
    salt = os.getenv("TELEMETRY_HASH_SALT", "")
    raw = f"{salt}:{value}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:length]


def _mask_text(text: str, *, keep_tail: int = 4) -> str:
    if not text:
        return text
    if len(text) <= keep_tail:
        return "*" * len(text)
    return f"***{text[-keep_tail:]}"


def _redact_free_text(text: str) -> str:
    redacted = API_KEY_RE.sub("[API_KEY]", text)
    redacted = EMAIL_RE.sub("[EMAIL]", redacted)
    redacted = PHONE_RE.sub("[PHONE]", redacted)
    redacted = VIN_RE.sub("[VIN]", redacted)
    redacted = POLICY_LIKE_RE.sub("[ID]", redacted)
    return redacted[:1000]


def redact_value(value: Any, key: str | None = None) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, dict):
        return redact_payload(value)
    if isinstance(value, list):
        return [redact_value(v, key=key) for v in value]
    if isinstance(value, tuple):
        return [redact_value(v, key=key) for v in value]

    text = str(value)
    k = (key or "").lower().strip()

    if k in {"message", "error", "error_message", "detail"}:
        return _redact_free_text(text)
    if k in {"file_hash", "hash", "layout_fingerprint"}:
        return text
    if k in {"policy_number", "policy_no"}:
        return f"policy#{private_hash(text, length=8)}"
    if k == "vin":
        return f"vin#{private_hash(text, length=8)}"
    if k in {"insured_name", "business_name", "holder_name"}:
        return f"name#{private_hash(text, length=8)}"
    if k in {"address", "insured_address"}:
        return f"addr#{private_hash(text, length=8)}"

    if k in SENSITIVE_KEYS or any(s in k for s in ("password", "secret", "token", "api_key")):
        return "[REDACTED]"

    if not text:
        return text

    if EMAIL_RE.search(text) or PHONE_RE.search(text):
        return "[REDACTED]"

    if API_KEY_RE.fullmatch(text) and len(text) >= 24:
        return "[REDACTED]"

    if VIN_RE.search(text):
        return VIN_RE.sub("[VIN]", text)

    # Mask obvious long identifier-like strings even if the key is not known.
    if len(text) >= 12 and re.fullmatch(r"[A-Za-z0-9\-_/ ]+", text):
        if sum(ch.isdigit() for ch in text) >= 4:
            return _mask_text(text, keep_tail=4)

    return text


def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: redact_value(v, key=k) for k, v in payload.items()}
    if isinstance(payload, list):
        return [redact_value(v) for v in payload]
    if isinstance(payload, tuple):
        return [redact_value(v) for v in payload]
    return redact_value(payload)


def log_event(
    event_name: str,
    *,
    level: str = "info",
    correlation_id: str | None = None,
    status: str | None = None,
    message: str | None = None,
    duration_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"event": event_name}
    if correlation_id:
        payload["correlation_id"] = correlation_id
    if status:
        payload["status"] = status
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if message:
        payload["message"] = redact_value(message)
    if metadata:
        payload["metadata"] = redact_payload(metadata)

    log_line = json.dumps(payload, sort_keys=True, default=str)
    getattr(logger, level.lower(), logger.info)(log_line)
    return payload


@contextmanager
def log_timing(
    event_name: str,
    *,
    correlation_id: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> Iterator[Callable[[], int]]:
    started = time.perf_counter()
    try:
        yield lambda: int((time.perf_counter() - started) * 1000)
    except Exception as exc:
        log_event(
            event_name,
            level="error",
            correlation_id=correlation_id,
            status="failure",
            duration_ms=int((time.perf_counter() - started) * 1000),
            message=str(exc),
            metadata=metadata,
        )
        raise
    else:
        log_event(
            event_name,
            level=level,
            correlation_id=correlation_id,
            status="success",
            duration_ms=int((time.perf_counter() - started) * 1000),
            metadata=metadata,
        )


class TelemetryService:
    def __init__(self, session):
        self.session = session

    def record_event(
        self,
        event_name: str,
        *,
        category: str | None = None,
        status: str | None = None,
        correlation_id: str | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        duration_ms: int | None = None,
        count_value: int | None = None,
        value_float: float | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        event = AppEvent(
            event_name=event_name,
            category=category,
            status=status,
            correlation_id=correlation_id,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            duration_ms=duration_ms,
            count_value=count_value,
            value_float=value_float,
            message=redact_value(message, key="message") if message else None,
            metadata_json=redact_payload(metadata) if metadata else None,
        )
        try:
            self.session.add(event)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            logger.warning(f"Telemetry event write failed: {exc}")
            return None
        return event

    def purge_old_events(self, retention_days: int = DEFAULT_EVENT_RETENTION_DAYS) -> int:
        cutoff = datetime.utcnow() - timedelta(days=max(1, int(retention_days)))
        try:
            deleted = self.session.query(AppEvent).filter(AppEvent.timestamp < cutoff).delete()
            self.session.commit()
            return int(deleted or 0)
        except Exception as exc:
            self.session.rollback()
            logger.warning(f"Telemetry retention cleanup failed: {exc}")
            return 0

    def get_event_summary(self, days: int = 30) -> list[dict[str, Any]]:
        cutoff = datetime.utcnow() - timedelta(days=max(1, int(days)))
        rows = (
            self.session.query(
                AppEvent.event_name,
                AppEvent.category,
                AppEvent.status,
                func.count(AppEvent.id),
                func.sum(AppEvent.count_value),
            )
            .filter(AppEvent.timestamp >= cutoff)
            .group_by(AppEvent.event_name, AppEvent.category, AppEvent.status)
            .order_by(AppEvent.event_name.asc())
            .all()
        )
        return [
            {
                "event_name": event_name,
                "category": category,
                "status": status,
                "events": int(count or 0),
                "count_value": int(total or 0),
            }
            for event_name, category, status, count, total in rows
        ]

    def record_metric(
        self,
        metric_name: str,
        *,
        value: int | float = 1,
        category: str | None = None,
        correlation_id: str | None = None,
        object_type: str | None = None,
        object_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        if isinstance(value, int):
            return self.record_event(
                metric_name,
                category=category,
                status="metric",
                correlation_id=correlation_id,
                object_type=object_type,
                object_id=object_id,
                count_value=value,
                metadata=metadata,
            )
        return self.record_event(
            metric_name,
            category=category,
            status="metric",
            correlation_id=correlation_id,
            object_type=object_type,
            object_id=object_id,
            value_float=float(value),
            metadata=metadata,
        )
