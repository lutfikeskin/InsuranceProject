"""
Tests for PolicyService.get_renewal_buckets().

Integration-style: spin up the in-memory SQLite from conftest, insert a
handful of Policy rows with known expiration_dates relative to today, then
assert which bucket each lands in.
"""

from datetime import date, timedelta

import pytest

# Side-effect imports — register PolicyHistory + NotificationLog so the
# in-memory create_all() in conftest builds every related table.
import core.history_model  # noqa: F401
import core.notification_model  # noqa: F401
from core.database import Policy
from core.services import PolicyService


def _insert(session, policy_number: str, days_offset: int) -> Policy:
    """Insert a Policy whose expiration is `days_offset` from today.

    Only policy_number and expiration_date are required by the schema; we
    skip the rest so the test fixture stays small."""
    p = Policy(
        policy_number=policy_number,
        expiration_date=date.today() + timedelta(days=days_offset),
    )
    session.add(p)
    session.flush()
    return p


@pytest.fixture
def svc(mock_db_session):
    return PolicyService(mock_db_session)


class TestBucketPlacement:
    def test_overdue_bucket(self, svc, mock_db_session):
        p = _insert(mock_db_session, "OVERDUE-1", -5)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        assert p in result["overdue"]
        assert result["urgent"] == []
        assert result["warning"] == []
        assert result["watch"] == []

    def test_urgent_bucket_lower_boundary(self, svc, mock_db_session):
        # 0 days left → expires today → "urgent" (inclusive of 0).
        p = _insert(mock_db_session, "URG-0", 0)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        assert p in result["urgent"]

    def test_urgent_bucket_upper_boundary(self, svc, mock_db_session):
        p = _insert(mock_db_session, "URG-14", 14)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        assert p in result["urgent"]

    def test_warning_bucket_lower_boundary(self, svc, mock_db_session):
        p = _insert(mock_db_session, "WARN-15", 15)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        assert p in result["warning"]

    def test_warning_bucket_upper_boundary(self, svc, mock_db_session):
        p = _insert(mock_db_session, "WARN-30", 30)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        assert p in result["warning"]

    def test_watch_bucket_lower_boundary(self, svc, mock_db_session):
        p = _insert(mock_db_session, "WATCH-31", 31)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        assert p in result["watch"]

    def test_watch_bucket_upper_boundary(self, svc, mock_db_session):
        p = _insert(mock_db_session, "WATCH-60", 60)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        assert p in result["watch"]


class TestExclusions:
    def test_too_far_in_future_excluded(self, svc, mock_db_session):
        # 61 days out — outside the 60-day window, should not appear anywhere.
        p = _insert(mock_db_session, "FAR", 61)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        for bucket in result.values():
            assert p not in bucket

    def test_too_long_overdue_excluded(self, svc, mock_db_session):
        # Default overdue_lookback_days is 30, so a policy 31 days overdue
        # is outside the window.
        p = _insert(mock_db_session, "ANCIENT", -31)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        for bucket in result.values():
            assert p not in bucket

    def test_null_expiration_excluded(self, svc, mock_db_session):
        # A policy with no expiration_date should never appear.
        p = Policy(policy_number="NULL-EXP", expiration_date=None)
        mock_db_session.add(p)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        for bucket in result.values():
            assert p not in bucket


class TestOrdering:
    def test_within_bucket_sorted_ascending_by_expiration(self, svc, mock_db_session):
        # Insert in reverse-chronological order; expect ascending output.
        p_later = _insert(mock_db_session, "URG-10", 10)
        p_earlier = _insert(mock_db_session, "URG-2", 2)
        mock_db_session.commit()

        result = svc.get_renewal_buckets()
        idx_earlier = result["urgent"].index(p_earlier)
        idx_later = result["urgent"].index(p_later)
        assert idx_earlier < idx_later


class TestOverdueLookbackKnob:
    def test_custom_lookback_widens_overdue_window(self, svc, mock_db_session):
        # 60 days overdue — outside the default 30-day window, but inside 90.
        p = _insert(mock_db_session, "OLD", -60)
        mock_db_session.commit()

        default = svc.get_renewal_buckets()
        wide = svc.get_renewal_buckets(overdue_lookback_days=90)

        assert p not in default["overdue"]
        assert p in wide["overdue"]


class TestEmptyDatabase:
    def test_returns_all_empty_buckets_when_no_policies(self, svc):
        result = svc.get_renewal_buckets()
        assert result == {
            "overdue": [],
            "urgent": [],
            "warning": [],
            "watch": [],
        }

    def test_returns_all_four_keys_even_when_some_empty(self, svc, mock_db_session):
        # Insert only an urgent policy; the other three keys must still exist.
        _insert(mock_db_session, "URG", 7)
        mock_db_session.commit()
        result = svc.get_renewal_buckets()
        assert set(result.keys()) == {"overdue", "urgent", "warning", "watch"}
