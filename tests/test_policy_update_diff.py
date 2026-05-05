import core.history_model  # noqa: F401 - registers PolicyHistory for SQLAlchemy mappers

from core.database import Coverage, Driver, Policy, Vehicle
from core.history_model import PolicyHistory
from core.services import PolicyService


def test_update_preview_does_not_mutate_or_write_history(mock_db_session):
    policy = Policy(
        policy_number="DIFF-1",
        carrier_name="Carrier A",
        underwriter_name="Old Underwriter",
        insured_name="Alpha Trucking LLC",
        premium="$100",
        insured_city="Old City",
    )
    policy.vehicles.append(
        Vehicle(year=2020, make="Ford", model="F150", vin="VIN123", vehicle_type="Truck")
    )
    policy.drivers.append(Driver(full_name="Jane Driver", license_number="D1", is_excluded=False))
    policy.coverages.append(
        Coverage(coverage_code="AUTO_LIAB", family="auto_liability", combined_single_limit=1000000)
    )
    mock_db_session.add(policy)
    mock_db_session.commit()

    preview = PolicyService(mock_db_session).preview_update_from_extraction(
        policy,
        {
            "classification": {"policy_type": "commercial_auto"},
            "policy": {
                "policy_number": "DIFF-1",
                "carrier_name": "Carrier A",
                "underwriter_name": "New Underwriter",
                "insured_name": "Alpha Trucking LLC",
                "premium": "$200",
                "insured_city": "New City",
            },
            "vehicles": [
                {
                    "year": 2020,
                    "make": "Ford",
                    "model": "F250",
                    "vin": "VIN123",
                    "type": "Truck",
                }
            ],
            "drivers": [
                {
                    "full_name": "Jane Driver",
                    "license_number": "D1",
                    "is_excluded": True,
                }
            ],
            "coverages": [
                {
                    "coverage_code": "AUTO_LIAB",
                    "family": "auto_liability",
                    "limits": {"combined_single_limit": 2000000},
                }
            ],
            "additional_interests": [],
        },
    )

    changed_fields = {change["field"] for change in preview["changes"]}
    assert preview["is_changed"] is True
    assert {"underwriter_name", "premium", "insured_city"}.issubset(changed_fields)
    assert {"vehicles", "drivers", "coverages"}.issubset(changed_fields)
    assert preview["collection_changes"]["vehicles"] is True
    assert preview["collection_changes"]["drivers"] is True
    assert preview["collection_changes"]["coverages"] is True

    mock_db_session.refresh(policy)
    assert policy.underwriter_name == "Old Underwriter"
    assert policy.premium == "$100"
    assert policy.insured_city == "Old City"
    assert policy.vehicles[0].model == "F150"
    assert policy.drivers[0].is_excluded is False
    assert mock_db_session.query(PolicyHistory).count() == 0
