from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ReviewStatus = Literal["pending", "saved", "skipped", "failed"]
ReviewDecision = Literal["save_new", "update_existing", "save_endorsement", "skip"]

REVIEW_STATUSES: tuple[ReviewStatus, ...] = ("pending", "saved", "skipped", "failed")
REVIEW_DECISIONS: tuple[ReviewDecision, ...] = (
    "save_new",
    "update_existing",
    "save_endorsement",
    "skip",
)


@dataclass(frozen=True)
class ReviewContractIssue:
    path: str
    message: str


@dataclass(frozen=True)
class ReviewTaskContract:
    issues: tuple[ReviewContractIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def _issue(path: str, message: str) -> ReviewContractIssue:
    return ReviewContractIssue(path=path, message=message)


def validate_review_task_payload(payload: Any) -> ReviewTaskContract:
    issues: list[ReviewContractIssue] = []
    if not isinstance(payload, dict):
        return ReviewTaskContract((_issue("$", "review task must be an object"),))

    if not payload.get("filename"):
        issues.append(_issue("filename", "filename is required"))
    if not payload.get("file_hash"):
        issues.append(_issue("file_hash", "file_hash is required"))

    status = payload.get("status", "pending")
    if status not in REVIEW_STATUSES:
        issues.append(_issue("status", f"unsupported status: {status}"))

    extraction_result = payload.get("extraction_result")
    if not isinstance(extraction_result, dict):
        issues.append(_issue("extraction_result", "extraction_result must be an object"))

    decision = payload.get("decision")
    if decision is not None and decision not in REVIEW_DECISIONS:
        issues.append(_issue("decision", f"unsupported decision: {decision}"))
    if decision == "update_existing" and not payload.get("target_policy_id"):
        issues.append(_issue("target_policy_id", "target_policy_id is required for update_existing"))

    human_edits = payload.get("human_edits")
    if human_edits is not None and not isinstance(human_edits, dict):
        issues.append(_issue("human_edits", "human_edits must be an object when present"))

    return ReviewTaskContract(tuple(issues))
