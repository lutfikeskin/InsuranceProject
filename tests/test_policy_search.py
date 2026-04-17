import pytest

import core.history_model  # noqa: F401 — registers PolicyHistory for SQLAlchemy mappers

from core.database import Policy
from core.services import PolicyService


def test_search_policies_empty_term_returns_recent(mock_db_session):
    svc = PolicyService(mock_db_session)
    mock_db_session.add(
        Policy(
            policy_number="P-1",
            insured_name="Alpha Trucking",
            carrier_name="C1",
        )
    )
    mock_db_session.add(
        Policy(
            policy_number="P-2",
            insured_name="Beta Logistics",
            carrier_name="C2",
        )
    )
    mock_db_session.commit()

    rows = svc.search_policies(None, limit=10)
    assert len(rows) == 2
    assert rows[0].policy_number == "P-2"


def test_search_policies_filter_by_insured(mock_db_session):
    svc = PolicyService(mock_db_session)
    mock_db_session.add(
        Policy(policy_number="A-1", insured_name="UniqueNameXYZ", carrier_name="X")
    )
    mock_db_session.add(
        Policy(policy_number="B-1", insured_name="Other", carrier_name="Y"),
    )
    mock_db_session.commit()

    rows = svc.search_policies("UniqueName", limit=10)
    assert len(rows) == 1
    assert rows[0].policy_number == "A-1"


def test_create_policy_from_dict_links_coverage_vehicle_vin(mock_db_session):
    svc = PolicyService(mock_db_session)
    data = {
        "policy_number": "COV-1",
        "insured_name": "Test",
        "effective_date": "2024-01-01",
        "expiration_date": "2025-01-01",
        "vehicles": [
            {
                "year": 2020,
                "make": "Freightliner",
                "model": "Cascadia",
                "vin": "1XP5DB9X7LN123456",
                "type": "Tractor",
            }
        ],
        "coverages": [
            {
                "coverage_code": "COMP",
                "family": "physical_damage",
                "limit_structure": "deductible_only",
                "limits": {},
                "deductible": 500,
                "vehicle_vin": "1xp5db9x7ln123456",
            }
        ],
        "drivers": [],
        "additional_interests": [],
    }
    pol = svc.create_policy_from_dict(data)
    assert len(pol.vehicles) == 1
    assert len(pol.coverages) == 1
    assert pol.coverages[0].vehicle is not None
    assert pol.coverages[0].vehicle.vin == "1XP5DB9X7LN123456"
