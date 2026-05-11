"""Parse and normalize Gemini JSON extraction payloads."""

import json
from typing import Optional

from core.logger import logger
from utils.text_utils import clean_text as _clean_text, parse_us_address as _parse_us_address

from .extraction_types import ExtractionContext


def parse_json_response(
    text: str, ctx: Optional[ExtractionContext] = None
) -> dict:
    """Centralized result parser to handle Gemini's list/dict inconsistency recursively."""
    try:
        data = json.loads(text)
        while isinstance(data, list):
            if ctx:
                ctx.usage_metadata["json_unwraps"] = ctx.usage_metadata.get(
                    "json_unwraps", 0
                ) + 1

            if not data:
                return {}
            data = data[0]

        if isinstance(data, dict):
            return data
        return {}
    except Exception as e:
        logger.error(f"JSON Parse Error: {e}")
        if ctx:
            ctx.errors.append(f"parse_error:{e}")
            ctx.usage_metadata["parse_error"] = str(e)
        return {}


def normalize_coi_result(raw_data: dict, fallback_classification: dict) -> dict:
    policies = raw_data.get("policies") or []
    policy_rows = [p for p in policies if isinstance(p, dict)]

    def _pick_first_nonempty(key: str):
        for row in policy_rows:
            val = _clean_text(row.get(key))
            if val is not None:
                return val
        return None

    def _object_section(key: str) -> dict:
        section = raw_data.get(key)
        return section if isinstance(section, dict) else {}

    aggregated_limits = {}
    for row in policy_rows:
        limits = row.get("limits") if isinstance(row.get("limits"), dict) else {}
        for limit_key, limit_val in limits.items():
            clean_limit = _clean_text(limit_val)
            if clean_limit is not None and aggregated_limits.get(limit_key) in (
                None,
                "",
            ):
                aggregated_limits[limit_key] = clean_limit
        row_text = " ".join(
            str(v)
            for v in row.values()
            if not isinstance(v, (dict, list)) and v
        )
        limit_text = " ".join(str(v) for v in limits.values() if v)
        medpay_evidence = f"{row_text} {limit_text}".lower()
        if (
            aggregated_limits.get("med_pay_limit") in (None, "")
            and ("medical payments" in medpay_evidence or "med pay" in medpay_evidence)
            and ("incl" in medpay_evidence or "included" in medpay_evidence)
        ):
            aggregated_limits["med_pay_limit"] = "Included"

    classification = raw_data.get("classification") or fallback_classification or {}
    if "document_type" not in classification:
        classification["document_type"] = "certificate_of_insurance"

    insured_section = _object_section("insured")
    parsed_insured_address = _parse_us_address(insured_section.get("address"))
    insured_city = _clean_text(insured_section.get("city")) or parsed_insured_address[
        "city"
    ]
    insured_state_code = (
        _clean_text(insured_section.get("state_code"))
        or _clean_text(insured_section.get("state"))
        or parsed_insured_address["state_code"]
    )
    insured_zip = _clean_text(insured_section.get("zip")) or parsed_insured_address[
        "zip"
    ]
    classified_policy_type = (classification.get("policy_type") or "").lower()
    has_gl = bool(
        aggregated_limits.get("general_liability_limit")
        or classified_policy_type == "general_liability"
        or any("general" in (row.get("policy_type") or "").lower() for row in policy_rows)
    )
    has_auto = bool(
        aggregated_limits.get("liability_limit")
        or classified_policy_type in {"personal_auto", "commercial_auto"}
        or any("auto" in (row.get("policy_type") or "").lower() for row in policy_rows)
    )

    normalized_policy = {
        "carrier_name": _pick_first_nonempty("carrier_name"),
        "underwriter_name": _pick_first_nonempty("underwriter_name"),
        "naic_number": _pick_first_nonempty("naic_number"),
        "policy_number": _pick_first_nonempty("policy_number"),
        "effective_date": _pick_first_nonempty("effective_date"),
        "expiration_date": _pick_first_nonempty("expiration_date"),
        "insured_name": _clean_text(insured_section.get("name")),
        "insured_address": parsed_insured_address["address"],
        "insured_city": insured_city,
        "insured_state_code": insured_state_code,
        "insured_zip": insured_zip,
        "financial_responsibility_name": _clean_text(
            _object_section("producer").get("name")
        ),
        "liability_limit": aggregated_limits.get("liability_limit"),
        "general_liability_limit": aggregated_limits.get("general_liability_limit"),
        "cargo_limit": aggregated_limits.get("cargo_limit"),
        "cargo_deductible": aggregated_limits.get("cargo_deductible"),
        "um_uim_limit": aggregated_limits.get("um_uim_limit"),
        "med_pay_limit": aggregated_limits.get("med_pay_limit"),
        "pip_limit": aggregated_limits.get("pip_limit"),
        "comp_deductible": aggregated_limits.get("comp_deductible"),
        "coll_deductible": aggregated_limits.get("coll_deductible"),
        "has_general_liability": has_gl,
        "has_auto_liability": has_auto,
    }

    return {
        "classification": classification,
        "policy": normalized_policy,
        "compliance": {},
        "coverages": [],
        "vehicles": raw_data.get("vehicles")
        if isinstance(raw_data.get("vehicles"), list)
        else [],
        "drivers": raw_data.get("drivers")
        if isinstance(raw_data.get("drivers"), list)
        else [],
        "coi_summary": {
            "certificate_holder": _object_section("certificate_holder"),
            "insured": {
                **insured_section,
                "address": parsed_insured_address["address"],
                "city": insured_city,
                "state_code": insured_state_code,
                "zip": insured_zip,
            },
            "producer": _object_section("producer"),
            "policies": policies,
            "additional_insured_text": raw_data.get("additional_insured_text"),
            "cancellation_notice_days": raw_data.get("cancellation_notice_days"),
            "description_of_operations": raw_data.get("description_of_operations"),
        },
    }


def normalize_endorsement_result(
    raw_data: dict, fallback_classification: dict, file_hash: str
) -> dict:
    classification = raw_data.get("classification") or fallback_classification or {}
    if "document_type" not in classification:
        classification["document_type"] = "endorsement"
    endorsement = {
        "parent_policy_number": raw_data.get("parent_policy_number"),
        "endorsement_type": raw_data.get("endorsement_type"),
        "endorsement_form_number": raw_data.get("endorsement_form_number"),
        "effective_date": raw_data.get("effective_date"),
        "changes_summary": raw_data.get("changes_summary"),
        "file_hash": file_hash,
    }
    return {
        "classification": classification,
        "endorsement": endorsement,
    }


def clean_coverage_zeros(coverages: list) -> list:
    """
    Gemini's structured output fills missing INTEGER fields with 0 instead of null.
    Since $0 limits and $0 deductibles don't exist in real insurance documents,
    we safely convert them to None so downstream logic (summaries, validation) works correctly.
    """
    LIMIT_KEYS = {
        "per_person",
        "per_accident",
        "per_occurrence",
        "combined_single_limit",
        "aggregate",
    }
    for c in coverages:
        if isinstance(c.get("limits"), dict):
            for k in LIMIT_KEYS:
                if c["limits"].get(k) == 0:
                    c["limits"][k] = None
        if c.get("deductible") == 0:
            c["deductible"] = None
        if c.get("vehicle_vin") in ("null", ""):
            c["vehicle_vin"] = None
    return coverages
