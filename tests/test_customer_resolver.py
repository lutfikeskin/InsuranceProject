from core.customer_resolver import CustomerResolver


def test_dba_person_owner_is_extracted_from_commercial_insured_name():
    embedded = CustomerResolver.extract_embedded_owner_name(
        "Enmanuel Torres Bonilla DBA Enmanuel Torres Bonilla"
    )

    assert embedded == {
        "owner_name": "Enmanuel Torres Bonilla",
        "entity_name": "Enmanuel Torres Bonilla",
        "full_insured_name": "Enmanuel Torres Bonilla DBA Enmanuel Torres Bonilla",
    }


def test_corporate_dba_prefix_does_not_create_person_owner():
    embedded = CustomerResolver.extract_embedded_owner_name("ABC Trucking LLC DBA XYZ Logistics")

    assert embedded is None
