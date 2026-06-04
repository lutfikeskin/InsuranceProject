from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class CustomerHistory(Base):
    """Append-only audit log for Customer changes.

    Mirrors PolicyHistory in shape and contract. One row per recorded event;
    `changes` is a per-field delta list, never a full-row snapshot, so the
    timeline shows what changed without bloating storage.
    """

    __tablename__ = "customer_history"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 'Manual_Edit' | 'CustomerResolver' | 'PolicyService' | 'Merge'
    source = Column(String, nullable=False)

    # 'CREATED' | 'UPDATED' | 'ENTITY_ADDED' | 'ENTITY_REMOVED' |
    # 'MERGED_INTO' | 'MERGED_FROM' | 'POLICY_LINKED' | 'POLICY_UNLINKED'
    event_type = Column(String, nullable=False)

    customer_version = Column(Integer, nullable=False, default=1)

    # [{"field": "full_name", "old_value": "...", "new_value": "..."}]
    changes = Column(JSON, nullable=False)

    notes = Column(Text, nullable=True)

    customer = relationship("Customer", back_populates="history")
