"""
Tests for PolicyService.find_related_policy.

Verifies the helper used by the Compare page's Auto-pair button:
- Finds a related policy regardless of which side of the relationship
  the given policy_id sits on (policy_id or related_policy_id column).
- Respects the confirmed_only filter so suggested relationships don't
  auto-pair.
- Returns None when nothing matches.
- Picks the most recently created relationship when multiple qualify.
"""

from datetime import datetime, timedelta

import pytest

# Side-effect imports so create_all() builds every related table.
import core.history_model  # noqa: F401
import core.notification_model  # noqa: F401
from core.database import Policy, PolicyRelationship
from core.services import PolicyService


@pytest.fixture
def svc(mock_db_session):
    return PolicyService(mock_db_session)


def _insert_policy(session, number: str) -> Policy:
    p = Policy(policy_number=number)
    session.add(p)
    session.flush()
    return p


def _insert_relationship(
    session,
    primary: Policy,
    related: Policy,
    *,
    confidence: str = "confirmed",
    relationship_type: str = "renewal",
    created_at: datetime = None,
):
    rel = PolicyRelationship(
        policy_id=primary.id,
        related_policy_id=related.id,
        relationship_type=relationship_type,
        confidence=confidence,
        created_at=created_at or datetime.utcnow(),
    )
    session.add(rel)
    session.flush()
    return rel


class TestFindRelatedPolicy:
    def test_returns_related_when_target_is_primary_side(self, svc, mock_db_session):
        a = _insert_policy(mock_db_session, "A")
        b = _insert_policy(mock_db_session, "B")
        _insert_relationship(mock_db_session, primary=a, related=b)
        mock_db_session.commit()

        result = svc.find_related_policy(a.id)
        assert result is not None
        assert result.id == b.id

    def test_returns_other_side_when_target_is_related_side(self, svc, mock_db_session):
        # Same relationship as above but query from the *other* end. The
        # method must still return A.
        a = _insert_policy(mock_db_session, "A")
        b = _insert_policy(mock_db_session, "B")
        _insert_relationship(mock_db_session, primary=a, related=b)
        mock_db_session.commit()

        result = svc.find_related_policy(b.id)
        assert result is not None
        assert result.id == a.id

    def test_returns_none_when_no_relationship(self, svc, mock_db_session):
        p = _insert_policy(mock_db_session, "LONELY")
        mock_db_session.commit()
        assert svc.find_related_policy(p.id) is None

    def test_excludes_suggested_when_confirmed_only(self, svc, mock_db_session):
        a = _insert_policy(mock_db_session, "A")
        b = _insert_policy(mock_db_session, "B")
        _insert_relationship(mock_db_session, primary=a, related=b, confidence="suggested")
        mock_db_session.commit()

        # Default behavior (confirmed_only=True) skips the suggested row.
        assert svc.find_related_policy(a.id) is None

    def test_includes_suggested_when_caller_opts_in(self, svc, mock_db_session):
        a = _insert_policy(mock_db_session, "A")
        b = _insert_policy(mock_db_session, "B")
        _insert_relationship(mock_db_session, primary=a, related=b, confidence="suggested")
        mock_db_session.commit()

        result = svc.find_related_policy(a.id, confirmed_only=False)
        assert result is not None
        assert result.id == b.id

    def test_returns_most_recent_when_multiple_relationships(self, svc, mock_db_session):
        a = _insert_policy(mock_db_session, "A")
        b_old = _insert_policy(mock_db_session, "B_OLD")
        b_new = _insert_policy(mock_db_session, "B_NEW")
        now = datetime.utcnow()
        _insert_relationship(
            mock_db_session, primary=a, related=b_old, created_at=now - timedelta(days=10)
        )
        _insert_relationship(
            mock_db_session, primary=a, related=b_new, created_at=now,
        )
        mock_db_session.commit()

        result = svc.find_related_policy(a.id)
        assert result is not None
        # The fresher relationship (b_new) wins.
        assert result.id == b_new.id

    def test_returns_none_for_unknown_policy_id(self, svc):
        assert svc.find_related_policy(99999) is None
