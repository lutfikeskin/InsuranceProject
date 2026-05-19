"""
NotificationLog — record of a renewal contact attempt for a policy.

This is the foundation of the renewal-reminder workflow. The Renewals page
writes a row here every time a broker generates an email draft, logs a phone
call, or otherwise records that they've reached out about an upcoming
expiration. Future automated-email integrations (out of scope for now — IT's
problem) read and write the same table so the broker never sees the same
policy show up twice if it's already been contacted.

Design notes:
- Foreign keys are uni-directional (we don't add `back_populates` on the
  Policy / Customer models). Service-layer queries are explicit enough that
  the convenience isn't worth the coupling.
- `method` is a free-form string validated at the service layer rather than
  at the DB so we can add new methods (auto_email, sms, webhook) without a
  migration. Known values: "email_draft", "email_auto", "phone",
  "manual", "other".
- No user_id column. The app has no auth yet; IT will add a foreign key
  later when they introduce a User model. Until then a single broker is
  assumed.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from datetime import datetime, timezone

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=False, index=True)
    customer_id = Column(
        Integer,
        ForeignKey("customers.id"),
        nullable=True,
        index=True,
    )
    contacted_at = Column(DateTime, default=_utcnow, nullable=False)
    method = Column(String, nullable=False, default="email_draft")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
