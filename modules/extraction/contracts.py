from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ExtractionResultKind = Literal["policy", "endorsement", "non_extractable", "invalid"]

POLICY_RESULT_LIST_FIELDS = ("coverages", "vehicles", "drivers")
POLICY_DATA_SOURCES = {
    "full_policy",
    "coi_summary",
    "declarations_page_forced",
    "renewal_declarations_forced",
    "quote_forced",
    "application_forced",
    "unknown_forced",
}


@dataclass(frozen=True)
class ContractIssue:
    path: str
    message: str


@dataclass(frozen=True)
class ExtractionResultContract:
    kind: ExtractionResultKind
    issues: tuple[ContractIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def _issue(path: str, message: str) -> ContractIssue:
    return ContractIssue(path=path, message=message)


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _is_list(value: Any) -> bool:
    return isinstance(value, list)


def classify_extraction_result(result: Any) -> ExtractionResultKind:
    if not isinstance(result, dict):
        return "invalid"
    if result.get("extractable") is False:
        return "non_extractable"
    if result.get("policy_data_source") == "endorsement_summary" or "endorsement" in result:
        return "endorsement"
    return "policy"


def validate_extraction_result_contract(result: Any) -> ExtractionResultContract:
    kind = classify_extraction_result(result)
    issues: list[ContractIssue] = []

    if kind == "invalid":
        return ExtractionResultContract(
            kind=kind,
            issues=(_issue("$", "extraction result must be a JSON object"),),
        )

    if kind == "non_extractable":
        _validate_non_extractable(result, issues)
    elif kind == "endorsement":
        _validate_endorsement(result, issues)
    else:
        _validate_policy(result, issues)

    return ExtractionResultContract(kind=kind, issues=tuple(issues))


def _validate_classification(result: dict[str, Any], issues: list[ContractIssue]) -> None:
    classification = result.get("classification")
    if not _is_dict(classification):
        issues.append(_issue("classification", "classification must be an object"))
        return
    for field in ("document_type", "policy_type"):
        if not classification.get(field):
            issues.append(_issue(f"classification.{field}", "field is required"))


def _validate_non_extractable(result: dict[str, Any], issues: list[ContractIssue]) -> None:
    if not result.get("document_type"):
        issues.append(_issue("document_type", "document_type is required"))
    if not result.get("message"):
        issues.append(_issue("message", "message is required"))
    _validate_classification(result, issues)


def _validate_endorsement(result: dict[str, Any], issues: list[ContractIssue]) -> None:
    _validate_classification(result, issues)
    endorsement = result.get("endorsement")
    if not _is_dict(endorsement):
        issues.append(_issue("endorsement", "endorsement must be an object"))
        return
    for field in ("parent_policy_number", "effective_date"):
        if not endorsement.get(field):
            issues.append(_issue(f"endorsement.{field}", "field is required"))


def _validate_policy(result: dict[str, Any], issues: list[ContractIssue]) -> None:
    _validate_classification(result, issues)
    if not _is_dict(result.get("policy")):
        issues.append(_issue("policy", "policy must be an object"))
    for field in POLICY_RESULT_LIST_FIELDS:
        if not _is_list(result.get(field)):
            issues.append(_issue(field, "field must be an array"))
    source = result.get("policy_data_source")
    if source is not None and source not in POLICY_DATA_SOURCES:
        issues.append(_issue("policy_data_source", f"unsupported policy_data_source: {source}"))
