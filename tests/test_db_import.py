from datetime import date
from pathlib import Path

import pytest

from core.database import Customer, Policy, get_session, init_db
from core.db_import import DbImportError, merge_database_from_file, validate_sqlite_db


def _add_policy(session, policy_number: str, customer_name: str = "Jane Doe"):
    customer = Customer(full_name=customer_name)
    session.add(customer)
    session.flush()
    policy = Policy(
        customer_id=customer.id,
        policy_number=policy_number,
        carrier_name="Test Carrier",
        effective_date=date(2024, 1, 1),
        expiration_date=date(2025, 1, 1),
        insured_name=customer_name,
    )
    session.add(policy)
    session.commit()
    return policy


def test_validate_sqlite_db_rejects_missing_policies(tmp_path):
    bad_db = tmp_path / "bad.db"
    bad_db.write_bytes(b"not a sqlite file")
    with pytest.raises(DbImportError):
        validate_sqlite_db(bad_db)


def test_validate_sqlite_db_counts_rows(tmp_path):
    db_path = tmp_path / "source.db"
    engine = init_db(str(db_path))
    session = get_session(engine)
    try:
        _add_policy(session, "POL-001")
    finally:
        session.close()

    preview = validate_sqlite_db(db_path)
    assert preview.policy_count == 1
    assert preview.customer_count == 1


def test_merge_imports_new_policy(tmp_path):
    source_db = tmp_path / "source.db"
    target_db = tmp_path / "target.db"

    source_engine = init_db(str(source_db))
    source_session = get_session(source_engine)
    try:
        _add_policy(source_session, "SRC-100", "Import Customer")
    finally:
        source_session.close()

    target_engine = init_db(str(target_db))
    target_session = get_session(target_engine)
    try:
        assert target_session.query(Policy).count() == 0
    finally:
        target_session.close()

    result = merge_database_from_file(target_engine, source_db)
    assert result.imported_policies == 1
    assert result.skipped_duplicates == 0
    assert result.imported_customers == 1

    target_session = get_session(target_engine)
    try:
        imported = (
            target_session.query(Policy)
            .filter(Policy.policy_number == "SRC-100")
            .one()
        )
        assert imported.insured_name == "Import Customer"
        assert imported.customer is not None
        assert imported.customer.full_name == "Import Customer"
    finally:
        target_session.close()


def test_merge_skips_duplicate_policy_number(tmp_path):
    source_db = tmp_path / "source.db"
    target_db = tmp_path / "target.db"

    source_engine = init_db(str(source_db))
    source_session = get_session(source_engine)
    try:
        _add_policy(source_session, "DUP-001", "Source Customer")
    finally:
        source_session.close()

    target_engine = init_db(str(target_db))
    target_session = get_session(target_engine)
    try:
        _add_policy(target_session, "DUP-001", "Existing Customer")
    finally:
        target_session.close()

    result = merge_database_from_file(target_engine, source_db)
    assert result.imported_policies == 0
    assert result.skipped_duplicates == 1

    target_session = get_session(target_engine)
    try:
        assert target_session.query(Policy).count() == 1
    finally:
        target_session.close()
