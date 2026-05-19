"""
NotificationService — thin CRUD + query layer over NotificationLog rows.

Mirrors the shape of `core/history_service.py`: takes a session in the
constructor, never auto-commits, leaves transaction control to the caller.

Method validation is intentionally loose. The model's `method` column is a
free-form string, and we want the service to accept new methods (e.g.
`"sms"`, `"webhook"`, `"auto_email"`) without a code change. Unknown values
get a logger warning so we can spot typos in the field, but the write still
goes through.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .logger import logger
from .notification_model import NotificationLog

# Methods we know about today. Pure documentation — not enforced. Anything
# else still writes, but logs a one-line warning so a typo doesn't sit in
# the DB forever undetected.
KNOWN_METHODS = frozenset({"email_draft", "email_auto", "phone", "manual", "other"})


class NotificationService:
    def __init__(self, session: Session):
        self.session = session

    def record_contact(
        self,
        policy_id: int,
        customer_id: Optional[int] = None,
        method: str = "email_draft",
        notes: Optional[str] = None,
        contacted_at: Optional[datetime] = None,
    ) -> NotificationLog:
        """
        Append a row to notification_log. Returns the freshly-flushed row so
        the caller can read its `id` / `created_at`.

        Does NOT commit. Caller owns the transaction.
        """
        if method not in KNOWN_METHODS:
            logger.warning(
                f"NotificationService: unknown method '{method}' for policy {policy_id}. "
                f"Allowed without enforcement; consider adding it to KNOWN_METHODS."
            )

        ts = contacted_at or datetime.now(timezone.utc)
        row = NotificationLog(
            policy_id=policy_id,
            customer_id=customer_id,
            method=method,
            notes=notes,
            contacted_at=ts,
            created_at=datetime.now(timezone.utc),
        )
        try:
            self.session.add(row)
            self.session.flush()  # populate row.id so the caller can use it
        except Exception:
            logger.exception(
                "NotificationService.record_contact failed for policy %s", policy_id
            )
            raise
        return row

    def get_for_policy(self, policy_id: int, limit: int = 10) -> list[NotificationLog]:
        """Most-recent-first list of contact rows for one policy."""
        q = (
            self.session.query(NotificationLog)
            .filter(NotificationLog.policy_id == policy_id)
            .order_by(NotificationLog.contacted_at.desc())
        )
        if limit:
            q = q.limit(limit)
        return q.all()

    def last_contact(self, policy_id: int) -> Optional[NotificationLog]:
        """Single most-recent contact row for a policy, or None if never contacted."""
        return (
            self.session.query(NotificationLog)
            .filter(NotificationLog.policy_id == policy_id)
            .order_by(NotificationLog.contacted_at.desc())
            .first()
        )

    def has_contact_since(self, policy_id: int, since: datetime) -> bool:
        """
        True iff the policy has at least one contact row at or after `since`.

        Used by the Renewals page to filter out policies the broker just
        reached out to — no point showing them again every page reload.
        """
        return (
            self.session.query(NotificationLog.id)
            .filter(
                NotificationLog.policy_id == policy_id,
                NotificationLog.contacted_at >= since,
            )
            .first()
            is not None
        )

    def count_in_window(self, start: datetime, end: datetime) -> int:
        """
        How many contact rows were logged in [start, end). End-exclusive so
        callers can chain windows without double-counting boundary rows.
        """
        return (
            self.session.query(func.count(NotificationLog.id))
            .filter(
                NotificationLog.contacted_at >= start,
                NotificationLog.contacted_at < end,
            )
            .scalar()
            or 0
        )
