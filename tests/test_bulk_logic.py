import io
import zipfile
from datetime import datetime
from types import SimpleNamespace

import pypdf

from core.services import COIService
from modules.coi import COIGenerator
from views.create_coi import (
    _build_gmail_compose_url,
    _has_meaningful_limit,
    _money_display,
    _safe_coi_pdf_filename,
)


def _base_policy(**overrides):
    policy = {
        "carrier_name": "Test Carrier",
        "naic_number": "12345",
        "policy_number": "POL-999",
        "effective_date": datetime(2023, 1, 1),
        "expiration_date": datetime(2024, 1, 1),
        "liability_limit": "$1,000,000",
        "general_liability_limit": "$2,000,000",
        "gl_occurrence_limit": "$2,000,000",
        "gl_general_aggregate": "$2,000,000",
        "cargo_limit": "$100,000",
        "cargo_deductible": "$1,000",
        "has_general_liability": True,
        "has_auto_liability": True,
        "has_cargo": True,
        "coi_type": "Additional Insured",
        "insured_name": "Test Insured",
        "insured_address": "123 Insured St",
        "insured_city": "City",
        "insured_state_code": "ST",
        "insured_zip": "12345",
        "vehicle_list_str": "",
        "driver_list_str": "",
    }
    policy.update(overrides)
    return policy


def _base_holder(**overrides):
    holder = {
        "name": "Holder",
        "address": "2 Main",
        "city": "City",
        "state": "ST",
        "zip": "00000",
        "description": "Ops",
    }
    holder.update(overrides)
    return holder


def _pdf_text(pdf_bytes: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages)


def test_bulk_generation_logic_uses_safe_filenames():
    gen = COIGenerator(template_path="data/COI Example.pdf")
    selected_companies = {
        "Comp A": {"name": "Comp A", "address": "Addr A", "city": "City A", "state": "SA", "zip": "11111"},
        "Comp B": {"name": "Comp B", "address": "Addr B", "city": "City B", "state": "SB", "zip": "22222"},
    }

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for comp_data in selected_companies.values():
            pdf = gen.generate_coi(_base_policy(), {**comp_data, "description": "Standard Description"})
            assert pdf
            zf.writestr(
                _safe_coi_pdf_filename("Test Insured", comp_data.get("name", "")),
                pdf,
            )

    zip_buffer.seek(0)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        file_list = zf.namelist()
        assert "COI - Test Insured - Comp A.pdf" in file_list
        assert "COI - Test Insured - Comp B.pdf" in file_list


def test_certificate_holder_clears_additional_insured_codes():
    gen = COIGenerator(template_path="data/COI Example.pdf")

    addl_pdf = gen.generate_coi(_base_policy(coi_type="Additional Insured"), _base_holder())
    holder_pdf = gen.generate_coi(_base_policy(coi_type="Certificate Holder"), _base_holder())

    addl_lines = [line.strip() for line in _pdf_text(addl_pdf).splitlines()]
    holder_lines = [line.strip() for line in _pdf_text(holder_pdf).splitlines()]

    assert addl_lines.count("Y") >= 1
    assert holder_lines.count("Y") == 0


def test_gl_occurrence_prefers_general_liability_limit():
    gen = COIGenerator(template_path="data/COI Example.pdf")
    pdf = gen.generate_coi(
        _base_policy(
            liability_limit="$1,000,000",
            general_liability_limit="$2,000,000",
            gl_occurrence_limit="$2,000,000",
            gl_general_aggregate="$5,000,000",
        ),
        _base_holder(),
    )
    text = _pdf_text(pdf)

    assert "$2,000,000" in text
    assert "$5,000,000" in text


def test_coi_without_gl_general_aggregate_falls_back_to_gl_limit():
    gen = COIGenerator(template_path="data/COI Example.pdf")
    pdf = gen.generate_coi(
        _base_policy(
            gl_general_aggregate=None,
            liability_limit="$1,000,000",
            general_liability_limit="$2,000,000",
            gl_occurrence_limit="$2,000,000",
            has_auto_liability=False,
            has_cargo=False,
            cargo_limit="",
        ),
        _base_holder(),
    )
    text = _pdf_text(pdf)

    assert pdf
    assert len(pdf) > 1000
    assert "$2,000,000" in text


def test_generation_payload_uses_underwriter_before_carrier():
    policy = SimpleNamespace(
        carrier_name="Brand Carrier",
        underwriter_name="Legal Underwriter Co",
        naic_number=None,
        policy_number="P1",
        effective_date=datetime(2023, 1, 1),
        expiration_date=datetime(2024, 1, 1),
        liability_limit="$1,000,000",
        general_liability_limit="$2,000,000",
        cargo_limit="null",
        cargo_deductible=None,
        comp_deductible=None,
        coll_deductible=None,
        has_general_liability=None,
        has_auto_liability=None,
        insured_name="Insured",
        insured_address="1 Main",
        insured_city="City",
        insured_state_code="ST",
        insured_zip="12345",
    )

    payload = COIService.build_generation_payload(policy)

    assert payload["carrier_name"] == "Legal Underwriter Co"
    assert payload["display_carrier_name"] == "Brand Carrier"
    assert payload["gl_occurrence_limit"] == "$2,000,000"
    assert payload["has_general_liability"] is True
    assert payload["has_auto_liability"] is True
    assert payload["has_cargo"] is False


def test_nullish_limits_and_slash_emails_are_normalized():
    assert not _has_meaningful_limit("null")
    assert not _has_meaningful_limit("N/A")
    assert _has_meaningful_limit("$100K Cargo")
    assert _money_display("1000") == "$1,000"
    assert _money_display("1,000") == "$1,000"
    assert _money_display("$1,000") == "$1,000"

    url = _build_gmail_compose_url("Insured", "one@example.com / two@example.com;three@example.com")
    assert "to=one%40example.com%2Ctwo%40example.com%2Cthree%40example.com" in url
