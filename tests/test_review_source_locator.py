import pytest

from utils.review_source_locator import (
    extract_review_field_values,
    locate_policy_field_sources,
    value_search_variants,
)


def test_extract_review_field_values_keeps_only_critical_scalars():
    values = extract_review_field_values(
        {
            "policy_number": " P-123 ",
            "insured_name": "Example Insured",
            "vehicles": [{"vin": "123"}],
            "empty": "",
            "field_confidences": {"policy_number": "high"},
        }
    )

    assert values == {
        "policy_number": "P-123",
        "insured_name": "Example Insured",
    }


def test_value_search_variants_include_date_and_money_forms():
    assert "05/01/2026" in value_search_variants("2026-05-01")
    assert "1000000" in value_search_variants("$1,000,000")


def test_locate_policy_field_sources_from_text_pdf():
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Policy Number: P-12345")
    page.insert_text((72, 96), "Named Insured: Example Trucking LLC")
    pdf_bytes = doc.tobytes()
    doc.close()

    result = locate_policy_field_sources(
        pdf_bytes,
        {
            "policy_number": "P-12345",
            "insured_name": "Example Trucking LLC",
        },
    )

    fields = {loc["field"]: loc for loc in result["locations"]}
    assert result["status"]["status"] == "ok"
    assert fields["policy_number"]["page_number"] == 1
    assert len(fields["policy_number"]["bbox"]) == 4
    assert fields["insured_name"]["match_quality"] == "exact"


def test_repeated_value_is_marked_ambiguous():
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Carrier: GEICO")
    page.insert_text((72, 96), "Insurer: GEICO")
    pdf_bytes = doc.tobytes()
    doc.close()

    result = locate_policy_field_sources(pdf_bytes, {"carrier_name": "GEICO"})

    assert result["locations"][0]["field"] == "carrier_name"
    assert result["locations"][0]["match_quality"] == "ambiguous"
    assert result["locations"][0]["match_count"] == 2
