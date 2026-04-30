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


def normalize(val):
    if val is None:
        return ""
    s = str(val).strip().lower()
    # Strip currency symbols and thousand separators for numeric comparison.
    s = s.replace("$", "").replace(",", "")
    # Collapse multiple spaces.
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def compare_extraction(extracted, golden):
    config = get_carrier_config(golden)
    critical_errors = []
    warnings = []

    policy_ext = extracted.get("policy", {})
    policy_gold = golden.get("policy", {})

    for field in config["critical"]:
        if field in config["skip"]:
            continue
        ext_val = normalize(policy_ext.get(field))
        gold_val = normalize(policy_gold.get(field))
        if ext_val != gold_val:
            critical_errors.append(
                f"CRITICAL {field}: expected '{gold_val}' got '{ext_val}'"
            )

    for coll in config["variable"]:
        ext_count = len(extracted.get(coll, []) or [])
        gold_count = len(golden.get(coll, []) or [])
        if abs(ext_count - gold_count) > VARIABLE_COUNT_TOLERANCE:
            warnings.append(
                f"WARN {coll} count: expected ~{gold_count} got {ext_count}"
            )

    return critical_errors, warnings


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="Requires GEMINI_API_KEY env var")
@pytest.mark.parametrize("pdf_path,json_path", get_golden_pairs())
def test_extraction_accuracy(pdf_path, json_path):
    api_key = os.getenv("GEMINI_API_KEY")

    with open(json_path, "r", encoding="utf-8") as f:
        golden = json.load(f)

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    result, _, error = process_pdf(pdf_bytes, api_key=api_key)
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
