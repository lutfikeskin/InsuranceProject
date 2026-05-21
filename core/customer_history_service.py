"""Append-only audit log for Customer changes.

Mirrors HistoryService in shape and contract. Every recorded event is one
CustomerHistory row with a per-field `changes` list. Callers pass the source
string so the timeline can show whether a change came from the UI, the
extraction pipeline, or a merge.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from .customer_history_model import CustomerHistory
from .database import Customer, CustomerEntity


# Source constants — kept as bare strings on purpose so call sites stay
# greppable and CustomerHistory rows are self-describing in raw SQL.
SOURCE_MANUAL = "Manual_Edit"
SOURCE_RESOLVER = "CustomerResolver"
SOURCE_POLICY_SERVICE = "PolicyService"
SOURCE_MERGE = "Merge"


class CustomerHistoryService:
    """Records customer-level audit events.

    Use one instance per request / session scope; the service is stateless
    apart from holding a SQLAlchemy session.
    """

    SCALAR_FIELDS = ("full_name", "primary_email", "primary_phone", "needs_real_name_entry")

    def __init__(self, session: Session):
        self.session = session

    # ---------------- public API ----------------

    def record_field_changes(
        self,
        customer: Customer,
        new_values: dict[str, Any],
        *,
        source: str,
        event_type: str = "UPDATED",
        notes: str | None = None,
    ) -> list[dict]:
        """Diff scalar fields and write history if anything actually changed.

        Mutates `customer` in place for fields in `new_values` that belong to
        SCALAR_FIELDS. Returns the changes list (empty if nothing changed).
        """
        changes: list[dict] = []
        for field in self.SCALAR_FIELDS:
            if field not in new_values:
                continue
            old = getattr(customer, field, None)
            new = new_values[field]
            if self._normalize(old) != self._normalize(new):
                changes.append(
                    {
                        "field": field,
                        "old_value": _serialize(old),
                        "new_value": _serialize(new),
                    }
                )
                setattr(customer, field, new)
        if changes:
            customer.updated_at = datetime.utcnow()
            self._write(customer, source=source, event_type=event_type, changes=changes, notes=notes)
        return changes

    def record_creation(self, customer: Customer, *, source: str = SOURCE_RESOLVER, notes: str | None = None) -> None:
        changes = [
            {
                "field": "full_name",
                "old_value": None,
                "new_value": customer.full_name,
            }
        ]
        self._write(customer, source=source, event_type="CREATED", changes=changes, notes=notes)

    def record_entity_added(
        self,
        customer: Customer,
        entity: CustomerEntity,
        *,
        source: str,
        notes: str | None = None,
    ) -> None:
        changes = [
            {
                "field": "entity",
                "old_value": None,
                "new_value": {
                    "entity_name": entity.entity_name,
                    "entity_type": entity.entity_type,
                    "is_primary": bool(entity.is_primary),
                },
            }
        ]
        customer.updated_at = datetime.utcnow()
        self._write(customer, source=source, event_type="ENTITY_ADDED", changes=changes, notes=notes)

    def record_entity_removed(
        self,
        customer: Customer,
        entity: CustomerEntity,
        *,
        source: str,
        notes: str | None = None,
    ) -> None:
        changes = [
            {
                "field": "entity",
                "old_value": {
                    "entity_name": entity.entity_name,
                    "entity_type": entity.entity_type,
                    "is_primary": bool(entity.is_primary),
                },
                "new_value": None,
            }
        ]
        customer.updated_at = datetime.utcnow()
        self._write(customer, source=source, event_type="ENTITY_REMOVED", changes=changes, notes=notes)

    def record_merge(
        self,
        kept: Customer,
        merged: Customer,
        *,
        moved_policy_count: int = 0,
        moved_entity_count: int = 0,
        notes: str | None = None,
    ) -> None:
        """Write the merge event on the surviving customer.

        Logging on the merged side is futile — `customer_history.customer_id`
        has ON DELETE CASCADE, so any row written for `merged` is wiped the
        moment the caller deletes that customer. The kept-side row carries
        full context (merged_id, merged name, counts) so the audit trail is
        complete from the only customer the user can still navigate to.
        """
        kept_changes = [
            {
                "field": "merged_from",
                "old_value": None,
                "new_value": {
                    "customer_id": merged.id,
                    "full_name": merged.full_name,
                    "moved_policies": moved_policy_count,
                    "moved_entities": moved_entity_count,
                },
            }
        ]
        kept.updated_at = datetime.utcnow()
        self._write(kept, source=SOURCE_MERGE, event_type="MERGED_FROM", changes=kept_changes, notes=notes)

    def record_policy_link(
        self,
        customer: Customer,
        policy_id: int,
        policy_number: str | None,
        *,
        linked: bool,
        source: str = SOURCE_POLICY_SERVICE,
        notes: str | None = None,
    ) -> None:
        payload = {"policy_id": policy_id, "policy_number": policy_number}
        if linked:
            changes = [{"field": "policy_link", "old_value": None, "new_value": payload}]
            event = "POLICY_LINKED"
        else:
            changes = [{"field": "policy_link", "old_value": payload, "new_value": None}]
            event = "POLICY_UNLINKED"
        customer.updated_at = datetime.utcnow()
        self._write(customer, source=source, event_type=event, changes=changes, notes=notes)

    def list_for_customer(
        self,
        customer_id: int,
        *,
        limit: int = 200,
        event_types: Iterable[str] | None = None,
    ) -> list[CustomerHistory]:
        q = (
            self.session.query(CustomerHistory)
            .filter(CustomerHistory.customer_id == customer_id)
            .order_by(CustomerHistory.timestamp.desc(), CustomerHistory.id.desc())
        )
        if event_types:
            q = q.filter(CustomerHistory.event_type.in_(list(event_types)))
        return q.limit(limit).all()

    # ---------------- internals ----------------

    def _next_version(self, customer_id: int) -> int:
        max_ver = (
            self.session.query(func.max(CustomerHistory.customer_version))
            .filter(CustomerHistory.customer_id == customer_id)
            .scalar()
        )
        return (max_ver or 0) + 1

    def _write(
        self,
        customer: Customer,
        *,
        source: str,
        event_type: str,
        changes: list[dict],
        notes: str | None,
    ) -> CustomerHistory:
        row = CustomerHistory(
            customer_id=customer.id,
            timestamp=datetime.utcnow(),
            source=source,
            event_type=event_type,
            customer_version=self._next_version(customer.id),
            changes=changes,
            notes=notes,
        )
        self.session.add(row)
        return row

    @staticmethod
    def _normalize(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, str):
            s = val.strip()
            return s or None
        return val


def _serialize(val: Any) -> Any:
    """JSON-safe serialization for old/new values."""
    if val is None or isinstance(val, (str, int, float, bool, dict, list)):
        return val
    return str(val)
