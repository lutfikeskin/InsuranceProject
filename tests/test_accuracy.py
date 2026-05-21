from collections import Counter
import json
import os
import re
from pathlib import Path

import pytest

from modules.extraction import process_pdf
from accuracy_config import (
    CARRIER_FIELD_WEIGHTS,
    VARIABLE_COUNT_TOLERANCE,
)

DATA_DIR = Path("tests/data")
FORCE_REFRESH_ENV = "EXTRACTION_ACCURACY_FORCE_REFRESH"
CLASSIFICATION_FIELDS = ("document_type", "policy_type")
COVERAGE_LIMIT_FIELDS = (
    "per_person",
    "per_accident",
    "per_occurrence",
    "combined_single_limit",
    "aggregate",
)


def get_golden_pairs():
    pairs = []
    for json_path in DATA_DIR.rglob("*.json"):
        if json_path.name == "ontology_golden.json":
            continue
        pdf_path = json_path.with_suffix(".pdf")
        if pdf_path.exists():
            pairs.append((str(pdf_path), str(json_path)))
    return pairs


def get_carrier_config(golden_data):
    carrier = golden_data.get("_meta", {}).get("carrier", "default")
    return CARRIER_FIELD_WEIGHTS.get(carrier, CARRIER_FIELD_WEIGHTS["default"])


def force_refresh_enabled() -> bool:
    return os.getenv(FORCE_REFRESH_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def normalize(val):
    if val is None:
        return ""
    s = str(val).strip().lower()
    # Strip currency symbols and thousand separators for numeric comparison.
    s = s.replace("$", "").replace(",", "")
    # Collapse multiple spaces.
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _truthy_signature(value) -> str:
    normalized = normalize(value)
    if normalized in {"true", "yes", "y", "1"}:
        return "true"
    if normalized in {"false", "no", "n", "0", ""}:
        return "false"
    return normalized


def _counter_delta(expected: Counter, actual: Counter) -> tuple[list, list]:
    missing = list((expected - actual).elements())
    extra = list((actual - expected).elements())
    return missing, extra


def _format_signature(sig) -> str:
    if isinstance(sig, tuple):
        return " | ".join(str(part) for part in sig if part not in ("", None))
    return str(sig)


def _coverage_signature(row: dict) -> tuple:
    limits = row.get("limits") if isinstance(row.get("limits"), dict) else {}
    return (
        normalize(row.get("coverage_code")),
        normalize(row.get("vehicle_vin")),
        *(normalize(limits.get(field)) for field in COVERAGE_LIMIT_FIELDS),
        normalize(row.get("deductible")),
    )


def _vehicle_signature(row: dict) -> tuple:
    vin = normalize(row.get("vin"))
    if vin:
        return ("vin", vin)
    return (
        "vehicle",
        normalize(row.get("year")),
        normalize(row.get("make")),
        normalize(row.get("model")),
        normalize(row.get("type") or row.get("vehicle_type")),
    )


def _driver_signature(row: dict) -> tuple:
    return (
        normalize(row.get("full_name") or row.get("name")),
        _truthy_signature(row.get("is_excluded")),
    )


def _compare_classification(extracted: dict, golden: dict, critical_errors: list[str]) -> None:
    ext_classification = extracted.get("classification") or {}
    golden_meta = golden.get("_meta") or {}
    golden_classification = golden.get("classification") or {}
    for field in CLASSIFICATION_FIELDS:
        expected = golden_meta.get(field) or golden_classification.get(field)
        if not expected:
            continue
        actual = ext_classification.get(field)
        if normalize(actual) != normalize(expected):
            critical_errors.append(
                f"CRITICAL classification.{field}: expected '{normalize(expected)}' got '{normalize(actual)}'"
            )


def _compare_signature_collection(
    name: str,
    extracted_rows: list,
    golden_rows: list,
    signature_fn,
    critical_errors: list[str],
    warnings: list[str],
    *,
    missing_is_critical: bool = True,
) -> None:
    expected = Counter(
        signature_fn(row)
        for row in golden_rows
        if isinstance(row, dict) and any(normalize(value) for value in row.values())
    )
    actual = Counter(
        signature_fn(row)
        for row in extracted_rows
        if isinstance(row, dict) and any(normalize(value) for value in row.values())
    )
    missing, extra = _counter_delta(expected, actual)
    missing_target = critical_errors if missing_is_critical else warnings
    missing_prefix = "CRITICAL" if missing_is_critical else "WARN"
    for sig in missing:
        missing_target.append(f"{missing_prefix} {name} missing: {_format_signature(sig)}")
    for sig in extra:
        warnings.append(f"WARN {name} extra: {_format_signature(sig)}")


def compare_extraction(extracted, golden):
    config = get_carrier_config(golden)
    critical_errors = []
    warnings = []

    _compare_classification(extracted, golden, critical_errors)

    policy_ext = extracted.get("policy", {})
    policy_gold = golden.get("policy", {})

    for field in config["critical"]:
        if field in config["skip"]:
            continue
        ext_val = normalize(policy_ext.get(field))
        gold_val = normalize(policy_gold.get(field))
        if ext_val != gold_val:
            critical_errors.append(
                f"CRITICAL policy.{field}: expected '{gold_val}' got '{ext_val}'"
            )

    for coll in config["variable"]:
        ext_count = len(extracted.get(coll, []) or [])
        gold_count = len(golden.get(coll, []) or [])
        if abs(ext_count - gold_count) > VARIABLE_COUNT_TOLERANCE:
            warnings.append(
                f"WARN {coll} count: expected ~{gold_count} got {ext_count}"
            )

    _compare_signature_collection(
        "coverage",
        extracted.get("coverages", []) or [],
        golden.get("coverages", []) or [],
        _coverage_signature,
        critical_errors,
        warnings,
        missing_is_critical=False,
    )
    _compare_signature_collection(
        "vehicle",
        extracted.get("vehicles", []) or [],
        golden.get("vehicles", []) or [],
        _vehicle_signature,
        critical_errors,
        warnings,
    )
    _compare_signature_collection(
        "driver",
        extracted.get("drivers", []) or [],
        golden.get("drivers", []) or [],
        _driver_signature,
        critical_errors,
        warnings,
    )

    return critical_errors, warnings

def test_compare_extraction_detects_nested_mismatch():
    golden = {
        "_meta": {"carrier": "default", "document_type": "declarations_page", "policy_type": "commercial_auto"},
        "policy": {
            "policy_number": "P1",
            "effective_date": "2026-01-01",
            "expiration_date": "2027-01-01",
            "carrier_name": "Carrier",
            "insured_name": "Insured",
            "liability_limit": "$1,000,000 CSL",
        },
        "coverages": [
            {
                "coverage_code": "AUTO_LIAB_CSL",
                "vehicle_vin": None,
                "limits": {"combined_single_limit": 1_000_000},
                "deductible": None,
            }
        ],
        "vehicles": [{"vin": "VIN123", "year": 2024, "make": "Ford", "model": "Transit"}],
        "drivers": [{"full_name": "Jane Driver", "is_excluded": False}],
    }
    extracted = {
        "classification": {"document_type": "declarations_page", "policy_type": "personal_auto"},
        "policy": dict(golden["policy"]),
        "coverages": [],
        "vehicles": [],
        "drivers": [],
    }

    critical_errors, warnings = compare_extraction(extracted, golden)

    assert any("classification.policy_type" in error for error in critical_errors)
    assert any("vehicle missing" in error for error in critical_errors)
    assert any("driver missing" in error for error in critical_errors)
    assert any("coverage missing" in warning for warning in warnings)


def test_force_refresh_env(monkeypatch):
    monkeypatch.delenv(FORCE_REFRESH_ENV, raising=False)
    assert force_refresh_enabled() is False
    monkeypatch.setenv(FORCE_REFRESH_ENV, "true")
    assert force_refresh_enabled() is True


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="Requires GEMINI_API_KEY env var")
@pytest.mark.parametrize("pdf_path,json_path", get_golden_pairs())
def test_extraction_accuracy(pdf_path, json_path):
    api_key = os.getenv("GEMINI_API_KEY")

    with open(json_path, "r", encoding="utf-8") as f:
        golden = json.load(f)

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    result, _, error = process_pdf(
        pdf_bytes,
        api_key=api_key,
        force_refresh=force_refresh_enabled(),
    )
    assert error is None, f"Extraction failed: {error}"

    critical_errors, warnings = compare_extraction(result, golden)

    for warning in warnings:
        print(f"WARN {warning}")

    assert not critical_errors, "\n".join(critical_errors)


def test_ontology_golden_fixture_acord_and_codes():
    """Static JSON: no API calls; exercises compliance, symbols, MI_PPI, trailer interchange, stacked UM."""
    path = DATA_DIR / "generic" / "ontology_golden.json"
    if not path.exists():
        pytest.skip("ontology_golden.json missing")
    with open(path, "r", encoding="utf-8") as f:
        golden = json.load(f)
    from reporting.acord_view import build_acord_view

    v = build_acord_view(golden)
    assert v["compliance"].get("doc_endorsements")
    pol_ont = v.get("policy_ontology") or {}
    assert pol_ont.get("um_stacked_effective_limit") == 300000
    assert v["commercial_flags"].get("symbol1_any_auto_suggested") is True
    assert v["acord_127_vehicles"][0].get("covered_auto_symbols") == "1,7"
    codes = {c.get("coverage_code") for c in (golden.get("coverages") or [])}
    assert "MI_PPI" in codes and "TRAILER_INTERCHANGE" in codes
