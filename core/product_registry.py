from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductSpec:
    policy_type: str
    display_name: str
    account_type: str
    schema_scope: str
    coverage_constraint_key: str | None
    supports_vehicle_schedule: bool
    supports_driver_schedule: bool


PRODUCT_SPECS: dict[str, ProductSpec] = {
    "personal_auto": ProductSpec(
        policy_type="personal_auto",
        display_name="Personal Auto",
        account_type="Personal",
        schema_scope="personal_auto",
        coverage_constraint_key="personal_auto",
        supports_vehicle_schedule=True,
        supports_driver_schedule=True,
    ),
    "commercial_auto": ProductSpec(
        policy_type="commercial_auto",
        display_name="Commercial Auto",
        account_type="Commercial",
        schema_scope="commercial_auto",
        coverage_constraint_key="commercial_auto",
        supports_vehicle_schedule=True,
        supports_driver_schedule=True,
    ),
    "general_liability": ProductSpec(
        policy_type="general_liability",
        display_name="General Liability",
        account_type="Commercial",
        schema_scope="commercial",
        coverage_constraint_key="general_liability",
        supports_vehicle_schedule=False,
        supports_driver_schedule=False,
    ),
    "bop": ProductSpec(
        policy_type="bop",
        display_name="Businessowners Policy",
        account_type="Commercial",
        schema_scope="commercial",
        coverage_constraint_key=None,
        supports_vehicle_schedule=False,
        supports_driver_schedule=False,
    ),
    "commercial_package": ProductSpec(
        policy_type="commercial_package",
        display_name="Commercial Package",
        account_type="Commercial",
        schema_scope="commercial",
        coverage_constraint_key=None,
        supports_vehicle_schedule=True,
        supports_driver_schedule=True,
    ),
    "umbrella": ProductSpec(
        policy_type="umbrella",
        display_name="Umbrella / Excess",
        account_type="Commercial",
        schema_scope="commercial",
        coverage_constraint_key=None,
        supports_vehicle_schedule=False,
        supports_driver_schedule=False,
    ),
    "motor_truck_cargo": ProductSpec(
        policy_type="motor_truck_cargo",
        display_name="Motor Truck Cargo",
        account_type="Commercial",
        schema_scope="commercial",
        coverage_constraint_key=None,
        supports_vehicle_schedule=True,
        supports_driver_schedule=False,
    ),
    "unknown": ProductSpec(
        policy_type="unknown",
        display_name="Unknown",
        account_type="Commercial",
        schema_scope="commercial",
        coverage_constraint_key=None,
        supports_vehicle_schedule=True,
        supports_driver_schedule=True,
    ),
}

ACCOUNT_TYPE_BY_POLICY: dict[str, str] = {
    policy_type: spec.account_type for policy_type, spec in PRODUCT_SPECS.items()
}


def get_product_spec(policy_type: str | None) -> ProductSpec:
    return PRODUCT_SPECS.get(policy_type or "unknown", PRODUCT_SPECS["unknown"])


def account_type_for_policy(policy_type: str | None) -> str:
    return get_product_spec(policy_type).account_type
