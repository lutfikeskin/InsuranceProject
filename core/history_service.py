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
        from utils.text_utils import normalize_string, parse_currency
        
        # Special case for currency-like values
        if isinstance(val, str) and ('$' in val or ',' in val):
             pass

        return normalize_string(val)

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
            'document_type': 'document_type',
            'premium_audit_flag': 'premium_audit_flag',
            'status': 'status' # New Field
        }

        for json_key, attr in scalar_map.items():
            if json_key in p_data: # ONLY compare if present in update payload
                new_val = p_data.get(json_key)
                old_val = getattr(policy, attr)
                
                parsed_new = new_val
                if "date" in json_key and isinstance(new_val, str) and new_val:
                    try:
                        parsed_new = datetime.fromisoformat(str(new_val)).date()
                    except ValueError:
                        pass

                norm_new = self._normalize(parsed_new)
                norm_old = self._normalize(old_val)

                if norm_new != norm_old:
                    changes.append({
                        "field": attr,
                        "old_value": str(old_val),
                        "new_value": str(parsed_new)
                    })
                    setattr(policy, attr, parsed_new)

        # CRITICAL FIX: If key is missing in new_data, ignore it (do not assume delete).
        
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

        if 'coverages' in new_data:
            new_covs = new_data.get('coverages', [])
            def _cov_sig_dict(cov):
                if isinstance(cov, dict):
                    limits = cov.get("limits") if isinstance(cov.get("limits"), dict) else {}
                    return (
                        cov.get("coverage_code"),
                        cov.get("per_person") if cov.get("per_person") is not None else limits.get("per_person"),
                        cov.get("per_accident") if cov.get("per_accident") is not None else limits.get("per_accident"),
                        cov.get("per_occurrence") if cov.get("per_occurrence") is not None else limits.get("per_occurrence"),
                        cov.get("combined_single_limit") if cov.get("combined_single_limit") is not None else limits.get("combined_single_limit"),
                        cov.get("aggregate") if cov.get("aggregate") is not None else limits.get("aggregate"),
                        cov.get("deductible"),
                    )
                return (
                    getattr(cov, "coverage_code", None),
                    getattr(cov, "per_person", None),
                    getattr(cov, "per_accident", None),
                    getattr(cov, "per_occurrence", None),
                    getattr(cov, "combined_single_limit", None),
                    getattr(cov, "aggregate", None),
                    getattr(cov, "deductible", None),
                )

            old_cov_sigs = {_cov_sig_dict(c) for c in policy.coverages}
            new_cov_sigs = {_cov_sig_dict(c) for c in new_covs}

            if old_cov_sigs != new_cov_sigs:
                changes.append({
                    "field": "coverages",
                    "old_value": list(sorted(old_cov_sigs)),
                    "new_value": list(sorted(new_cov_sigs))
                })
                collection_changes["coverages"] = True

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
        
        if 'additional_interests' in new_data:
            new_ais = new_data.get('additional_interests', [])
            old_ais_set = {f"{a.name}|{a.interest_type}" for a in policy.additional_interests}
            new_ais_set = {f"{a.get('name')}|{a.get('interest_type')}" for a in new_ais}
            
            if old_ais_set != new_ais_set:
                changes.append({
                    "field": "additional_interests",
                    "old_value": f"Count: {len(old_ais_set)}",
                    "new_value": f"Count: {len(new_ais_set)}"
                })
                collection_changes["additional_interests"] = True

        if "extraction_extras" in new_data:
            new_ex = new_data.get("extraction_extras")
            old_ex = getattr(policy, "extraction_extras", None)
            if self._normalize(new_ex) != self._normalize(old_ex):
                changes.append({
                    "field": "extraction_extras",
                    "old_value": str(old_ex)[:500] if old_ex else "",
                    "new_value": str(new_ex)[:500] if new_ex else "",
                })
                policy.extraction_extras = new_ex

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
