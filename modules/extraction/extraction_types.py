"""Per-request extraction state and shared messages."""

from dataclasses import dataclass, field
from typing import Optional

NON_EXTRACTABLE_MESSAGES = {
    "quote": "This document is a quote/proposal and is not extractable as bound coverage.",
    "application": "This document is an application and is not extractable as active coverage.",
    "endorsement": "This endorsement requires a parent policy context and is skipped in Phase 3.",
}


@dataclass
class ExtractionContext:
    """Holds the state for a single extraction request."""

    file_bytes: bytes
    file_hash: str
    user_selected_policy_type: Optional[str] = None
    correlation_id: Optional[str] = None
    classification_warnings: list = field(default_factory=list)

    classification: dict = field(default_factory=dict)
    extracted_data: dict = field(default_factory=dict)

    final_policy: dict = field(default_factory=dict)
    final_coverages: list = field(default_factory=list)
    final_vehicles: list = field(default_factory=list)
    final_drivers: list = field(default_factory=list)

    usage_metadata: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    carrier_hints: str = ""
    variant_status: str = "known"

    @property
    def policy_type(self) -> str:
        return self.classification.get("policy_type", "unknown")

    @property
    def confidence(self) -> str:
        return self.classification.get("confidence", "unknown")
