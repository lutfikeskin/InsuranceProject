"""
Unit tests for core/notification_service.py.

Uses the in-memory mock_db_session fixture from conftest, so the
notification_log table is created via Base.metadata.create_all() without
needing the real Alembic migration to have run.
"""

from datetime import datetime, timedelta

import pytest

# Side-effect imports so the relevant ORM tables register with Base.metadata
# before the in-memory engine in mock_db_session runs create_all().
import core.history_model  # noqa: F401
import core.notification_model  # noqa: F401
from core.notification_model import NotificationLog
from core.notification_service import KNOWN_METHODS, NotificationService


@pytest.fixture
def svc(mock_db_session):
    return NotificationService(mock_db_session)


class TestRecordContact:
    def test_writes_row_with_defaults(self, svc, mock_db_session):
        row = svc.record_contact(policy_id=42)
        mock_db_session.commit()

        assert row.id is not None  # flushed before return
        assert row.policy_id == 42
        assert row.customer_id is None
        assert row.method == "email_draft"
        assert row.notes is None
        assert isinstance(row.contacted_at, datetime)
        assert isinstance(row.created_at, datetime)

    def test_persists_method_and_notes_and_customer(self, svc, mock_db_session):
        row = svc.record_contact(
            policy_id=42,
            customer_id=7,
            method="phone",
            notes="Spoke with Joe, will call back next week.",
        )
        mock_db_session.commit()

        fetched = mock_db_session.query(NotificationLog).filter_by(id=row.id).one()
        assert fetched.customer_id == 7
        assert fetched.method == "phone"
        assert fetched.notes == "Spoke with Joe, will call back next week."

    def test_explicit_contacted_at_is_respected(self, svc, mock_db_session):
        when = datetime(2024, 1, 15, 9, 0, 0)
        row = svc.record_contact(policy_id=1, contacted_at=when)
        mock_db_session.commit()
        assert row.contacted_at == when

    def test_unknown_method_still_writes_with_warning(self, svc, mock_db_session, mocker):
        # New methods should be allowed without a code change; we just want a
        # log warning so typos don't sit silently in the DB. The service uses
        # loguru (not stdlib logging) so caplog doesn't see the message —
        # spy on logger.warning directly.
        import core.notification_service as ns_mod

        spy = mocker.spy(ns_mod.logger, "warning")
        row = svc.record_contact(policy_id=1, method="carrier_pigeon")
        mock_db_session.commit()

        assert row.method == "carrier_pigeon"
        assert spy.call_count == 1
        assert "carrier_pigeon" in spy.call_args[0][0]

    def test_does_not_commit(self, svc, mock_db_session):
        # Service must leave transaction control to the caller. Verify by
        # rolling back and confirming nothing landed.
        svc.record_contact(policy_id=99)
        mock_db_session.rollback()
        count = mock_db_session.query(NotificationLog).filter_by(policy_id=99).count()
        assert count == 0


class TestGetForPolicy:
    def test_returns_rows_most_recent_first(self, svc, mock_db_session):
        base = datetime(2024, 1, 1, 12, 0, 0)
        svc.record_contact(policy_id=10, method="phone", contacted_at=base)
        svc.record_contact(
            policy_id=10, method="email_draft", contacted_at=base + timedelta(days=2)
        )
        svc.record_contact(
            policy_id=10, method="manual", contacted_at=base + timedelta(days=1)
        )
        mock_db_session.commit()

        rows = svc.get_for_policy(10)
        assert [r.method for r in rows] == ["email_draft", "manual", "phone"]

    def test_respects_limit(self, svc, mock_db_session):
        for i in range(5):
            svc.record_contact(policy_id=20, contacted_at=datetime(2024, 1, i + 1))
        mock_db_session.commit()

        rows = svc.get_for_policy(20, limit=2)
        assert len(rows) == 2

    def test_empty_when_no_contacts(self, svc, mock_db_session):
        assert svc.get_for_policy(999) == []

    def test_filters_by_policy_id(self, svc, mock_db_session):
        svc.record_contact(policy_id=1)
        svc.record_contact(policy_id=2)
        svc.record_contact(policy_id=2)
        mock_db_session.commit()

        assert len(svc.get_for_policy(1)) == 1
        assert len(svc.get_for_policy(2)) == 2


class TestLastContact:
    def test_returns_most_recent(self, svc, mock_db_session):
        base = datetime(2024, 1, 1)
        svc.record_contact(policy_id=5, method="phone", contacted_at=base)
        svc.record_contact(
            policy_id=5, method="email_draft", contacted_at=base + timedelta(days=3)
        )
        mock_db_session.commit()

        last = svc.last_contact(5)
        assert last is not None
        assert last.method == "email_draft"

    def test_none_when_never_contacted(self, svc):
        assert svc.last_contact(404) is None


class TestHasContactSince:
    def test_true_when_recent_contact_exists(self, svc, mock_db_session):
        svc.record_contact(policy_id=7, contacted_at=datetime(2024, 6, 15))
        mock_db_session.commit()
        assert svc.has_contact_since(7, datetime(2024, 6, 1)) is True

    def test_false_when_contact_is_older_than_window(self, svc, mock_db_session):
        svc.record_contact(policy_id=7, contacted_at=datetime(2024, 1, 1))
        mock_db_session.commit()
        assert svc.has_contact_since(7, datetime(2024, 6, 1)) is False

    def test_boundary_is_inclusive(self, svc, mock_db_session):
        when = datetime(2024, 6, 1, 12, 0, 0)
        svc.record_contact(policy_id=7, contacted_at=when)
        mock_db_session.commit()
        assert svc.has_contact_since(7, when) is True

    def test_false_when_no_rows(self, svc):
        assert svc.has_contact_since(404, datetime(2024, 1, 1)) is False


class TestCountInWindow:
    def test_counts_rows_in_range(self, svc, mock_db_session):
        for day in (1, 5, 10, 15, 20):
            svc.record_contact(policy_id=1, contacted_at=datetime(2024, 6, day))
        mock_db_session.commit()

        # Window: June 1 inclusive, June 15 exclusive — should hit 3 rows (1, 5, 10).
        assert svc.count_in_window(datetime(2024, 6, 1), datetime(2024, 6, 15)) == 3

    def test_zero_when_empty(self, svc):
        assert svc.count_in_window(datetime(2024, 1, 1), datetime(2024, 12, 31)) == 0

    def test_end_is_exclusive(self, svc, mock_db_session):
        when = datetime(2024, 6, 15, 0, 0, 0)
        svc.record_contact(policy_id=1, contacted_at=when)
        mock_db_session.commit()
        # Row at exactly `end` must NOT be counted.
        assert svc.count_in_window(datetime(2024, 6, 1), when) == 0

    def test_counts_across_all_policies(self, svc, mock_db_session):
        # The Renewals KPI relies on a cross-policy aggregate count.
        # Pins the contract: count_in_window is NOT filtered by policy.
        svc.record_contact(policy_id=1, contacted_at=datetime(2024, 6, 5))
        svc.record_contact(policy_id=2, contacted_at=datetime(2024, 6, 6))
        svc.record_contact(policy_id=3, contacted_at=datetime(2024, 6, 7))
        mock_db_session.commit()
        assert (
            svc.count_in_window(datetime(2024, 6, 1), datetime(2024, 6, 30)) == 3
        )


class TestKnownMethodsConstant:
    def test_includes_documented_methods(self):
        for m in ("email_draft", "email_auto", "phone", "manual", "other"):
            assert m in KNOWN_METHODS

    def test_is_immutable(self):
        # frozenset prevents accidental mutation by code that imports the
        # constant; this guards the assumption.
        assert isinstance(KNOWN_METHODS, frozenset)
