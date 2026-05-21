from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.customer_history_model import CustomerHistory
from core.customer_history_service import (
    SOURCE_MANUAL,
    SOURCE_RESOLVER,
    CustomerHistoryService,
)
from core.customer_resolver import CustomerResolver
from core.database import Base, Customer, CustomerEntity


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def customer(session):
    c = Customer(full_name="Sally Smith")
    session.add(c)
    session.flush()
    return c


class TestRecordFieldChanges:
    def test_records_only_changed_fields(self, session, customer):
        svc = CustomerHistoryService(session)
        changes = svc.record_field_changes(
            customer,
            {"full_name": "Sally Smith-Jones", "primary_email": "sally@example.com"},
            source=SOURCE_MANUAL,
        )
        session.flush()
        assert {c["field"] for c in changes} == {"full_name", "primary_email"}
        rows = session.query(CustomerHistory).filter_by(customer_id=customer.id).all()
        assert len(rows) == 1
        assert rows[0].event_type == "UPDATED"
        assert rows[0].source == SOURCE_MANUAL
        assert rows[0].customer_version == 1

    def test_no_history_when_nothing_changed(self, session, customer):
        svc = CustomerHistoryService(session)
        changes = svc.record_field_changes(
            customer,
            {"full_name": "Sally Smith"},  # same as existing
            source=SOURCE_MANUAL,
        )
        session.flush()
        assert changes == []
        assert session.query(CustomerHistory).count() == 0

    def test_mutates_customer_in_place(self, session, customer):
        svc = CustomerHistoryService(session)
        svc.record_field_changes(
            customer,
            {"primary_phone": "555-1212"},
            source=SOURCE_MANUAL,
        )
        assert customer.primary_phone == "555-1212"
        assert customer.updated_at is not None

    def test_version_increments(self, session, customer):
        svc = CustomerHistoryService(session)
        svc.record_field_changes(customer, {"primary_email": "a@x.com"}, source=SOURCE_MANUAL)
        session.flush()
        svc.record_field_changes(customer, {"primary_email": "b@x.com"}, source=SOURCE_MANUAL)
        session.flush()
        rows = (
            session.query(CustomerHistory)
            .filter_by(customer_id=customer.id)
            .order_by(CustomerHistory.customer_version)
            .all()
        )
        assert [r.customer_version for r in rows] == [1, 2]


class TestRecordEntityAdded:
    def test_writes_entity_added_row(self, session, customer):
        entity = CustomerEntity(
            customer_id=customer.id,
            entity_name="ACME Trucking LLC",
            entity_type="business",
            is_primary=False,
            source="manual",
        )
        session.add(entity)
        session.flush()
        CustomerHistoryService(session).record_entity_added(customer, entity, source=SOURCE_MANUAL)
        session.flush()
        rows = session.query(CustomerHistory).filter_by(customer_id=customer.id).all()
        assert len(rows) == 1
        assert rows[0].event_type == "ENTITY_ADDED"
        assert rows[0].changes[0]["new_value"]["entity_name"] == "ACME Trucking LLC"


class TestRecordEntityRemoved:
    def test_writes_entity_removed_row(self, session, customer):
        entity = CustomerEntity(
            customer_id=customer.id,
            entity_name="Old Alias",
            entity_type="dba",
            is_primary=False,
            source="manual",
        )
        session.add(entity)
        session.flush()
        CustomerHistoryService(session).record_entity_removed(customer, entity, source=SOURCE_MANUAL)
        session.flush()
        rows = session.query(CustomerHistory).filter_by(customer_id=customer.id).all()
        assert len(rows) == 1
        assert rows[0].event_type == "ENTITY_REMOVED"
        assert rows[0].changes[0]["old_value"]["entity_name"] == "Old Alias"


class TestRecordMerge:
    def test_logs_only_on_kept_customer(self, session, customer):
        merged = Customer(full_name="Bob Other")
        session.add(merged)
        session.flush()
        CustomerHistoryService(session).record_merge(
            customer,
            merged,
            moved_policy_count=3,
            moved_entity_count=2,
        )
        session.flush()
        kept_rows = session.query(CustomerHistory).filter_by(customer_id=customer.id).all()
        merged_rows = session.query(CustomerHistory).filter_by(customer_id=merged.id).all()
        # Kept side: one MERGED_FROM row
        assert len(kept_rows) == 1
        assert kept_rows[0].event_type == "MERGED_FROM"
        assert kept_rows[0].changes[0]["new_value"]["customer_id"] == merged.id
        assert kept_rows[0].changes[0]["new_value"]["moved_policies"] == 3
        # Merged side: nothing (would be cascaded on delete anyway)
        assert merged_rows == []


class TestListForCustomer:
    def test_returns_newest_first(self, session, customer):
        svc = CustomerHistoryService(session)
        svc.record_field_changes(customer, {"primary_email": "a@x.com"}, source=SOURCE_MANUAL)
        session.flush()
        svc.record_field_changes(customer, {"primary_email": "b@x.com"}, source=SOURCE_MANUAL)
        session.flush()
        rows = svc.list_for_customer(customer.id)
        assert len(rows) == 2
        assert rows[0].customer_version > rows[1].customer_version

    def test_event_type_filter(self, session, customer):
        svc = CustomerHistoryService(session)
        svc.record_field_changes(customer, {"primary_email": "a@x.com"}, source=SOURCE_MANUAL)
        session.flush()
        entity = CustomerEntity(
            customer_id=customer.id,
            entity_name="Filtered Alias",
            entity_type="business",
            is_primary=False,
            source="manual",
        )
        session.add(entity)
        session.flush()
        svc.record_entity_added(customer, entity, source=SOURCE_MANUAL)
        session.flush()
        all_rows = svc.list_for_customer(customer.id)
        only_entity = svc.list_for_customer(customer.id, event_types=["ENTITY_ADDED"])
        assert len(all_rows) == 2
        assert len(only_entity) == 1
        assert only_entity[0].event_type == "ENTITY_ADDED"


class TestResolverIntegration:
    def test_create_customer_writes_created_and_entity_rows(self, session):
        resolver = CustomerResolver(session)
        customer = resolver.create_customer("Jane Q. Public", entity_name="Jane's Diner LLC", entity_type="business")
        session.flush()
        rows = (
            session.query(CustomerHistory)
            .filter_by(customer_id=customer.id)
            .order_by(CustomerHistory.customer_version)
            .all()
        )
        types = [r.event_type for r in rows]
        assert types[0] == "CREATED"
        assert "ENTITY_ADDED" in types
        # All rows should originate from the resolver
        assert all(r.source == SOURCE_RESOLVER for r in rows)

    def test_add_entity_writes_history(self, session):
        resolver = CustomerResolver(session)
        customer = resolver.create_customer("Mike Manual")
        session.flush()
        resolver.add_entity(customer, "MMM Holdings", "business", source="Manual_Edit")
        session.flush()
        rows = svc_rows_for(session, customer.id, "ENTITY_ADDED")
        # Two ENTITY_ADDED rows: one from create (primary self), one from the manual add
        assert len(rows) >= 2
        manual_row = [r for r in rows if r.source == SOURCE_MANUAL][0]
        assert manual_row.changes[0]["new_value"]["entity_name"] == "MMM Holdings"

    def test_merge_customers_writes_kept_history(self, session):
        resolver = CustomerResolver(session)
        kept = resolver.create_customer("Kept Co")
        merged = resolver.create_customer("Going Co")
        session.flush()
        result = resolver.merge_customers(keep_id=kept.id, merge_id=merged.id)
        assert result["success"] is True
        assert result["kept_customer_id"] == kept.id
        kept_history = svc_rows_for(session, kept.id, "MERGED_FROM")
        assert len(kept_history) == 1

    def test_merge_rejects_self(self, session):
        resolver = CustomerResolver(session)
        c = resolver.create_customer("Same Co")
        session.flush()
        result = resolver.merge_customers(keep_id=c.id, merge_id=c.id)
        assert result["success"] is False


# -----------------------
# helpers
# -----------------------
def svc_rows_for(session, customer_id, event_type):
    return (
        session.query(CustomerHistory)
        .filter_by(customer_id=customer_id, event_type=event_type)
        .order_by(CustomerHistory.id)
        .all()
    )
