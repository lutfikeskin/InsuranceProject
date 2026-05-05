from modules.extraction.pipeline import GeminiExtractionPipeline
from modules.extraction.prompts import get_extract_all_prompt, get_extract_coi_prompt


def test_manual_policy_type_preserves_detected_document_type():
    classification = GeminiExtractionPipeline._classification_with_user_policy_type(
        {
            "document_type": "certificate_of_insurance",
            "policy_type": "unknown",
            "confidence": "medium",
            "signals": ["ACORD certificate", "Certificate Holder"],
        },
        "commercial_auto",
    )

    assert classification["document_type"] == "certificate_of_insurance"
    assert classification["policy_type"] == "commercial_auto"
    assert classification["confidence"] == "high"
    assert classification["signals"][0] == "user_selected"
    assert len(classification["signals"]) <= 3


def test_full_policy_prompt_scopes_auto_instructions():
    prompt = get_extract_all_prompt(
        "{}",
        scoped_policy_type="commercial_auto",
    )

    assert "--- AUTO POLICY DETAILS ---" in prompt
    assert "covered auto designation symbols" in prompt
    assert "--- LIABILITY POLICY DETAILS ---" not in prompt


def test_full_policy_prompt_scopes_general_liability_instructions():
    prompt = get_extract_all_prompt(
        "{}",
        scoped_policy_type="general_liability",
    )

    assert "--- LIABILITY POLICY DETAILS ---" in prompt
    assert "Extract vehicles/drivers only when a schedule is actually present" in prompt
    assert "covered auto designation symbols" not in prompt


def test_coi_prompt_keeps_compact_producer_and_underwriter_rules():
    prompt = get_extract_coi_prompt(user_policy_type="commercial_auto")

    assert "dedicated PRODUCER box/section" in prompt
    assert "never fall back to carrier/insurer" in prompt
    assert "carrier_name = brand" in prompt
    assert "underwriter_name = full legal name" in prompt
    assert "user_selected" in prompt


def test_coi_normalization_handles_nullish_producer_and_underwriter():
    pipeline = GeminiExtractionPipeline.__new__(GeminiExtractionPipeline)

    normalized = pipeline._normalize_coi_result(
        {
            "classification": {
                "document_type": "certificate_of_insurance",
                "policy_type": "commercial_auto",
                "confidence": "high",
            },
            "certificate_holder": {"name": "Holder", "address": "1 Main"},
            "insured": {"name": "Insured", "address": "2 Main"},
            "producer": None,
            "policies": [
                {
                    "carrier_name": "GEICO",
                    "underwriter_name": "GEICO Marine Insurance Company",
                    "policy_number": "P-1",
                    "effective_date": "2025-01-01",
                    "expiration_date": "2026-01-01",
                    "limits": {"liability_limit": "N/A"},
                }
            ],
        },
        {},
    )

    assert normalized["policy"]["underwriter_name"] == "GEICO Marine Insurance Company"
    assert normalized["policy"]["liability_limit"] is None
    assert normalized["policy"]["financial_responsibility_name"] is None
    assert normalized["coi_summary"]["producer"] == {}


def test_coi_normalization_splits_insured_address_city_state_zip():
    pipeline = GeminiExtractionPipeline.__new__(GeminiExtractionPipeline)

    normalized = pipeline._normalize_coi_result(
        {
            "classification": {
                "document_type": "memorandum",
                "policy_type": "commercial_auto",
                "confidence": "high",
            },
            "certificate_holder": {"name": "Holder", "address": "1 Main"},
            "insured": {
                "name": "Enmanuel Torres Bonilla DBA Enmanuel Torres Bonilla",
                "address": "5074 LINDORA DR COLUMBUS, OH 43232",
            },
            "producer": None,
            "policies": [{"policy_type": "commercial_auto", "limits": {"liability_limit": "$1,000,000"}}],
        },
        {},
    )

    assert normalized["policy"]["insured_address"] == "5074 LINDORA DR"
    assert normalized["policy"]["insured_city"] == "COLUMBUS"
    assert normalized["policy"]["insured_state_code"] == "OH"
    assert normalized["policy"]["insured_zip"] == "43232"


def test_coi_normalization_prefers_structured_insured_address_fields():
    pipeline = GeminiExtractionPipeline.__new__(GeminiExtractionPipeline)

    normalized = pipeline._normalize_coi_result(
        {
            "classification": {
                "document_type": "certificate_of_insurance",
                "policy_type": "commercial_auto",
                "confidence": "high",
            },
            "certificate_holder": {"name": "Holder", "address": "1 Main"},
            "insured": {
                "name": "Insured",
                "address": "5074 LINDORA DR",
                "city": "Columbus",
                "state_code": "OH",
                "zip": "43232",
            },
            "producer": None,
            "policies": [{"policy_type": "commercial_auto", "limits": {"liability_limit": "$1,000,000"}}],
        },
        {},
    )

    assert normalized["policy"]["insured_address"] == "5074 LINDORA DR"
    assert normalized["policy"]["insured_city"] == "Columbus"
    assert normalized["policy"]["insured_state_code"] == "OH"
    assert normalized["policy"]["insured_zip"] == "43232"


def test_coi_normalization_preserves_medical_payments_included_and_gl_false():
    pipeline = GeminiExtractionPipeline.__new__(GeminiExtractionPipeline)

    normalized = pipeline._normalize_coi_result(
        {
            "classification": {
                "document_type": "memorandum",
                "policy_type": "commercial_auto",
                "confidence": "high",
            },
            "certificate_holder": {"name": "Holder", "address": "1 Main"},
            "insured": {"name": "Insured", "address": "2 Main"},
            "producer": None,
            "policies": [
                {
                    "policy_type": "commercial_auto",
                    "limits": {
                        "liability_limit": "$1,000,000",
                        "med_pay_limit": "MEDICAL PAYMENTS INCL",
                    },
                }
            ],
        },
        {},
    )

    assert normalized["policy"]["med_pay_limit"] == "MEDICAL PAYMENTS INCL"
    assert normalized["policy"]["has_auto_liability"] is True
    assert normalized["policy"]["has_general_liability"] is False
