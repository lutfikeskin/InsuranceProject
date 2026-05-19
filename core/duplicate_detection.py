from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy.orm import Session

from .database import Policy


def normalize_policy_number(policy_number: Any) -> str | None:
    """Normalize policy numbers for duplicate matching without changing stored values."""
    if policy_number is None:
        return None
    normalized = re.sub(r"[\s\-]+", "", str(policy_number).strip().upper())
    return normalized or None


def _normalize_name(value: Any) -> str | None:
    if value is None:
        return None
    clean = re.sub(r"[^A-Z0-9]+", " ", str(value).upper()).strip()
    return re.sub(r"\s+", " ", clean) or None


def _policy_summary(policy: Policy | None) -> dict[str, Any] | None:
    if policy is None:
        return None
    return {
        "id": policy.id,
        "policy_number": policy.policy_number,
        "insured_name": policy.insured_name,
        "carrier_name": policy.carrier_name,
        "underwriter_name": policy.underwriter_name,
        "policy_type": policy.policy_type,
        "effective_date": str(policy.effective_date) if policy.effective_date else None,
        "expiration_date": str(policy.expiration_date) if policy.expiration_date else None,
        "status": policy.status,
        "policy_status": policy.policy_status,
    }


@dataclass
class DuplicateDetectionResult:
    status: str
    confidence: str
    recommended_action: str
    reason: str
    existing_policy: Policy | None = None

    def to_dict(self, include_policy: bool = False) -> dict[str, Any]:
        payload = {
            "status": self.status,
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
            "reason": self.reason,
            "existing_policy_id": self.existing_policy.id if self.existing_policy else None,
            "existing_policy": _policy_summary(self.existing_policy),
        }
        if include_policy:
            payload["_policy_object"] = self.existing_policy
        return payload


class DuplicateDetectionService:
    """Resolves policy duplicates without deciding how persistence should proceed."""

    def __init__(self, session: Session):
        self.session = session

    def find_policy_by_normalized_number(self, policy_number: Any) -> Policy | None:
        normalized = normalize_policy_number(policy_number)
        if not normalized:
            return None

        exact = (
            self.session.query(Policy)
            .filter(Policy.policy_number == str(policy_number).strip())
            .first()
        )
        if exact:
            return exact

        candidates = (
            self.session.query(Policy)
            .filter(Policy.policy_number.isnot(None))
            .all()
        )
        for candidate in candidates:
            if normalize_policy_number(candidate.policy_number) == normalized:
                return candidate
        return None

    def find_possible_related_policy(self, policy_payload: dict) -> Policy | None:
        incoming_insured = _normalize_name(policy_payload.get("insured_name"))
        incoming_carrier = _normalize_name(policy_payload.get("carrier_name"))
        if not incoming_insured:
            return None

        candidates = self.session.query(Policy).filter(Policy.insured_name.isnot(None)).all()
        for candidate in candidates:
            if _normalize_name(candidate.insured_name) != incoming_insured:
                continue
            if incoming_carrier and _normalize_name(candidate.carrier_name) == incoming_carrier:
                return candidate
            if not incoming_carrier:
                return candidate
        return None

    def analyze_payload(self, extraction_result: dict) -> DuplicateDetectionResult:
        policy_payload = extraction_result.get("policy") or {}
        policy_number = policy_payload.get("policy_number")
        if not normalize_policy_number(policy_number):
            return DuplicateDetectionResult(
                status="missing_policy_number",
                confidence="low",
                recommended_action="review",
                reason="Incoming policy has no usable policy number.",
            )

        existing = self.find_policy_by_normalized_number(policy_number)
        if not existing:
            possible_related = self.find_possible_related_policy(policy_payload)
            if possible_related:
                return DuplicateDetectionResult(
                    status="possible_related_policy",
                    confidence="medium",
                    recommended_action="review",
                    reason=(
                        "No matching policy number was found, but another policy has the same insured"
                        " and may be related."
                    ),
                    existing_policy=possible_related,
                )
            return DuplicateDetectionResult(
                status="no_match",
                confidence="high",
                recommended_action="create_new",
                reason="No existing policy has the same normalized policy number.",
            )

        incoming_carrier = _normalize_name(policy_payload.get("carrier_name"))
        existing_carrier = _normalize_name(existing.carrier_name)
        incoming_insured = _normalize_name(policy_payload.get("insured_name"))
        existing_insured = _normalize_name(existing.insured_name)
        conflict_fields = []

        if incoming_carrier and existing_carrier and incoming_carrier != existing_carrier:
            conflict_fields.append("carrier_name")
        if incoming_insured and existing_insured and incoming_insured != existing_insured:
            conflict_fields.append("insured_name")

        if conflict_fields:
            return DuplicateDetectionResult(
                status="exact_number_carrier_conflict",
                confidence="medium",
                recommended_action="review",
                reason=(
                    "Policy number matches an existing record, but "
                    f"{', '.join(conflict_fields)} differs."
                ),
                existing_policy=existing,
            )

        return DuplicateDetectionResult(
            status="exact_policy_match",
            confidence="high",
            recommended_action="update_existing",
            reason="Policy number matches an existing policy.",
            existing_policy=existing,
        )
