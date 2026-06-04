from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from .database import Policy
from .history_model import PolicyHistory

class HistoryService:
    SCALAR_FIELD_MAP = {
        'carrier_name': 'carrier_name',
        'underwriter_name': 'underwriter_name',
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
        'has_general_liability': 'has_general_liability',
        'has_auto_liability': 'has_auto_liability',
        'insured_name': 'insured_name',
        'business_name': 'business_name',
        'insured_address': 'insured_address',
        'insured_city': 'insured_city',
        'insured_state_code': 'insured_state_code',
        'insured_zip': 'insured_zip',
        'financial_responsibility_name': 'financial_responsibility_name',
        'policy_type': 'policy_type',
        'account_type': 'account_type',
        'document_type': 'document_type',
        'classification_confidence': 'classification_confidence',
        'classification_signals': 'classification_signals',
        'field_confidences': 'field_confidences',
        'premium_audit_flag': 'premium_audit_flag',
        'status': 'status',
    }

    def __init__(self, session: Session):
        self.session = session

    def normalize(self, val):
        """Reduces '100,000' and 100000 to same value for comparison."""
        from utils.text_utils import normalize_string
        
        # Special case for currency-like values
        if isinstance(val, str) and ('$' in val or ',' in val):
             pass

        return normalize_string(val)

    def _sig_value(self, val):
        normalized = self.normalize(val)
        return "" if normalized is None else str(normalized)

    def list_for_policy(self, policy_id: int, *, limit: int = 200):
        """Reverse-chronological PolicyHistory rows for a single policy."""
        return (
            self.session.query(PolicyHistory)
            .filter(PolicyHistory.policy_id == policy_id)
            .order_by(PolicyHistory.timestamp.desc(), PolicyHistory.id.desc())
            .limit(limit)
            .all()
        )

    def _get_next_version(self, policy_id: int) -> int:
        """Calculates next version number."""
        max_ver = self.session.query(func.max(PolicyHistory.policy_version)).filter(
            PolicyHistory.policy_id == policy_id
        ).scalar()
        return (max_ver or 0) + 1

    def _parse_field_value(self, json_key, value):
        if "date" in json_key and isinstance(value, str) and value:
            s = value.strip()
            # Carriers print dates in many formats. Try the common ones; if all
            # fail, return None rather than the raw string so the SQLite Date
            # column gets a valid value (or NULL) instead of crashing on flush.
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(s, fmt).date()
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(s).date()
            except ValueError:
                return None
        return value

    def _collection_changes_template(self):
        return {
            "vehicles": False,
            "drivers": False,
            "coverages": False,
            "additional_interests": False
        }

    def vehicle_sig(self, vehicle):
        if isinstance(vehicle, dict):
            return (
                self._sig_value(vehicle.get("vin")),
                self._sig_value(vehicle.get("year")),
                self._sig_value(vehicle.get("make")),
                self._sig_value(vehicle.get("model")),
                self._sig_value(vehicle.get("gvw")),
                self._sig_value(vehicle.get("type") or vehicle.get("vehicle_type")),
                self._sig_value(vehicle.get("chassis")),
                self._sig_value(vehicle.get("body")),
            )
        return (
            self._sig_value(getattr(vehicle, "vin", None)),
            self._sig_value(getattr(vehicle, "year", None)),
            self._sig_value(getattr(vehicle, "make", None)),
            self._sig_value(getattr(vehicle, "model", None)),
            self._sig_value(getattr(vehicle, "gvw", None)),
            self._sig_value(getattr(vehicle, "vehicle_type", None)),
            self._sig_value(getattr(vehicle, "chassis", None)),
            self._sig_value(getattr(vehicle, "body", None)),
        )

    def driver_sig(self, driver):
        if isinstance(driver, dict):
            return (
                self._sig_value(driver.get("full_name")),
                self._sig_value(driver.get("license_number")),
                self._sig_value(driver.get("is_excluded")),
            )
        return (
            self._sig_value(getattr(driver, "full_name", None)),
            self._sig_value(getattr(driver, "license_number", None)),
            self._sig_value(getattr(driver, "is_excluded", None)),
        )

    def coverage_sig(self, coverage):
        if isinstance(coverage, dict):
            limits = coverage.get("limits") if isinstance(coverage.get("limits"), dict) else {}
            return (
                self._sig_value(coverage.get("coverage_code")),
                self._sig_value(coverage.get("family")),
                self._sig_value(coverage.get("type") or coverage.get("display_name")),
                self._sig_value(coverage.get("vehicle_vin")),
                self._sig_value(coverage.get("per_person") if coverage.get("per_person") is not None else limits.get("per_person")),
                self._sig_value(coverage.get("per_accident") if coverage.get("per_accident") is not None else limits.get("per_accident")),
                self._sig_value(coverage.get("per_occurrence") if coverage.get("per_occurrence") is not None else limits.get("per_occurrence")),
                self._sig_value(coverage.get("combined_single_limit") if coverage.get("combined_single_limit") is not None else limits.get("combined_single_limit")),
                self._sig_value(coverage.get("aggregate") if coverage.get("aggregate") is not None else limits.get("aggregate")),
                self._sig_value(coverage.get("deductible")),
            )
        vehicle = getattr(coverage, "vehicle", None)
        return (
            self._sig_value(getattr(coverage, "coverage_code", None)),
            self._sig_value(getattr(coverage, "family", None)),
            self._sig_value(getattr(coverage, "type", None)),
            self._sig_value(getattr(vehicle, "vin", None)),
            self._sig_value(getattr(coverage, "per_person", None)),
            self._sig_value(getattr(coverage, "per_accident", None)),
            self._sig_value(getattr(coverage, "per_occurrence", None)),
            self._sig_value(getattr(coverage, "combined_single_limit", None)),
            self._sig_value(getattr(coverage, "aggregate", None)),
            self._sig_value(getattr(coverage, "deductible", None)),
        )

    def additional_interest_sig(self, interest):
        if isinstance(interest, dict):
            return (
                self._sig_value(interest.get("name")),
                self._sig_value(interest.get("address")),
                self._sig_value(interest.get("interest_type")),
            )
        return (
            self._sig_value(getattr(interest, "name", None)),
            self._sig_value(getattr(interest, "address", None)),
            self._sig_value(getattr(interest, "interest_type", None)),
        )

    def _sorted_sigs(self, rows, sig_func):
        return sorted(sig_func(row) for row in rows)

    def preview_changes(self, policy: Policy, new_data: dict):
        """
        Compares an existing policy with new_data without mutating rows or writing history.
        Returns (is_changed, change_log, metadata).
        """
        changes = []
        collection_changes = self._collection_changes_template()

        p_data = new_data.get('policy', {})

        for json_key, attr in self.SCALAR_FIELD_MAP.items():
            if json_key in p_data:
                parsed_new = self._parse_field_value(json_key, p_data.get(json_key))
                old_val = getattr(policy, attr)

                if self.normalize(parsed_new) != self.normalize(old_val):
                    changes.append({
                        "field": attr,
                        "old_value": str(old_val),
                        "new_value": str(parsed_new)
                    })

        if 'vehicles' in new_data:
            new_vehs = new_data.get('vehicles', [])
            old_sigs = self._sorted_sigs(policy.vehicles, self.vehicle_sig)
            new_sigs = self._sorted_sigs(new_vehs, self.vehicle_sig)
            if old_sigs != new_sigs:
                changes.append({
                    "field": "vehicles",
                    "old_value": old_sigs,
                    "new_value": new_sigs
                })
                collection_changes["vehicles"] = True

        if 'coverages' in new_data:
            new_covs = new_data.get('coverages', [])
            old_sigs = self._sorted_sigs(policy.coverages, self.coverage_sig)
            new_sigs = self._sorted_sigs(new_covs, self.coverage_sig)
            if old_sigs != new_sigs:
                changes.append({
                    "field": "coverages",
                    "old_value": old_sigs,
                    "new_value": new_sigs
                })
                collection_changes["coverages"] = True

        if 'drivers' in new_data:
            new_drvs = new_data.get('drivers', [])
            old_sigs = self._sorted_sigs(policy.drivers, self.driver_sig)
            new_sigs = self._sorted_sigs(new_drvs, self.driver_sig)
            if old_sigs != new_sigs:
                changes.append({
                    "field": "drivers",
                    "old_value": old_sigs,
                    "new_value": new_sigs
                })
                collection_changes["drivers"] = True

        if 'additional_interests' in new_data:
            new_ais = new_data.get('additional_interests', [])
            old_sigs = self._sorted_sigs(policy.additional_interests, self.additional_interest_sig)
            new_sigs = self._sorted_sigs(new_ais, self.additional_interest_sig)
            if old_sigs != new_sigs:
                changes.append({
                    "field": "additional_interests",
                    "old_value": old_sigs,
                    "new_value": new_sigs
                })
                collection_changes["additional_interests"] = True

        if "extraction_extras" in new_data:
            new_ex = new_data.get("extraction_extras")
            old_ex = getattr(policy, "extraction_extras", None)
            if self.normalize(new_ex) != self.normalize(old_ex):
                changes.append({
                    "field": "extraction_extras",
                    "old_value": str(old_ex)[:500] if old_ex else "",
                    "new_value": str(new_ex)[:500] if new_ex else "",
                })

        return len(changes) > 0, changes, collection_changes

    def compare_and_record(self, policy: Policy, new_data: dict, source: str = "AI_Extraction", event_type: str = "AI_EXTRACTION"):
        """
        Compares existing policy with new_data. 
        Returns (is_changed, change_log, metadata)
        Mutates SCALAR fields here, but returns flags for COLLECTIONS to be mutated by caller.
        """
        is_changed, changes, collection_changes = self.preview_changes(policy, new_data)
        p_data = new_data.get('policy', {})

        for json_key, attr in self.SCALAR_FIELD_MAP.items():
            if json_key in p_data:
                setattr(policy, attr, self._parse_field_value(json_key, p_data.get(json_key)))

        if "extraction_extras" in new_data:
            policy.extraction_extras = new_data.get("extraction_extras")

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
             
        return is_changed, changes, collection_changes
