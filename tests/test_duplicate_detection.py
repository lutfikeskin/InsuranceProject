import core.history_model  # noqa: F401 - registers PolicyHistory for SQLAlchemy mappers

from core.database import Policy
from core.duplicate_detection import normalize_policy_number
from core.services import PolicyService


def test_normalized_policy_number_exact_match(mock_db_session):
    mock_db_session.add(
        Policy(
            policy_number="AB-123",
            carrier_name="Progressive",
            insured_name="Alpha Trucking LLC",
        )
    )
    mock_db_session.commit()

    svc = PolicyService(mock_db_session)
    result = svc.detect_duplicate_for_extraction(
        {
            "policy": {
                "policy_number": " ab 123 ",
                "carrier_name": "Progressive",
                "insured_name": "Alpha Trucking LLC",
            }
        }
    )

    assert normalize_policy_number(" ab-123 ") == "AB123"
    assert result["status"] == "exact_policy_match"
    assert result["recommended_action"] == "update_existing"
    assert result["existing_policy"]["policy_number"] == "AB-123"


def test_same_number_different_carrier_requires_review(mock_db_session):
    mock_db_session.add(
        Policy(
            policy_number="COMM-9",
            carrier_name="Carrier A",
            insured_name="Same Insured",
        )
    )
    mock_db_session.commit()

    result = PolicyService(mock_db_session).detect_duplicate_for_extraction(
        {
            "policy": {
                "policy_number": "COMM-9",
                "carrier_name": "Carrier B",
                "insured_name": "Same Insured",
            }
        }
    )

    assert result["status"] == "exact_number_carrier_conflict"
    assert result["confidence"] == "medium"
    assert result["recommended_action"] == "review"


def test_same_insured_different_policy_number_is_possible_related(mock_db_session):
    mock_db_session.add(
        Policy(
            policy_number="OLD-1",
            carrier_name="Carrier A",
            insured_name="Alpha Trucking LLC",
        )
    )
    mock_db_session.commit()

    result = PolicyService(mock_db_session).detect_duplicate_for_extraction(
        {
            "policy": {
                "policy_number": "NEW-1",
                "carrier_name": "Carrier A",
                "insured_name": "Alpha Trucking LLC",
            }
        }
    )

    assert result["status"] == "possible_related_policy"
    assert result["existing_policy"]["policy_number"] == "OLD-1"


def test_create_new_intent_blocks_same_policy_number(mock_db_session):
    existing = Policy(
        policy_number="BLOCK-1",
        carrier_name="Carrier A",
        insured_name="Alpha Trucking LLC",
        premium="$100",
    )
    mock_db_session.add(existing)
    mock_db_session.commit()

    svc = PolicyService(mock_db_session)
    success, msg = svc.save_policy_from_extraction(
        {
            "_duplicate_action": "create_new",
            "classification": {"policy_type": "commercial_auto"},
            "policy": {
                "policy_number": "BLOCK-1",
                "carrier_name": "Carrier A",
                "insured_name": "Alpha Trucking LLC",
                "premium": "$200",
            },
            "vehicles": [],
            "drivers": [],
            "coverages": [],
            "additional_interests": [],
        }
    )

    mock_db_session.refresh(existing)
    assert success is False
    assert "Cannot create a new policy" in msg
    assert existing.premium == "$100"


def test_default_save_still_updates_existing_policy(mock_db_session):
    existing = Policy(
        policy_number="UPD-1",
        carrier_name="Carrier A",
        insured_name="Alpha Trucking LLC",
        premium="$100",
    )
    mock_db_session.add(existing)
    mock_db_session.commit()

    success, msg = PolicyService(mock_db_session).save_policy_from_extraction(
        {
            "classification": {"policy_type": "commercial_auto"},
            "policy": {
                "policy_number": "UPD-1",
                "carrier_name": "Carrier A",
                "insured_name": "Alpha Trucking LLC",
                "premium": "$200",
            },
            "vehicles": [],
            "drivers": [],
            "coverages": [],
            "additional_interests": [],
        }
    )

    mock_db_session.refresh(existing)
    assert success is True
    assert msg.startswith("Updated existing policy")
    assert existing.premium == "$200"
    assert len(existing.history) == 1
