"""Merge policies from an uploaded SQLite insurance_data.db into the live database."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, joinedload, selectinload, sessionmaker

from core import history_model  # noqa: F401 — register PolicyHistory
from core.database import (
    AdditionalInterest,
    Coverage,
    Customer,
    CustomerEntity,
    Driver,
    Policy,
    PolicyEndorsement,
    PolicyRelationship,
    Vehicle,
    init_db,
)

PolicyHistory = history_model.PolicyHistory


class DbImportError(ValueError):
    """Raised when an uploaded file is not a valid import database."""


@dataclass
class DbImportPreview:
    policy_count: int
    customer_count: int


@dataclass
class MergeResult:
    imported_policies: int = 0
    skipped_duplicates: int = 0
    imported_customers: int = 0
    imported_relationships: int = 0
    errors: list[str] = field(default_factory=list)


def _normalize_policy_number(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _model_values(instance, *, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    mapper = inspect(instance.__class__)
    values = {}
    for col in mapper.columns:
        if col.name in exclude:
            continue
        values[col.key] = getattr(instance, col.key)
    return values


def validate_sqlite_db(path: str | Path) -> DbImportPreview:
    """Verify the file is SQLite with expected tables; return row counts."""
    db_path = Path(path)
    if not db_path.is_file():
        raise DbImportError("Upload is not a valid database file.")

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise DbImportError(f"Could not open database file: {exc}") from exc

    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "policies" not in tables:
            raise DbImportError("Database is missing the policies table.")

        policy_count = conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
        customer_count = 0
        if "customers" in tables:
            customer_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    except sqlite3.Error as exc:
        raise DbImportError(f"Invalid SQLite database: {exc}") from exc
    finally:
        conn.close()

    return DbImportPreview(policy_count=policy_count, customer_count=customer_count)


def _resolve_target_customer(
    target_session: Session,
    customers_by_name: dict[str, Customer],
    source_customer: Customer | None,
    imported_customers: int,
) -> tuple[int | None, int]:
    if source_customer is None:
        return None, imported_customers

    name_key = (source_customer.full_name or "").strip().casefold()
    if not name_key:
        return None, imported_customers

    existing = customers_by_name.get(name_key)
    if existing:
        return existing.id, imported_customers

    new_customer = Customer(**_model_values(source_customer, exclude={"id"}))
    target_session.add(new_customer)
    target_session.flush()

    for entity in source_customer.entities or []:
        target_session.add(
            CustomerEntity(
                **_model_values(entity, exclude={"id", "customer_id"}),
                customer_id=new_customer.id,
            )
        )

    customers_by_name[name_key] = new_customer
    return new_customer.id, imported_customers + 1


def merge_database_from_file(target_engine, source_path: str | Path) -> MergeResult:
    """Merge policies from source SQLite file into the target engine database."""
    source_path = Path(source_path)
    validate_sqlite_db(source_path)

    result = MergeResult()
    source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")

    TargetSession = sessionmaker(bind=target_engine)
    SourceSession = sessionmaker(bind=source_engine)

    target_session = TargetSession()
    source_session = SourceSession()

    pending_relationships: list[dict] = []
    pending_replaced_by: list[tuple[int, int | None]] = []

    try:
        existing_numbers: set[str] = set()
        for (num,) in target_session.query(Policy.policy_number).all():
            normalized = _normalize_policy_number(num)
            if normalized:
                existing_numbers.add(normalized)

        target_policy_by_number: dict[str, int] = {}
        for pol_id, num in target_session.query(Policy.id, Policy.policy_number).all():
            normalized = _normalize_policy_number(num)
            if normalized:
                target_policy_by_number[normalized] = pol_id

        customers_by_name: dict[str, Customer] = {
            (c.full_name or "").strip().casefold(): c
            for c in target_session.query(Customer).all()
            if (c.full_name or "").strip()
        }

        policy_id_map: dict[int, int] = {}

        source_policies = (
            source_session.query(Policy)
            .options(
                joinedload(Policy.customer).joinedload(Customer.entities),
                selectinload(Policy.vehicles),
                selectinload(Policy.drivers),
                selectinload(Policy.coverages),
                selectinload(Policy.additional_interests),
                selectinload(Policy.endorsements),
                selectinload(Policy.history),
                selectinload(Policy.policy_relationships),
            )
            .all()
        )

        for src_policy in source_policies:
            policy_number = _normalize_policy_number(src_policy.policy_number)
            if not policy_number:
                result.errors.append("Skipped policy with empty policy_number.")
                continue
            if policy_number in existing_numbers:
                result.skipped_duplicates += 1
                continue

            target_customer_id, result.imported_customers = _resolve_target_customer(
                target_session,
                customers_by_name,
                src_policy.customer,
                result.imported_customers,
            )

            policy_data = _model_values(
                src_policy,
                exclude={"id", "customer_id", "replaced_by_policy_id"},
            )
            policy_data["policy_number"] = policy_number
            policy_data["customer_id"] = target_customer_id
            policy_data["replaced_by_policy_id"] = None

            new_policy = Policy(**policy_data)
            target_session.add(new_policy)
            target_session.flush()

            policy_id_map[src_policy.id] = new_policy.id
            target_policy_by_number[policy_number] = new_policy.id
            existing_numbers.add(policy_number)
            result.imported_policies += 1

            vehicle_id_map: dict[int, int] = {}
            for vehicle in src_policy.vehicles or []:
                new_vehicle = Vehicle(
                    **_model_values(vehicle, exclude={"id", "policy_id"}),
                    policy_id=new_policy.id,
                )
                target_session.add(new_vehicle)
                target_session.flush()
                vehicle_id_map[vehicle.id] = new_vehicle.id

            for driver in src_policy.drivers or []:
                target_session.add(
                    Driver(
                        **_model_values(driver, exclude={"id", "policy_id"}),
                        policy_id=new_policy.id,
                    )
                )

            for interest in src_policy.additional_interests or []:
                target_session.add(
                    AdditionalInterest(
                        **_model_values(interest, exclude={"id", "policy_id"}),
                        policy_id=new_policy.id,
                    )
                )

            for endorsement in src_policy.endorsements or []:
                target_session.add(
                    PolicyEndorsement(
                        **_model_values(endorsement, exclude={"id", "parent_policy_id"}),
                        parent_policy_id=new_policy.id,
                    )
                )

            for hist in src_policy.history or []:
                target_session.add(
                    PolicyHistory(
                        **_model_values(hist, exclude={"id", "policy_id"}),
                        policy_id=new_policy.id,
                    )
                )

            for coverage in src_policy.coverages or []:
                new_vehicle_id = None
                if coverage.vehicle_id is not None:
                    new_vehicle_id = vehicle_id_map.get(coverage.vehicle_id)
                target_session.add(
                    Coverage(
                        **_model_values(
                            coverage, exclude={"id", "policy_id", "vehicle_id"}
                        ),
                        policy_id=new_policy.id,
                        vehicle_id=new_vehicle_id,
                    )
                )

            if src_policy.replaced_by_policy_id is not None:
                pending_replaced_by.append(
                    (new_policy.id, src_policy.replaced_by_policy_id)
                )

            for rel in src_policy.policy_relationships or []:
                pending_relationships.append(
                    {
                        "policy_id": rel.policy_id,
                        "related_policy_id": rel.related_policy_id,
                        "relationship_type": rel.relationship_type,
                        "confidence": rel.confidence,
                        "created_at": rel.created_at,
                    }
                )

        def _resolve_policy_id(old_id: int | None) -> int | None:
            if old_id is None:
                return None
            if old_id in policy_id_map:
                return policy_id_map[old_id]
            src_pol = source_session.get(Policy, old_id)
            if src_pol is None:
                return None
            num = _normalize_policy_number(src_pol.policy_number)
            if num:
                return target_policy_by_number.get(num)
            return None

        existing_rel_keys: set[tuple[int, int, str | None]] = {
            (r.policy_id, r.related_policy_id, r.relationship_type)
            for r in target_session.query(PolicyRelationship).all()
        }

        for rel in pending_relationships:
            new_policy_id = _resolve_policy_id(rel["policy_id"])
            new_related_id = _resolve_policy_id(rel["related_policy_id"])
            if new_policy_id is None or new_related_id is None:
                continue
            rel_key = (new_policy_id, new_related_id, rel["relationship_type"])
            if rel_key in existing_rel_keys:
                continue
            target_session.add(
                PolicyRelationship(
                    policy_id=new_policy_id,
                    related_policy_id=new_related_id,
                    relationship_type=rel["relationship_type"],
                    confidence=rel["confidence"],
                    created_at=rel["created_at"],
                )
            )
            existing_rel_keys.add(rel_key)
            result.imported_relationships += 1

        for new_policy_id, old_replaced_id in pending_replaced_by:
            resolved = _resolve_policy_id(old_replaced_id)
            if resolved is not None:
                pol = target_session.get(Policy, new_policy_id)
                if pol:
                    pol.replaced_by_policy_id = resolved

        target_session.commit()
    except Exception as exc:
        target_session.rollback()
        raise DbImportError(f"Merge failed: {exc}") from exc
    finally:
        source_session.close()
        target_session.close()
        source_engine.dispose()

    return result
