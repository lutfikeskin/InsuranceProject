import unittest
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, Policy, Vehicle, Driver, Coverage
from services import PolicyService, COIService
from datetime import date

class TestPolicyService(unittest.TestCase):
    def setUp(self):
        # Use in-memory SQLite for testing
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        self.service = PolicyService(self.session)

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(self.engine)

    def test_save_policy_success(self):
        p_data = {
            "carrier_name": "Test Carrier",
            "policy_number": "POL-001",
            "effective_date": "2023-01-01",
            "expiration_date": "2024-01-01",
            "insured_name": "John Doe",
            "has_general_liability": True,
            "has_auto_liability": True
        }
        success, msg = self.service.save_policy_from_extraction(p_data, [], [], [])
        self.assertTrue(success)
        
        # Verify
        p = self.service.get_policy_by_number("POL-001")
        self.assertIsNotNone(p)
        self.assertEqual(p.insured_name, "John Doe")

    def test_save_duplicate_policy(self):
        p_data = {
            "carrier_name": "Test Carrier",
            "policy_number": "POL-001",
            "effective_date": "2023-01-01"
        }
        # First save
        self.service.save_policy_from_extraction(p_data, [], [], [])
        
        # Second save (Duplicate)
        success, msg = self.service.save_policy_from_extraction(p_data, [], [], [])
        self.assertFalse(success)
        self.assertIn("duplicate", msg)

    def test_delete_policy(self):
        p_data = {
            "policy_number": "POL-DEL"
        }
        self.service.save_policy_from_extraction(p_data, [], [], [])
        p = self.service.get_policy_by_number("POL-DEL")
        self.assertIsNotNone(p)
        
        self.service.delete_policy(p)
        p_deleted = self.service.get_policy_by_number("POL-DEL")
        self.assertIsNone(p_deleted)

    def test_coi_preparation(self):
        # Setup data
        p = Policy(
            policy_number="COI-TEST",
            carrier_name="Progressive",
            insured_name="Test Trucking",
            effective_date=date(2023,1,1),
            expiration_date=date(2024,1,1)
        )
        self.session.add(p)
        self.session.commit()
        
        # Test COI Service
        p_data, desc_lines = COIService.prepare_coi_data(p)
        self.assertEqual(p_data['policy_number'], "COI-TEST")
        self.assertEqual(p_data['carrier_name'], "Progressive")
        
        # Check if NAIC lookup happened (Progressive mappings exist in utils)
        # Note: In our mock DB, we didn't mock naic_utils, so it should use the real one imported in services.py
        # "PROGRESSIVE" might fuzzy match or return empty if not exact. 
        # "Progressive Casualty Ins Co" is in mapping.
        
if __name__ == '__main__':
    unittest.main()
