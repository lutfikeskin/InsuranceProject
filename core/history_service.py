import json
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from .database import Policy, Coverage, Vehicle, Driver
from .history_model import PolicyHistory

class HistoryService:
    def __init__(self, session: Session):
        self.session = session

    def _normalize(self, val):
        """Reduces '100,000' and 100000 to same value for comparison."""
        if val is None:
            return None
        if isinstance(val, str):
            # Strip whitespace, commas, $
            s = val.strip().replace(",", "").replace("$", "").lower()
            if s == "none" or s == "": return None
            # Handle booleans in string form
            if s == "true": return True
            if s == "false": return False
            return s
        return val

    def _get_next_version(self, policy_id: int) -> int:
        """Calculates next version number."""
        max_ver = self.session.query(func.max(PolicyHistory.policy_version)).filter(
            PolicyHistory.policy_id == policy_id
        ).scalar()
        return (max_ver or 0) + 1



    def compare_and_record(self, policy: Policy, new_data: dict, source: str = "AI_Extraction", event_type: str = "AI_EXTRACTION"):
        """
        Compares existing policy with new_data. 
        Returns (is_changed, change_log, metadata)
        Mutates SCALAR fields here, but returns flags for COLLECTIONS to be mutated by caller.
        """
        changes = []
        collection_changes = {
            "vehicles": False,
            "drivers": False,
            "coverages": False,
            "additional_interests": False
        }
        
        # 1. Compare Scalar Fields (Policy Level)
        p_data = new_data.get('policy', {})
        
        scalar_map = {
            'carrier_name': 'carrier_name',
            'naic_number': 'naic_number',
            'effective_date': 'effective_date',
            'expiration_date': 'expiration_date',
            'premium': 'premium',
            'liability_limit': 'liability_limit',
            'general_liability_limit': 'general_liability_limit',
            'cargo_limit': 'cargo_limit',
            'cargo_deductible': 'cargo_deductible',
            'um_uim_limit': 'um_uim_limit',
            'med_pay_limit': 'med_pay_limit',
            'pip_limit': 'pip_limit',
            'comp_deductible': 'comp_deductible',
            'coll_deductible': 'coll_deductible',
            'has_full_collision': 'has_full_collision',
            'insured_name': 'insured_name',
            'insured_address': 'insured_address',
            'status': 'status' # New Field
        }

        for json_key, attr in scalar_map.items():
            if json_key in p_data: # ONLY compare if present in update payload
                new_val = p_data.get(json_key)
                old_val = getattr(policy, attr)
                
                # Date Handling without Pandas
                parsed_new = new_val
                if "date" in json_key and isinstance(new_val, str) and new_val:
                    try:
                        parsed_new = datetime.fromisoformat(str(new_val)).date()
                    except ValueError:
                        pass

                # Comparison
                norm_new = self._normalize(parsed_new)
                norm_old = self._normalize(old_val)

                if norm_new != norm_old:
                    changes.append({
                        "field": attr,
                        "old_value": str(old_val),
                        "new_value": str(parsed_new)
                    })
                    # Apply Update (Scalar only)
                    setattr(policy, attr, parsed_new)

        # 2. Compare Collections (Semantic Diff)
        # CRITICAL FIX: If key is missing in new_data, ignore it (do not assume delete).
        
        # Vehicles (By VIN)
        # Only process if 'vehicles' is explicitly in new_data
        if 'vehicles' in new_data:
            new_vehs = new_data.get('vehicles', [])
            old_vins = {v.vin for v in policy.vehicles if v.vin}
            new_vins = {v.get('vin') for v in new_vehs if v.get('vin')}
            
            is_veh_diff = False
            if old_vins or new_vins:
                if old_vins != new_vins:
                    is_veh_diff = True
            else:
                if len(policy.vehicles) != len(new_vehs):
                    is_veh_diff = True
            
            if is_veh_diff:
                changes.append({
                    "field": "vehicles",
                    "old_value": f"{len(policy.vehicles)} vehicles (VINs: {sorted(list(old_vins))})",
                    "new_value": f"{len(new_vehs)} vehicles (VINs: {sorted(list(new_vins))})"
                })
                collection_changes["vehicles"] = True

        # Coverages (By Code)
        if 'coverages' in new_data:
            new_covs = new_data.get('coverages', [])
            old_codes = {c.coverage_code for c in policy.coverages if c.coverage_code}
            new_codes = {c.get('coverage_code') for c in new_covs if c.get('coverage_code')}
            
            if old_codes != new_codes:
                changes.append({
                    "field": "coverages",
                    "old_value": list(sorted(old_codes)),
                    "new_value": list(sorted(new_codes))
                })
                collection_changes["coverages"] = True

        # Drivers
        if 'drivers' in new_data:
            new_drvs = new_data.get('drivers', [])
            old_drvs_set = {f"{d.full_name}|{d.license_number}" for d in policy.drivers}
            new_drvs_set = {f"{d.get('full_name')}|{d.get('license_number')}" for d in new_drvs}
            
            if old_drvs_set != new_drvs_set:
                changes.append({
                    "field": "drivers",
                    "old_value": f"Count: {len(old_drvs_set)}",
                    "new_value": f"Count: {len(new_drvs_set)}"
                })
                collection_changes["drivers"] = True
        
        # Additional Interests (New)
        if 'additional_interests' in new_data:
            new_ais = new_data.get('additional_interests', [])
            # Compare by Name
            old_ais_set = {f"{a.name}|{a.interest_type}" for a in policy.additional_interests}
            new_ais_set = {f"{a.get('name')}|{a.get('interest_type')}" for a in new_ais}
            
            if old_ais_set != new_ais_set:
                changes.append({
                    "field": "additional_interests",
                    "old_value": f"Count: {len(old_ais_set)}",
                    "new_value": f"Count: {len(new_ais_set)}"
                })
                collection_changes["additional_interests"] = True

        # 3. Persist History
        if changes:
             version = self._get_next_version(policy.id)
             history = PolicyHistory(
                 policy_id=policy.id,
                 source=source,
                 event_type=event_type,
                 policy_version=version,
                 changes=changes
             )
             self.session.add(history)
             
        return len(changes) > 0, changes, collection_changes
