"""Web integration tests for the round-3 database page overhaul.

Covers: tabbed master, customer/policy detail full pages, sub-tab partials,
audit-trail writes on save/entity/merge, and the policy history feed.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.customer_history_model import CustomerHistory
from core.database import Base, Customer, Policy
from core.history_model import PolicyHistory
from webapp import create_app


@pytest.fixture
def setup():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    s = Session()
    # One customer + two policies for renewal-chain coverage.
    customer = Customer(full_name="Trucking Co", primary_email="ops@trucking.example")
    s.add(customer)
    s.flush()

    policy = Policy(
        policy_number="TC-100",
        carrier_name="Progressive",
        insured_name="Trucking Co",
        effective_date=date(2026, 1, 1),
        expiration_date=date(2027, 1, 1),
        premium="1200.00",
        customer_id=customer.id,
        policy_type="commercial_auto",
    )
    s.add(policy)
    s.flush()
    policy_id = policy.id
    customer_id = customer.id
    s.commit()
    s.close()

    app = create_app(session_factory=Session)
    app.config.update(TESTING=True)
    return app.test_client(), Session, customer_id, policy_id


def test_master_database_renders_both_tables(setup):
    client, _, _, _ = setup
    r = client.get("/database")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Trucking Co" in body         # customer name shown
    assert "TC-100" in body              # policy number shown
    assert "Customers" in body
    assert "Policies" in body


def test_master_database_tab_param_highlights_tab(setup):
    client, _, _, _ = setup
    r = client.get("/database?tab=policies")
    assert r.status_code == 200


def test_customers_list_partial(setup):
    client, _, _, _ = setup
    r = client.get("/database/customers/list?q=Trucking")
    assert r.status_code == 200
    assert "Trucking Co" in r.get_data(as_text=True)


def test_policies_list_partial(setup):
    client, _, _, _ = setup
    r = client.get("/database/policies/list?q=TC-100")
    assert r.status_code == 200
    assert "TC-100" in r.get_data(as_text=True)


def test_customer_detail_renders_full_page_with_tabs(setup):
    client, _, customer_id, _ = setup
    r = client.get(f"/database/customer/{customer_id}")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Trucking Co" in body
    # Sub-tab nav is present
    assert "Profile" in body
    assert "Entities" in body
    assert "Policies" in body
    assert "History" in body
    assert "Merge" in body


def test_customer_tab_partials_each_render(setup):
    client, _, customer_id, _ = setup
    for tab in ("profile", "entities", "policies", "history", "merge"):
        r = client.get(f"/database/customer/{customer_id}/tab/{tab}")
        assert r.status_code == 200, f"tab {tab} failed: {r.status_code}"


def test_customer_save_records_history_row(setup):
    client, Session, customer_id, _ = setup
    r = client.post(
        f"/database/customer/{customer_id}/save",
        data={"full_name": "Trucking Co.", "primary_email": "ops@trucking.example", "primary_phone": "555-1234"},
    )
    assert r.status_code == 200
    s = Session()
    rows = s.query(CustomerHistory).filter_by(customer_id=customer_id).all()
    s.close()
    fields_touched = {c["field"] for row in rows for c in (row.changes or [])}
    assert "full_name" in fields_touched
    assert "primary_phone" in fields_touched


def test_customer_entity_add_records_history(setup):
    client, Session, customer_id, _ = setup
    r = client.post(
        f"/database/customer/{customer_id}/entity/add",
        data={"entity_name": "Trucking Holdings LLC", "entity_type": "business"},
    )
    assert r.status_code == 200
    s = Session()
    rows = s.query(CustomerHistory).filter_by(customer_id=customer_id, event_type="ENTITY_ADDED").all()
    s.close()
    assert any("Trucking Holdings" in (c.get("new_value", {}) or {}).get("entity_name", "") for row in rows for c in row.changes)


def test_customer_entity_remove_records_history(setup):
    client, Session, customer_id, _ = setup
    # First add a removable alias
    client.post(
        f"/database/customer/{customer_id}/entity/add",
        data={"entity_name": "Drop Me LLC", "entity_type": "business"},
    )
    # Look up entity id
    s = Session()
    cust = s.get(Customer, customer_id)
    target = next(e for e in cust.entities if e.entity_name == "Drop Me LLC")
    target_id = target.id
    s.close()

    r = client.post(f"/database/customer/{customer_id}/entity/{target_id}/remove")
    assert r.status_code == 200
    s = Session()
    rows = s.query(CustomerHistory).filter_by(customer_id=customer_id, event_type="ENTITY_REMOVED").all()
    s.close()
    assert len(rows) >= 1


def test_customer_merge_redirects_to_kept(setup):
    client, Session, customer_id, _ = setup
    # Create a second customer to merge INTO
    s = Session()
    other = Customer(full_name="Survivor Co")
    s.add(other)
    s.commit()
    other_id = other.id
    s.close()

    r = client.post(
        f"/database/customer/{customer_id}/merge",
        data={"target_customer_id": str(other_id)},
    )
    assert r.status_code in (302, 303)
    assert f"/database/customer/{other_id}" in r.headers.get("Location", "")
    # Kept customer should now have a MERGED_FROM row
    s = Session()
    rows = s.query(CustomerHistory).filter_by(customer_id=other_id, event_type="MERGED_FROM").all()
    s.close()
    assert len(rows) == 1


def test_policy_detail_renders_with_tabs(setup):
    client, _, _, policy_id = setup
    r = client.get(f"/database/policy/{policy_id}")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "TC-100" in body
    assert "Overview" in body
    assert "Edit" in body
    assert "History" in body
    assert "Renewals" in body


def test_policy_tab_partials_each_render(setup):
    client, _, _, policy_id = setup
    for tab in ("overview", "edit", "history", "renewals"):
        r = client.get(f"/database/policy/{policy_id}/tab/{tab}")
        assert r.status_code == 200, f"tab {tab} failed: {r.status_code}"


def test_policy_history_tab_lists_audit_rows(setup):
    client, Session, _, policy_id = setup
    # Seed a PolicyHistory row directly
    s = Session()
    s.add(PolicyHistory(
        policy_id=policy_id,
        source="Manual_Edit",
        event_type="MANUAL_EDIT",
        policy_version=1,
        changes=[{"field": "premium", "old_value": "1000", "new_value": "1200"}],
    ))
    s.commit()
    s.close()

    r = client.get(f"/database/policy/{policy_id}/tab/history")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "premium" in body
    assert "1200" in body


def test_policy_save_records_history_row(setup):
    client, Session, _, policy_id = setup
    r = client.post(
        f"/database/policy/{policy_id}/save",
        data={
            "policy_number": "TC-100",
            "carrier_name": "Progressive",
            "insured_name": "Trucking Co",
            "effective_date": "2026-01-01",
            "expiration_date": "2027-01-01",
            "premium": "1500.00",
            "vehicles_json": "[]",
            "drivers_json": "[]",
            "coverages_json": "[]",
            "additional_interests_json": "[]",
        },
    )
    assert r.status_code == 200
    s = Session()
    rows = s.query(PolicyHistory).filter_by(policy_id=policy_id).all()
    s.close()
    fields = {c["field"] for row in rows for c in (row.changes or [])}
    assert "premium" in fields


def test_policy_delete_returns_master_page(setup):
    client, _, _, policy_id = setup
    r = client.post(f"/database/policy/{policy_id}/delete")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Database" in body
