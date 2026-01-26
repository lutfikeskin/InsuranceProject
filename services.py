from sqlalchemy.orm import Session
from database import Policy, Vehicle, Coverage, Driver
from naic_utils import get_naic_for_carrier
import pandas as pd

class PolicyService:
    def __init__(self, session: Session):
        self.session = session

    def get_dashboard_metrics(self):
        total_policies = self.session.query(Policy).count()
        total_vehicles = self.session.query(Vehicle).count()
        
        # Calculate Total Premium
        # Note: premiums are stored as strings (e.g. "$1,200.00")
        all_premiums = self.session.query(Policy.premium).all()
        total_premium = 0.0
        for (p_str,) in all_premiums:
            if p_str:
                try:
                    # Remove $, commas and other non-numeric chars except dot
                    import re
                    clean_val = re.sub(r'[^\d.]', '', p_str)
                    if clean_val:
                        total_premium += float(clean_val)
                except ValueError:
                    pass
                    
        return total_policies, total_vehicles, total_premium

    def get_recent_policies(self, limit=10):
        return self.session.query(Policy).order_by(Policy.id.desc()).limit(limit).all()

    def get_all_policies(self):
        return self.session.query(Policy).all()

    def get_policy_by_number(self, policy_number):
        return self.session.query(Policy).filter_by(policy_number=policy_number).first()

    def get_policy_by_id(self, policy_id):
        return self.session.query(Policy).get(policy_id)

    def delete_policy(self, policy: Policy):
        self.session.delete(policy)
        self.session.commit()

    def save_policy_from_extraction(self, p_data, vehicles_data, coverages_data, drivers_data):
        # Date parsing logic could reside here or in a utils helper, sticking to what was in app.py logic
        
        effective_dt = pd.to_datetime(p_data.get('effective_date'), errors='coerce')
        expiration_dt = pd.to_datetime(p_data.get('expiration_date'), errors='coerce')

        policy = Policy(
            carrier_name=p_data.get('carrier_name'),
            naic_number=p_data.get('naic_number'),
            policy_number=p_data.get('policy_number'),
            effective_date=effective_dt.date() if pd.notnull(effective_dt) else None,
            expiration_date=expiration_dt.date() if pd.notnull(expiration_dt) else None,
            account_type=p_data.get('account_type'),
            insured_name=p_data.get('insured_name'),
            business_name=p_data.get('business_name'),
            insured_address=p_data.get('insured_address'),
            insured_city=p_data.get('insured_city'),
            insured_state_code=p_data.get('insured_state_code'),
            insured_zip=p_data.get('insured_zip'),
            premium=p_data.get('premium'),
            state=p_data.get('state'),
            financial_responsibility_name=p_data.get('financial_responsibility_name'),
            liability_limit=p_data.get('liability_limit'),
            cargo_limit=p_data.get('cargo_limit'),
            cargo_deductible=p_data.get('cargo_deductible'),
            has_full_collision=p_data.get('has_full_collision'),
            has_general_liability=p_data.get('has_general_liability', True),
            has_auto_liability=p_data.get('has_auto_liability', True)
        )

        for v in vehicles_data:
            policy.vehicles.append(Vehicle(year=v.get('year'), make=v.get('make'), model=v.get('model'), vin=v.get('vin'), gvw=v.get('gvw'), vehicle_type=v.get('type')))
        
        for c in coverages_data:
            policy.coverages.append(Coverage(type=c.get('type'), limit_per_person=c.get('limit_person'), limit_per_accident=c.get('limit_accident'), deductible=c.get('deductible')))
        
        for d in drivers_data:
            policy.drivers.append(Driver(full_name=d.get('full_name'), license_number=d.get('license_number'), is_excluded=d.get('is_excluded')))

        # Duplicate check should ideally happen before calling save, or handled here.
        # Mirroring app.py logic which checked before adding.
        existing = self.get_policy_by_number(p_data.get('policy_number'))
        if existing:
            return False, f"Skipped duplicate: {p_data.get('policy_number')}"
        
        self.session.add(policy)
        self.session.commit()
        return True, "Saved successfully"

    def save_policy_object(self, policy: Policy):
        # Used when constructing object manually in review
        # Check duplicate
        existing = self.get_policy_by_number(policy.policy_number)
        if existing:
             # Logic in app.py was to warn. 
             # We will just raise or return false if we want strictness, 
             # but valid use case might be updating? 
             # For now, let's just add (sqlalchemy might error on constraint if not careful)
             pass 
        
        self.session.add(policy)
        self.session.commit()

    def update_policy(self, policy: Policy, updated_data: dict):
        """
        Updates an existing policy with a dictionary of new data.
        """
        for key, value in updated_data.items():
            if hasattr(policy, key):
                setattr(policy, key, value)
        
        self.session.commit()
        return True

class COIService:
    @staticmethod
    def prepare_coi_data(p: Policy):
        current_naic = p.naic_number if p.naic_number else get_naic_for_carrier(p.carrier_name)
        cargo_ded_val = p.cargo_deductible if p.cargo_deductible else "1000"
        
        has_gl = p.has_general_liability if p.has_general_liability is not None else True
        has_auto = p.has_auto_liability if p.has_auto_liability is not None else True
        
        p_data = {
            "carrier_name": p.carrier_name, 
            "naic_number": current_naic,
            "policy_number": p.policy_number, 
            "effective_date": p.effective_date, 
            "expiration_date": p.expiration_date, 
            "liability_limit": p.liability_limit,
            "cargo_limit": p.cargo_limit,
            "cargo_deductible": cargo_ded_val,
            "has_general_liability": has_gl,
            "has_auto_liability": has_auto,
            "insured_name": p.insured_name,
            "insured_address": p.insured_address,
            "insured_city": p.insured_city,
            "insured_state_code": p.insured_state_code,
            "insured_zip": p.insured_zip,
            "vehicle_list_str": "", 
            "driver_list_str": ""
        }
        
        # Descriptions logic
        desc_lines = []
        if p.vehicles:
            v_str = " ".join([f"[{v.year} {v.make} {v.vin}]" for v in p.vehicles])
            desc_lines.append(f"Vehicle List: {v_str}")
        if p.drivers:
            d_str = ", ".join([d.full_name for d in p.drivers])
            desc_lines.append(f"Driver List: {d_str}")
            
        return p_data, desc_lines
