import core.history_model  # noqa: F401 - registers PolicyHistory for SQLAlchemy mappers

from core.database import Customer, CustomerEntity, Policy
from core.services import PolicyService


def _customer_with_entity(mock_db_session, name="Owner", source="extraction"):
    customer = Customer(full_name=name)
    mock_db_session.add(customer)
    mock_db_session.flush()
    mock_db_session.add(
        CustomerEntity(
            customer_id=customer.id,
            entity_name=name,
            entity_type="personal",
            is_primary=True,
            source=source,
        )
    )
    return customer


def _policy(mock_db_session, customer, number):
    policy = Policy(
        customer_id=customer.id,
        policy_number=number,
        insured_name=customer.full_name,
        carrier_name="Test Carrier",
    )
    mock_db_session.add(policy)
    return policy


def test_customer_search_excludes_orphans_by_default(mock_db_session):
    svc = PolicyService(mock_db_session)
    active = _customer_with_entity(mock_db_session, "Active Owner")
    orphan = _customer_with_entity(mock_db_session, "Orphan Owner")
    _policy(mock_db_session, active, "ACTIVE-1")
    mock_db_session.commit()

    active_rows = svc.search_customers(None)
    orphan_rows = svc.search_customers(None, orphan_filter="orphans")
    all_rows = svc.search_customers(None, orphan_filter="all")

    assert [c.full_name for c in active_rows] == ["Active Owner"]
    assert [c.full_name for c in orphan_rows] == ["Orphan Owner"]
    assert {c.full_name for c in all_rows} == {active.full_name, orphan.full_name}


def test_delete_last_policy_removes_extraction_only_customer(mock_db_session):
    svc = PolicyService(mock_db_session)
    customer = _customer_with_entity(mock_db_session, "Extraction Owner")
    policy = _policy(mock_db_session, customer, "DEL-1")
    mock_db_session.commit()

    result = svc.delete_policy(policy)

    assert result["customer_cleanup"]["deleted"] is True
    assert mock_db_session.query(Policy).count() == 0
    assert mock_db_session.query(Customer).count() == 0
    assert mock_db_session.query(CustomerEntity).count() == 0


def test_delete_one_of_multiple_policies_keeps_customer(mock_db_session):
    svc = PolicyService(mock_db_session)
    customer = _customer_with_entity(mock_db_session, "Multi Policy Owner")
    policy_one = _policy(mock_db_session, customer, "MULTI-1")
    _policy(mock_db_session, customer, "MULTI-2")
    mock_db_session.commit()

    result = svc.delete_policy(policy_one)

    assert result["customer_cleanup"]["deleted"] is False
    assert result["customer_cleanup"]["reason"] == "has_policies"
    assert mock_db_session.query(Customer).count() == 1
    assert mock_db_session.query(Policy).count() == 1


def test_delete_last_policy_retains_customer_with_manual_data(mock_db_session):
    svc = PolicyService(mock_db_session)
    customer = _customer_with_entity(mock_db_session, "Manual Owner", source="manual")
    policy = _policy(mock_db_session, customer, "KEEP-1")
    mock_db_session.commit()

    result = svc.delete_policy(policy)

    assert result["customer_cleanup"]["deleted"] is False
    assert result["customer_cleanup"]["reason"] == "manual_or_contact_data"
    assert mock_db_session.query(Policy).count() == 0
    assert mock_db_session.query(Customer).count() == 1
