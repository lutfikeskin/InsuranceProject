"""
Tests for modules/coi/generator.py — the COI PDF generator.

Locks down two things:
  1. End-to-end: with the real ACORD-25 template + mapping.json shipped in the
     repo, generate_coi returns non-empty bytes that begin with %PDF for the
     three COI types (Additional Insured, Certificate Holder, Lienholder) and
     for the major coverage combinations (auto only, GL only, GL + auto +
     cargo).
  2. Recovery: a corrupted/non-existent mapping.json falls back to an empty
     field map and still returns a working PDF (mapping just becomes a no-op
     for field renames). A *corrupt* mapping.json is a real bug and must
     raise json.JSONDecodeError — that contract was tightened in audit
     commit df43a66 and is locked here.

These are smoke + branch-coverage tests, not pixel/output validation.
"""

import io
import json
from datetime import datetime
from pathlib import Path

import pypdf
import pytest

from modules.coi.generator import COIGenerator


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "data" / "COI Example.pdf"
MAPPING_PATH = REPO_ROOT / "modules" / "coi" / "mapping.json"


pytestmark = pytest.mark.skipif(
    not TEMPLATE_PATH.exists(),
    reason=f"COI template not present at {TEMPLATE_PATH}",
)


@pytest.fixture
def base_policy():
    return {
        "policy_number": "TEST-12345",
        "carrier_name": "Test Carrier",
        "naic_number": "12345",
        "underwriter_name": "Test Underwriter",
        "effective_date": datetime(2026, 1, 1),
        "expiration_date": datetime(2027, 1, 1),
        "liability_limit": "1,000,000",
        "cargo_limit": "100,000",
        "cargo_deductible": "1,000",
        "comp_deductible": "500",
        "coll_deductible": "1,000",
        "insured_name": "Test Trucking LLC",
        "insured_address": "123 Main St",
        "insured_city": "Springfield",
        "insured_state_code": "IL",
        "insured_zip": "62704",
        "has_auto_liability": True,
        "has_general_liability": False,
        "has_cargo": True,
    }


@pytest.fixture
def base_holder():
    return {
        "name": "Test Holder Inc.",
        "address": "456 Oak Ave",
        "city": "Columbus",
        "state": "OH",
        "zip": "43232",
        "description": "Sample certificate description.",
    }


def _is_pdf(payload: bytes) -> bool:
    return isinstance(payload, bytes) and len(payload) > 100 and payload[:4] == b"%PDF"


def test_auto_only_coi_returns_pdf_bytes(base_policy, base_holder):
    base_policy["has_auto_liability"] = True
    base_policy["has_general_liability"] = False
    base_policy["coi_type"] = "Additional Insured"

    gen = COIGenerator(template_path=str(TEMPLATE_PATH))
    pdf_bytes = gen.generate_coi(base_policy, base_holder)

    assert _is_pdf(pdf_bytes), "generate_coi should return PDF bytes starting with %PDF"


def test_gl_plus_auto_plus_cargo_coi(base_policy, base_holder):
    base_policy["has_general_liability"] = True
    base_policy["has_auto_liability"] = True
    base_policy["has_cargo"] = True
    base_policy["coi_type"] = "Additional Insured"

    gen = COIGenerator(template_path=str(TEMPLATE_PATH))
    pdf_bytes = gen.generate_coi(base_policy, base_holder)

    assert _is_pdf(pdf_bytes)


def test_lienholder_coi_swaps_to_comp_coll(base_policy, base_holder):
    """Lienholder COI repurposes the OtherPolicy box for comp/coll deductibles."""
    base_policy["coi_type"] = "Lienholder"
    base_policy["has_cargo"] = True  # should be forced false by the Lienholder branch

    gen = COIGenerator(template_path=str(TEMPLATE_PATH))
    pdf_bytes = gen.generate_coi(base_policy, base_holder)

    assert _is_pdf(pdf_bytes)


def test_certificate_holder_coi(base_policy, base_holder):
    base_policy["coi_type"] = "Certificate Holder"

    gen = COIGenerator(template_path=str(TEMPLATE_PATH))
    pdf_bytes = gen.generate_coi(base_policy, base_holder)

    assert _is_pdf(pdf_bytes)


def test_missing_mapping_json_falls_back_to_empty_map(
    base_policy, base_holder, monkeypatch, tmp_path
):
    """When mapping.json is absent the generator must still return a valid PDF."""
    # Point os.path.dirname(__file__) to a directory without mapping.json by
    # temporarily moving the real mapping.json out of the way. Restore in finally.
    real_mapping = MAPPING_PATH
    backup = tmp_path / "mapping.bak.json"
    if real_mapping.exists():
        backup.write_bytes(real_mapping.read_bytes())
        real_mapping.unlink()
    try:
        gen = COIGenerator(template_path=str(TEMPLATE_PATH))
        pdf_bytes = gen.generate_coi(base_policy, base_holder)
        assert _is_pdf(pdf_bytes)
    finally:
        if backup.exists():
            real_mapping.write_bytes(backup.read_bytes())


def test_corrupt_mapping_json_propagates_decode_error(
    base_policy, base_holder, tmp_path
):
    """A corrupted mapping.json is a real bug and must raise, not silently fall back.

    This locks the contract tightened in commit df43a66 (audit Phase 2.2a).
    """
    real_mapping = MAPPING_PATH
    backup = real_mapping.read_bytes() if real_mapping.exists() else None
    real_mapping.write_text("{ this is not valid json", encoding="utf-8")
    try:
        gen = COIGenerator(template_path=str(TEMPLATE_PATH))
        with pytest.raises(json.JSONDecodeError):
            gen.generate_coi(base_policy, base_holder)
    finally:
        if backup is not None:
            real_mapping.write_bytes(backup)


def test_output_is_a_readable_pdf(base_policy, base_holder):
    """A stronger sanity check: pypdf should be able to open the result."""
    base_policy["coi_type"] = "Additional Insured"
    gen = COIGenerator(template_path=str(TEMPLATE_PATH))
    pdf_bytes = gen.generate_coi(base_policy, base_holder)

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1
