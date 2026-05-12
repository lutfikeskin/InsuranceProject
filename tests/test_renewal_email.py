"""
Unit tests for modules/notifications/renewal_email.py.

The function under test is pure (no DB, no Streamlit) so we feed it dicts and
SimpleNamespace mocks instead of building real Policy ORM objects.
"""

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from modules.notifications import RenewalEmailDraft, draft_renewal_email


@pytest.fixture
def base_policy_dict():
    return {
        "insured_name": "Acme Trucking LLC",
        "insured_email": "ops@acme.example",
        "carrier_name": "Progressive",
        "policy_number": "AB-12345",
        "effective_date": date(2025, 1, 1),
        "expiration_date": date(2025, 12, 31),
        "premium": 4321.0,
    }


class TestBasicDraftShape:
    def test_returns_frozen_dataclass_with_four_fields(self, base_policy_dict):
        draft = draft_renewal_email(base_policy_dict, today=date(2025, 12, 1))
        assert isinstance(draft, RenewalEmailDraft)
        assert draft.to == "ops@acme.example"
        assert "Progressive" in draft.subject
        assert "AB-12345" in draft.subject
        assert draft.body
        assert draft.download_filename.endswith(".txt")

    def test_is_frozen(self, base_policy_dict):
        draft = draft_renewal_email(base_policy_dict, today=date(2025, 12, 1))
        with pytest.raises(Exception):
            # frozen=True → cannot set attributes
            draft.to = "someone-else@example.com"  # type: ignore[misc]


class TestBodyContent:
    def test_body_includes_all_required_fields(self, base_policy_dict):
        draft = draft_renewal_email(base_policy_dict, today=date(2025, 12, 1))
        body = draft.body
        assert "Acme Trucking LLC" in body
        assert "Progressive" in body
        assert "AB-12345" in body
        assert "Jan 01, 2025" in body
        assert "Dec 31, 2025" in body
        assert "$4,321.00" in body

    def test_signoff_defaults_to_your_agency(self, base_policy_dict):
        draft = draft_renewal_email(base_policy_dict, today=date(2025, 12, 1))
        assert "Your agency" in draft.body

    def test_signoff_can_be_customized(self, base_policy_dict):
        draft = draft_renewal_email(
            base_policy_dict, agency_name="Truckers National", today=date(2025, 12, 1)
        )
        assert "Truckers National" in draft.body


class TestDaysPhrase:
    @pytest.mark.parametrize(
        "today,expected_phrase",
        [
            (date(2025, 12, 1), "in 30 days"),  # 30 days before
            (date(2025, 12, 30), "tomorrow"),  # 1 day before
            (date(2025, 12, 31), "today"),  # day-of
            (date(2026, 1, 2), "2 day(s) ago"),  # 2 days after expiration
        ],
    )
    def test_days_phrase_handles_all_ranges(self, base_policy_dict, today, expected_phrase):
        draft = draft_renewal_email(base_policy_dict, today=today)
        assert expected_phrase in draft.body


class TestInputFlexibility:
    def test_accepts_simple_namespace(self):
        p = SimpleNamespace(
            insured_name="Bob",
            insured_email="bob@example.com",
            carrier_name="State Farm",
            policy_number="SF-1",
            effective_date=date(2025, 1, 1),
            expiration_date=date(2025, 12, 31),
            premium=1000.0,
        )
        draft = draft_renewal_email(p, today=date(2025, 12, 1))
        assert "Bob" in draft.body
        assert draft.to == "bob@example.com"

    def test_handles_none_policy_gracefully(self):
        # Edge case — empty draft instead of crashing.
        draft = draft_renewal_email(None, today=date(2025, 12, 1))
        assert isinstance(draft, RenewalEmailDraft)
        # Body still renders with sentinel values:
        assert "Policyholder" in draft.body
        assert "(unknown)" in draft.body

    def test_string_dates_parse(self):
        p = {
            "insured_name": "X",
            "carrier_name": "Y",
            "policy_number": "Z",
            "effective_date": "2025-01-01",
            "expiration_date": "12/31/2025",
            "premium": 100.0,
        }
        draft = draft_renewal_email(p, today=date(2025, 12, 1))
        assert "Jan 01, 2025" in draft.body
        assert "Dec 31, 2025" in draft.body
        assert "in 30 days" in draft.body

    def test_unparseable_date_passes_through(self):
        p = {
            "insured_name": "X",
            "carrier_name": "Y",
            "policy_number": "Z",
            "expiration_date": "next quarter",
            "premium": 100.0,
        }
        draft = draft_renewal_email(p, today=date(2025, 12, 1))
        # Raw string survives so the broker at least sees what was on file.
        assert "next quarter" in draft.body
        # And the days-phrase falls back to neutral copy.
        assert "in the near future" in draft.body


class TestPremiumFormatting:
    def test_float_premium(self):
        draft = draft_renewal_email(
            {"premium": 4321.5, "policy_number": "X"}, today=date(2025, 1, 1)
        )
        assert "$4,321.50" in draft.body

    def test_int_premium(self):
        draft = draft_renewal_email(
            {"premium": 1000, "policy_number": "X"}, today=date(2025, 1, 1)
        )
        assert "$1,000.00" in draft.body

    def test_string_premium_with_commas(self):
        draft = draft_renewal_email(
            {"premium": "$2,500.75", "policy_number": "X"}, today=date(2025, 1, 1)
        )
        assert "$2,500.75" in draft.body

    def test_missing_premium(self):
        draft = draft_renewal_email({"policy_number": "X"}, today=date(2025, 1, 1))
        assert "(not on file)" in draft.body

    def test_unparseable_premium_passes_through(self):
        draft = draft_renewal_email(
            {"premium": "See dec page", "policy_number": "X"}, today=date(2025, 1, 1)
        )
        assert "See dec page" in draft.body


class TestRecipient:
    def test_missing_email_yields_empty_to(self):
        draft = draft_renewal_email({"policy_number": "X"}, today=date(2025, 1, 1))
        assert draft.to == ""

    def test_email_passes_through(self):
        draft = draft_renewal_email(
            {"insured_email": "Foo@Bar.example", "policy_number": "X"},
            today=date(2025, 1, 1),
        )
        # We don't lowercase or validate — preserve what was extracted.
        assert draft.to == "Foo@Bar.example"


class TestFilename:
    def test_filename_includes_insured_and_policy(self, base_policy_dict):
        draft = draft_renewal_email(base_policy_dict, today=date(2025, 12, 1))
        assert "renewal_" in draft.download_filename
        assert "Acme_Trucking_LLC" in draft.download_filename
        assert "AB-12345" in draft.download_filename
        assert draft.download_filename.endswith(".txt")

    def test_filename_sanitizes_special_chars(self):
        draft = draft_renewal_email(
            {"insured_name": "Bob's BBQ & More", "policy_number": "POL/12 34"},
            today=date(2025, 1, 1),
        )
        # Slashes, spaces, apostrophes all become underscores.
        # No collapsed runs of underscores.
        assert "/" not in draft.download_filename
        assert " " not in draft.download_filename
        assert "__" not in draft.download_filename

    def test_filename_falls_back_when_names_empty(self):
        draft = draft_renewal_email({}, today=date(2025, 1, 1))
        # Should not crash; should produce a sensible filename.
        assert draft.download_filename.endswith(".txt")
        assert draft.download_filename.startswith("renewal_")
