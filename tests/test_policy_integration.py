import unittest
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services import PolicyService, ACCOUNT_TYPE_BY_POLICY
from database import init_db, get_session, Policy

class TestPolicyIntegration(unittest.TestCase):
    def setUp(self):
        # Setup in-memory DB for testing
        self.engine = init_db(":memory:")
        Session = get_session(self.engine)
        self.session = Session

    def tearDown(self):
        self.session.close()

    def test_account_type_mapping(self):
        """Verify that policy types map to the correct account types."""
        self.assertEqual(ACCOUNT_TYPE_BY_POLICY["personal_auto"], "Personal")
        self.assertEqual(ACCOUNT_TYPE_BY_POLICY["commercial_auto"], "Commercial")
        self.assertEqual(ACCOUNT_TYPE_BY_POLICY["unknown"], "Commercial")

    def test_normalization_logic(self):
        """Verify that normalize_policy_data correctly structures the input."""
        service = PolicyService(self.session)
        
        mock_extraction = {
            "policy": {
                "policy_number": "TEST-001",
                "carrier_name": "Test Carrier",
                "insured_name": "John Doe"
            },
            "classification": {
                "policy_type": "personal_auto",
                "confidence": "high",
                "signals": ["Personal Auto Policy", "Bodily Injury"]
            },
            "vehicles": [],
            "drivers": [],
            "coverages": []
        }
        
        normalized = service.normalize_policy_data(mock_extraction)
        
        # Checks
        self.assertEqual(normalized['policy']['account_type'], "Personal")
        self.assertEqual(normalized['policy']['policy_type'], "personal_auto")
        self.assertEqual(normalized['policy']['classification_confidence'], "high")
        self.assertIn("Personal Auto Policy", normalized['policy']['classification_signals'])

    def test_save_policy_flow(self):
        """Verify that a policy can be saved effectively with the new fields."""
        service = PolicyService(self.session)
        
        mock_extraction = {
            "policy": {
                "policy_number": "POL-12345",
                "carrier_name": "SafeInsure",
                "insured_name": "Acme Corp",
                "effective_date": "2024-01-01",
                "expiration_date": "2025-01-01",
                "premium": "$5,000.00"
            },
            "classification": {
                "policy_type": "commercial_auto",
                "confidence": "medium",
                "signals": ["Commercial Auto coverage"]
            },
            "vehicles": [
                {"year": 2022, "make": "Ford", "model": "F-150", "vin": "1FTRX1234567890", "gvw": 6000, "type": "Pickup"}
            ],
            "coverages": [],
            "drivers": []
        }
        
        success, msg = service.save_policy_from_extraction(mock_extraction)
        self.assertTrue(success)
        
        # Retrieve and verify
        saved_policy = service.get_policy_by_number("POL-12345")
        self.assertIsNotNone(saved_policy)
        self.assertEqual(saved_policy.policy_type, "commercial_auto")
        self.assertEqual(saved_policy.account_type, "Commercial")
        self.assertEqual(saved_policy.classification_confidence, "medium")
        self.assertEqual(len(saved_policy.vehicles), 1)
        self.assertEqual(saved_policy.vehicles[0].make, "Ford")

    def test_duplicate_prevention(self):
        """Verify that saving the same policy number twice returns False."""
        service = PolicyService(self.session)
        
        mock_extraction = {
            "policy": {"policy_number": "H-999"},
            "classification": {"policy_type": "personal_auto"},
            "vehicles": [], "drivers": [], "coverages": []
        }
        
        # First Save
        success1, _ = service.save_policy_from_extraction(mock_extraction)
        self.assertTrue(success1)
        
        # Second Save
        success2, msg = service.save_policy_from_extraction(mock_extraction)
        self.assertFalse(success2)
        self.assertIn("duplicate", msg.lower())


    def test_personal_auto_split_limit_assembly(self):
        """Verify that split limits are correctly assembled into the liability_limit string."""
        from extractor import build_personal_auto_liability_limit
        
        mock_coverages = [
            {"type": "Bodily Injury Liability", "family": "auto_liability", "limit_person": 30000, "limit_accident": 60000, "limit_property_damage": None},
            {"type": "Property Damage Liability", "family": "auto_liability", "limit_person": None, "limit_accident": None, "limit_property_damage": 50000}
        ]
        
        assembled = build_personal_auto_liability_limit(mock_coverages)
        self.assertEqual(assembled, "30/60/50")

    def test_csl_priority_over_um(self):
        """Verify CSL priority and exclusion of Uninsured Motorist limits."""
        from extractor import build_personal_auto_liability_limit
        
        mock_coverages = [
            # Primary CSL
            {"type": "Liability Insurance", "family": "auto_liability", "limit_accident": 100000, "limit_person": None},
            # UM Split Limits (Should be ignored)
            {"type": "Uninsured Motorist", "family": "uninsured_motorist", "limit_accident": 100000, "limit_person": 50000},
            # UIM Split Limits (Should be ignored)
            {"type": "Underinsured Motorist", "family": "underinsured_motorist", "limit_accident": 100000, "limit_person": 50000}
        ]
        
        assembled = build_personal_auto_liability_limit(mock_coverages)
        self.assertEqual(assembled, "100 CSL")

    def test_manual_entry_validation_test(self):
        """Verify duplicate validation on manual entry logic."""
        service = PolicyService(self.session)
        policy = Policy(
            policy_number="MANUAL-001",
            insured_name="Manual User",
            policy_type="personal_auto"
        )
        
        # Save once
        success, _ = service.save_policy_object(policy)
        self.assertTrue(success)
        
        # Save exact object again (should fail)
        success2, msg = service.save_policy_object(policy)
        self.assertFalse(success2)
        self.assertIn("duplicate", msg.lower())

if __name__ == '__main__':
    unittest.main()
