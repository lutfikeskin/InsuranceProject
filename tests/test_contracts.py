from core.product_registry import account_type_for_policy, get_product_spec
from core.review_contract import validate_review_task_payload
from modules.extraction.contracts import validate_extraction_result_contract


def _classification(policy_type="commercial_auto"):
    return {
        "document_type": "declarations_page",
        "policy_type": policy_type,
        "confidence": "high",
    }


def test_policy_extraction_contract_accepts_current_shape():
    result = {
        "classification": _classification(),
        "policy": {"policy_number": "P1"},
        "coverages": [],
        "vehicles": [],
        "drivers": [],
        "policy_data_source": "full_policy",
    }

    contract = validate_extraction_result_contract(result)

    assert contract.kind == "policy"
    assert contract.ok is True


def test_policy_extraction_contract_rejects_missing_arrays():
    result = {
        "classification": _classification(),
        "policy": {"policy_number": "P1"},
    }

    contract = validate_extraction_result_contract(result)

    assert contract.kind == "policy"
    assert {issue.path for issue in contract.issues} == {"coverages", "vehicles", "drivers"}


def test_endorsement_contract_requires_parent_and_effective_date():
    result = {
        "classification": _classification(),
        "policy_data_source": "endorsement_summary",
        "endorsement": {"parent_policy_number": "P1"},
    }

    contract = validate_extraction_result_contract(result)

    assert contract.kind == "endorsement"
    assert [issue.path for issue in contract.issues] == ["endorsement.effective_date"]


def test_non_extractable_contract_accepts_user_message():
    result = {
        "extractable": False,
        "document_type": "application",
        "message": "Applications require review.",
        "classification": _classification(),
    }

    contract = validate_extraction_result_contract(result)

    assert contract.kind == "non_extractable"
    assert contract.ok is True


def test_review_task_contract_requires_update_target():
    payload = {
        "filename": "policy.pdf",
        "file_hash": "abc",
        "status": "pending",
        "decision": "update_existing",
        "extraction_result": {"policy": {}},
    }

    contract = validate_review_task_payload(payload)

    assert [issue.path for issue in contract.issues] == ["target_policy_id"]


def test_product_registry_keeps_existing_account_type_behavior():
    assert account_type_for_policy("personal_auto") == "Personal"
    assert account_type_for_policy("commercial_auto") == "Commercial"
    assert account_type_for_policy("new_future_type") == "Commercial"
    assert get_product_spec("personal_auto").schema_scope == "personal_auto"
