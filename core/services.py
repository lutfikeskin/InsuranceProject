from __future__ import annotations

from sqlalchemy.orm import Session
from .database import get_session, Policy, Vehicle, Driver, Coverage, ApiUsage
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from utils.naic_utils import get_naic_for_carrier
from .coverage_ontology import summarize_auto_liability, format_liability_limit
from utils.vehicle_utils import refine_vehicle_type
import pandas as pd
import json
import re

ACCOUNT_TYPE_BY_POLICY = {
    "personal_auto": "Personal",
    "commercial_auto": "Commercial",
    "general_liability": "Commercial",
    "bop": "Commercial",
    "commercial_package": "Commercial",
    "umbrella": "Commercial",
    "motor_truck_cargo": "Commercial",
    "unknown": "Commercial" # Default to Commercial for unknown if we somehow get here
}


def build_extraction_extras_json(extraction_result: dict) -> str | None:
    """
    JSON blob for compliance, statutory/UM policy annotations, and per-row vehicle/coverage
    fields that are not stored in relational columns.
    """
    comp = dict(extraction_result.get("compliance") or {})
    policy_data_source = extraction_result.get("policy_data_source")
    pol = extraction_result.get("policy") or {}
    coverages = extraction_result.get("coverages") or []
    vehicles = extraction_result.get("vehicles") or []
    audits = extraction_result.get("audits") or {}
    pol_ont = {k: pol.get(k) for k in (
        "um_stacked_effective_limit",
        "statutory_auto_liability_display",
        "statutory_auto_liability_resolved",
    ) if pol.get(k) is not None}
    veh_ont = [
        {
            "vin": v.get("vin"),
            "covered_auto_symbols": v.get("covered_auto_symbols"),
            "radius_of_operation": v.get("radius_of_operation"),
            "business_use_class": v.get("business_use_class"),
        }
        for v in vehicles
    ]
    cov_ont = [
        {
            "coverage_code": c.get("coverage_code"),
            "vehicle_vin": c.get("vehicle_vin"),
            "hnoa_basis": c.get("hnoa_basis"),
            "hnoa_attached_to": c.get("hnoa_attached_to"),
        }
        for c in coverages
    ]

    def _row_has_values(d: dict) -> bool:
        return any(v not in (None, "", [], {}) for v in d.values())

    has_content = bool(comp) or bool(pol_ont) or bool(policy_data_source) or bool(audits) or any(
        _row_has_values(d) for d in veh_ont
    ) or any(_row_has_values(d) for d in cov_ont)
    if not has_content:
        return None
    payload = {
        "policy_data_source": policy_data_source,
        "compliance": comp,
        "audits": audits,
        "policy_ontology": pol_ont,
        "vehicles_ontology": veh_ont,
        "coverages_ontology": cov_ont,
    }
    return json.dumps(payload, sort_keys=True, default=str)

SQL_SCHEMA_CONTEXT = """
You are a SQLite expert. Convert the user question into a valid SQL query.

Database Schema:
Table 'policies':
  - id (int)
  - carrier_name (text)
  - policy_number (text)
  - effective_date (date YYYY-MM-DD)
  - expiration_date (date YYYY-MM-DD)
  - liability_limit (text, e.g. '$1,000,000')
  - general_liability_limit (text, e.g. '$1,000,000 Occ')
  - insured_name (text)
  - premium (text)
  - has_full_collision (bool)
  - policy_type (text, e.g. 'personal_auto', 'commercial_auto', 'general_liability')
  - account_type (text, e.g. 'Personal', 'Commercial')
  - has_auto_liability (bool)
  - has_general_liability (bool)

Table 'vehicles':
  - policy_id (fk to policies.id)
  - year (int)
  - make (text)
  - model (text)
  - vin (text)
  - gvw (int)
  - vehicle_type (text, e.g. 'Straight Truck', 'Tractor', 'Cargo Van')
  - chassis (text, e.g. 'Cab Chassis', 'Pickup')
  - body (text, e.g. 'Box', 'Dump')

Table 'drivers':
  - policy_id (fk to policies.id)
  - full_name (text)
  - license_number (text)
  - is_excluded (bool)

Table 'coverages':
  - policy_id (fk to policies.id)
  - coverage_code (text, e.g. 'AUTO_LIAB_BI', 'GL_OCCURRENCE')
  - family (text, e.g. 'auto_liability', 'general_liability')
  - per_person (int)
  - per_accident (int)
  - per_occurrence (int)
  - combined_single_limit (int)
  - aggregate (int)
  - deductible (int)
  - type (text, display name)

Rules:
1. Return ONLY the raw SQL query. No markdown, no explanations.
2. DO NOT include semicolons (;) at the end of the query.
3. Use LIKE for text searching (case insensitive).
4. Handle currency strings in 'liability_limit' or 'premium' by stripping '$' and ',' if mathematical comparison is needed (e.g. CAST(REPLACE(REPLACE(premium, '$', ''), ',', '') AS FLOAT)).
5. If asking for specific coverages like "Comp/Coll", check 'has_full_collision' or join with coverages table if needed (but currently simplified to boolean flags on policy).
""".strip()

class PolicyService:
    CRITICAL_CONFIDENCE_FIELDS = (
        "carrier_name",
        "policy_number",
        "effective_date",
        "expiration_date",
        "liability_limit",
        "cargo_limit",
        "premium",
        "insured_name",
    )

    REQUIRED_FOR_COI = (
        "carrier_name",
        "policy_number",
        "effective_date",
        "expiration_date",
        "insured_name",
        "liability_limit",
    )
    RECOMMENDED_FOR_COI = ("naic_number", "insured_address", "cargo_limit")

    @classmethod
    def _extract_field_confidences(cls, policy_data: dict) -> dict | None:
        if not isinstance(policy_data, dict):
            return None
        confidences: dict[str, str] = {}
        for field in cls.CRITICAL_CONFIDENCE_FIELDS:
            raw_conf = policy_data.get(f"{field}_confidence")
            conf = cls._clean_text(raw_conf)
            if conf not in {"high", "medium", "low"}:
                continue
            confidences[field] = conf
        return confidences or None

    @staticmethod
    def _clean_text(value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        compact = " ".join(value.replace("\u200b", "").split()).strip()
        if not compact:
            return None
        if compact.lower() in {"null", "none", "n/a", "-"}:
            return None
        return compact

    @classmethod
    def _clean_limit_text(cls, value):
        text = cls._clean_text(value)
        if text is None:
            return None
        # Normalize common OCR split tokens for cargo lines.
        normalized = text.replace("Cargo w/", "Cargo w /").replace("Deductible", "Deductible")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @classmethod
    def _merge_coi_policy_rows(cls, rows: list[dict]) -> dict:
        merged: dict = {}
        merged_limits: dict = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in (
                "policy_type",
                "carrier_name",
                "carrier_name_confidence",
                "naic_number",
                "policy_number",
                "policy_number_confidence",
                "effective_date",
                "effective_date_confidence",
                "expiration_date",
                "expiration_date_confidence",
                "insured_name",
                "insured_name_confidence",
                "premium",
                "premium_confidence",
            ):
                val = cls._clean_text(row.get(key))
                if val is not None and merged.get(key) in (None, ""):
                    merged[key] = val
            limits = row.get("limits") if isinstance(row.get("limits"), dict) else {}
            for limit_key, limit_val in limits.items():
                clean_limit = cls._clean_limit_text(limit_val)
                if clean_limit is not None and merged_limits.get(limit_key) in (None, ""):
                    merged_limits[limit_key] = clean_limit
        merged["limits"] = merged_limits
        return merged

    def _save_single_extraction_payload(self, extraction_result):
        new_policy = self._create_policy_instance(extraction_result)
        existing = self.get_policy_by_number(new_policy.policy_number)

        if existing:
            from .history_service import HistoryService
            history_svc = HistoryService(self.session)

            normalized = self.normalize_policy_data(extraction_result)
            is_changed, changes, collection_changes = history_svc.compare_and_record(
                existing, normalized, source="AI_Re-Extraction", event_type="AI_EXTRACTION"
            )

            if is_changed:
                if collection_changes["vehicles"]:
                    existing.vehicles.clear()
                    for v in new_policy.vehicles:
                        existing.vehicles.append(Vehicle(
                            year=v.year, make=v.make, model=v.model, vin=v.vin,
                            gvw=v.gvw, vehicle_type=v.vehicle_type, chassis=v.chassis, body=v.body
                        ))

                if collection_changes["coverages"]:
                    existing.coverages.clear()
                    vin_map_existing = {
                        str(v.vin).strip().upper(): v
                        for v in existing.vehicles
                        if getattr(v, "vin", None)
                    }
                    for c in new_policy.coverages:
                        matched_ev = None
                        if c.vehicle is not None and getattr(c.vehicle, "vin", None):
                            matched_ev = vin_map_existing.get(str(c.vehicle.vin).strip().upper())
                        existing.coverages.append(
                            Coverage(
                                type=c.type,
                                coverage_code=c.coverage_code,
                                family=c.family,
                                per_person=c.per_person,
                                per_accident=c.per_accident,
                                per_occurrence=c.per_occurrence,
                                combined_single_limit=c.combined_single_limit,
                                aggregate=c.aggregate,
                                limit_per_person=c.limit_per_person,
                                limit_per_accident=c.limit_per_accident,
                                limit_property_damage=c.limit_property_damage,
                                deductible=c.deductible,
                                vehicle=matched_ev,
                            )
                        )

                if collection_changes["drivers"]:
                    existing.drivers.clear()
                    for d in new_policy.drivers:
                        existing.drivers.append(Driver(full_name=d.full_name, license_number=d.license_number, is_excluded=d.is_excluded))

                if collection_changes["additional_interests"]:
                    existing.additional_interests.clear()
                    for a in new_policy.additional_interests:
                        from .database import AdditionalInterest
                        existing.additional_interests.append(AdditionalInterest(
                            name=a.name, address=a.address, interest_type=a.interest_type
                        ))

                self.session.commit()
                return True, f"Updated existing policy. {len(changes)} changes logged (Version updated)."
            return False, "No changes detected."

        self.session.add(new_policy)
        self.session.commit()
        return True, "Saved successfully"

    def __init__(self, session: Session):
        self.session = session

    def get_dashboard_metrics(self):
        total_policies = self.session.query(Policy).count()
        total_vehicles = self.session.query(Vehicle).count()
        
        # Note: premiums are stored as strings (e.g. "$1,200.00")
        all_premiums = self.session.query(Policy.premium).all()
        total_premium = 0.0
        for (p_str,) in all_premiums:
            if p_str:
                try:
                    import re
                    clean_val = re.sub(r'[^\d.]', '', p_str)
                    if clean_val:
                        total_premium += float(clean_val)
                except ValueError:
                    pass
                    
        return total_policies, total_vehicles, total_premium

    def get_recent_policies(self, limit=10):
        return self.session.query(Policy).order_by(Policy.id.desc()).limit(limit).all()

    def search_policies(self, term: str | None = None, *, limit: int = 100, offset: int = 0):
        """
        Return policies matching policy_number or insured_name (case-insensitive).
        Empty/whitespace term: most recent policies only (capped by limit).
        """
        q = self.session.query(Policy)
        if term and str(term).strip():
            t = f"%{str(term).strip()}%"
            q = q.filter(
                or_(
                    Policy.policy_number.ilike(t),
                    Policy.insured_name.ilike(t),
                )
            )
        return q.order_by(Policy.id.desc()).offset(offset).limit(limit).all()

    def count_policies(self, term: str | None = None) -> int:
        """Count policies matching the same filter as search_policies (no limit)."""
        q = self.session.query(Policy)
        if term and str(term).strip():
            t = f"%{str(term).strip()}%"
            q = q.filter(
                or_(
                    Policy.policy_number.ilike(t),
                    Policy.insured_name.ilike(t),
                )
            )
        return q.count()

    def get_all_policies(self):
        """Backward-compatible: capped list of recent policies (newest first)."""
        return self.search_policies(None, limit=10000, offset=0)

    def get_policy_by_number(self, policy_number):
        return self.session.query(Policy).filter_by(policy_number=policy_number).first()

    def get_policy_by_id(self, policy_id):
        return self.session.query(Policy).get(policy_id)

    def delete_policy(self, policy: Policy):
        self.session.delete(policy)
        self.session.commit()

    def get_expiring_policies(self, days=30):
        """Returns policies expiring within the given number of days."""
        from datetime import date
        today = date.today()
        cutoff = today + timedelta(days=days)
        return self.session.query(Policy).filter(
            Policy.expiration_date != None,
            Policy.expiration_date >= today,
            Policy.expiration_date <= cutoff
        ).order_by(Policy.expiration_date.asc()).all()

    def check_duplicate(self, policy_number):
        """Returns existing policy with the same number, or None."""
        if not policy_number:
            return None
        return self.session.query(Policy).filter_by(policy_number=policy_number).first()

    def get_carrier_distribution(self):
        """Returns dict of {carrier_name: count} for all policies."""
        results = self.session.query(
            Policy.carrier_name, func.count(Policy.id)
        ).group_by(Policy.carrier_name).all()
        return {name or "Unknown": count for name, count in results}

    def get_expiration_timeline(self, months=6):
        """Returns dict of {month_label: count} for policies expiring in the next N months."""
        from datetime import date
        import calendar
        today = date.today()
        cutoff = today + timedelta(days=months * 30)
        
        expiring = self.session.query(Policy.expiration_date).filter(
            Policy.expiration_date != None,
            Policy.expiration_date >= today,
            Policy.expiration_date <= cutoff
        ).all()
        
        monthly = {}
        for i in range(months):
            future = today + timedelta(days=i * 30)
            label = f"{calendar.month_abbr[future.month]} {future.year}"
            monthly[label] = 0
        
        for (exp_date,) in expiring:
            if exp_date:
                label = f"{calendar.month_abbr[exp_date.month]} {exp_date.year}"
                if label in monthly:
                    monthly[label] += 1
        
        return monthly

    def normalize_policy_data(self, extraction_result):
        """
        Normalizes raw extraction data into a standard structure for persistence.
        """
        policy_data = extraction_result.get('policy', {})
        classification = extraction_result.get('classification', {})
        policy_type = classification.get('policy_type', 'unknown')
        
        account_type = ACCOUNT_TYPE_BY_POLICY.get(policy_type, "Commercial")
        policy_data['account_type'] = account_type
        
        policy_data['policy_type'] = policy_type
        policy_data['document_type'] = classification.get('document_type')
        policy_data['classification_confidence'] = classification.get('confidence')
        policy_data['classification_signals'] = json.dumps(classification.get('signals', []))
        policy_data['field_confidences'] = self._extract_field_confidences(policy_data)
        policy_data['premium_audit_flag'] = (
            (extraction_result.get("audits") or {}).get("premium", {}).get("flag")
        )
        
        return {
            "policy": policy_data,
            "vehicles": extraction_result.get('vehicles', []),
            "coverages": extraction_result.get('coverages', []),
            "drivers": extraction_result.get('drivers', []),
            "additional_interests": extraction_result.get('additional_interests', []),
            "policy_data_source": extraction_result.get('policy_data_source'),
            "extraction_extras": build_extraction_extras_json(extraction_result),
        }

    def _create_policy_instance(self, extraction_result):
        """Helper to create a transient Policy object from data."""
        normalized = self.normalize_policy_data(extraction_result)
        
        flat_data = normalized['policy'].copy()
        flat_data['vehicles'] = normalized['vehicles']
        flat_data['coverages'] = normalized['coverages']
        flat_data['drivers'] = normalized['drivers']
        flat_data['additional_interests'] = normalized['additional_interests']
        if normalized.get("policy_data_source"):
            flat_data["policy_data_source"] = normalized["policy_data_source"]
        if normalized.get("extraction_extras"):
            flat_data["extraction_extras"] = normalized["extraction_extras"]
        
        return self.create_policy_from_dict(flat_data)

    def save_policy_from_extraction(self, extraction_result):
        if extraction_result.get("policy_data_source") == "coi_summary" and extraction_result.get("coi_summary", {}).get("policies"):
            return self._save_policies_from_coi_summary(extraction_result)
        return self._save_single_extraction_payload(extraction_result)

    @classmethod
    def compute_completeness_score(cls, policy_data, document_type):
        payload = policy_data if isinstance(policy_data, dict) else {}

        def _is_missing(field_name: str) -> bool:
            value = payload.get(field_name)
            clean = cls._clean_text(value)
            return clean in (None, "")

        missing_required = [field for field in cls.REQUIRED_FOR_COI if _is_missing(field)]
        missing_recommended = [field for field in cls.RECOMMENDED_FOR_COI if _is_missing(field)]
        raw_score = 100 - (20 * len(missing_required)) - (5 * len(missing_recommended))
        score = max(0, raw_score)
        return {
            "score": score,
            "coi_ready": len(missing_required) == 0,
            "missing_required": missing_required,
            "missing_recommended": missing_recommended,
            "document_type": document_type,
        }

    def _save_policies_from_coi_summary(self, extraction_result):
        summary = extraction_result.get("coi_summary") or {}
        policies = summary.get("policies") or []
        saved_count = 0
        updated_count = 0
        skipped_count = 0

        grouped: dict[str, list[dict]] = {}
        for row in policies:
            if not isinstance(row, dict):
                continue
            policy_number = self._clean_text(row.get("policy_number"))
            if not policy_number:
                skipped_count += 1
                continue
            grouped.setdefault(policy_number, []).append(row)

        for policy_number, rows in grouped.items():
            merged_row = self._merge_coi_policy_rows(rows)
            limits = merged_row.get("limits") if isinstance(merged_row.get("limits"), dict) else {}

            policy_payload = {
                "policy": {
                    "carrier_name": merged_row.get("carrier_name"),
                    "carrier_name_confidence": merged_row.get("carrier_name_confidence"),
                    "naic_number": merged_row.get("naic_number"),
                    "policy_number": policy_number,
                    "policy_number_confidence": merged_row.get("policy_number_confidence"),
                    "effective_date": merged_row.get("effective_date"),
                    "effective_date_confidence": merged_row.get("effective_date_confidence"),
                    "expiration_date": merged_row.get("expiration_date"),
                    "expiration_date_confidence": merged_row.get("expiration_date_confidence"),
                    "insured_name": self._clean_text(merged_row.get("insured_name")) or self._clean_text((summary.get("insured") or {}).get("name")),
                    "insured_name_confidence": merged_row.get("insured_name_confidence"),
                    "insured_address": self._clean_text((summary.get("insured") or {}).get("address")),
                    "premium": self._clean_text(merged_row.get("premium")),
                    "premium_confidence": merged_row.get("premium_confidence"),
                    "financial_responsibility_name": self._clean_text((summary.get("producer") or {}).get("name")),
                    "liability_limit": self._clean_limit_text(limits.get("liability_limit")),
                    "liability_limit_confidence": self._clean_text(limits.get("liability_limit_confidence")),
                    "general_liability_limit": self._clean_limit_text(limits.get("general_liability_limit")),
                    "cargo_limit": self._clean_limit_text(limits.get("cargo_limit")),
                    "cargo_limit_confidence": self._clean_text(limits.get("cargo_limit_confidence")),
                    "cargo_deductible": self._clean_limit_text(limits.get("cargo_deductible")),
                    "um_uim_limit": self._clean_limit_text(limits.get("um_uim_limit")),
                    "med_pay_limit": self._clean_limit_text(limits.get("med_pay_limit")),
                    "pip_limit": self._clean_limit_text(limits.get("pip_limit")),
                    "comp_deductible": self._clean_limit_text(limits.get("comp_deductible")),
                    "coll_deductible": self._clean_limit_text(limits.get("coll_deductible")),
                    "policy_type": merged_row.get("policy_type") or extraction_result.get("classification", {}).get("policy_type") or "unknown",
                    "document_type": extraction_result.get("classification", {}).get("document_type"),
                    "classification_confidence": extraction_result.get("classification", {}).get("confidence"),
                    "classification_signals": extraction_result.get("classification", {}).get("signals", []),
                },
                "vehicles": extraction_result.get("vehicles", []),
                "drivers": extraction_result.get("drivers", []),
                "coverages": extraction_result.get("coverages", []),
                "additional_interests": extraction_result.get("additional_interests", []),
                "policy_data_source": "coi_summary",
                "compliance": extraction_result.get("compliance") or {},
                "coi_summary": {**summary, "merged_row_count": len(rows)},
            }
            success, msg = self._save_single_extraction_payload(policy_payload)
            if success and msg.startswith("Updated"):
                updated_count += 1
            elif success:
                saved_count += 1
            else:
                skipped_count += 1

        if saved_count == 0 and updated_count == 0:
            return False, f"COI summary save skipped. {skipped_count} entries skipped."
        return True, (
            f"COI summary processed: {saved_count} new, {updated_count} updated, {skipped_count} skipped."
        )

    def save_policy_object(self, policy: Policy):
        existing = self.get_policy_by_number(policy.policy_number)
        if existing:
            return False, "Skipped duplicate policy number."
        
        self.session.add(policy)
        self.session.commit()
        return True, "Saved policy manually."

    def update_policy(self, policy: Policy, updated_data: dict):
        """
        Updates an existing policy.
        If 'policy' key is present in updated_data, assumes full payload structure.
        Otherwise, assumes updated_data is just scalar policy fields (legacy behavior).
        """
        from .history_service import HistoryService
        history_svc = HistoryService(self.session)
        
        if any(k in updated_data for k in ("policy", "vehicles", "drivers", "coverages", "additional_interests")):
             final_payload = updated_data
        else:
             final_payload = {"policy": updated_data}
        
        is_changed, changes, collection_changes = history_svc.compare_and_record(policy, final_payload, source="Manual_Edit", event_type="MANUAL_EDIT")
        
        if is_changed:
            if collection_changes.get("vehicles"):
                new_vehs = final_payload.get('vehicles', [])
                policy.vehicles.clear()
                for v in new_vehs:
                    policy.vehicles.append(Vehicle(
                        year=v.get('year'), make=v.get('make'), model=v.get('model'), 
                        vin=v.get('vin'), gvw=v.get('gvw'), vehicle_type=v.get('type') or v.get('vehicle_type'),
                        chassis=v.get('chassis'), body=v.get('body')
                    ))
            
            if collection_changes.get("drivers"):
                new_drvs = final_payload.get('drivers', [])
                policy.drivers.clear()
                for d in new_drvs:
                    policy.drivers.append(Driver(
                        full_name=d.get('full_name'), license_number=d.get('license_number'), 
                        is_excluded=d.get('is_excluded')
                    ))
                    
            if collection_changes.get("additional_interests"):
                new_ais = final_payload.get('additional_interests', [])
                from .database import AdditionalInterest
                policy.additional_interests.clear()
                for a in new_ais:
                    policy.additional_interests.append(AdditionalInterest(
                        name=a.get('name'), address=a.get('address'), interest_type=a.get('interest_type')
                    ))

            self.session.commit()
            return True, f"Updated ({len(changes)} changes logged)."
        else:
            return True, "No changes detected."

    def create_policy_from_dict(self, data: dict) -> Policy:
        """
        Factory method to create a Policy object from a dictionary.
        Handles creating nested objects (Vehicles, Drivers, Coverages, AIs).
        Centralizes data parsing logic.
        """
        effective_dt = pd.to_datetime(data.get('effective_date'), errors='coerce')
        expiration_dt = pd.to_datetime(data.get('expiration_date'), errors='coerce')
        
        # Ensure 'status' defaults to Active if missing
        status_val = data.get('status', 'Active')

        # Handle classification signals (might be list or json string already)
        signals = data.get('classification_signals', [])
        if isinstance(signals, list):
            signals_json = json.dumps(signals)
        else:
            signals_json = signals # Assume string or None
            
        policy = Policy(
            carrier_name=data.get('carrier_name'),
            naic_number=data.get('naic_number'),
            policy_number=data.get('policy_number'),
            effective_date=effective_dt.date() if pd.notnull(effective_dt) else None,
            expiration_date=expiration_dt.date() if pd.notnull(expiration_dt) else None,
            
            insured_name=data.get('insured_name'),
            business_name=data.get('business_name'),
            insured_address=data.get('insured_address'),
            insured_city=data.get('insured_city'),
            insured_state_code=data.get('insured_state_code'),
            insured_zip=data.get('insured_zip'),
            
            premium=data.get('premium'),
            state=data.get('state'),
            financial_responsibility_name=data.get('financial_responsibility_name'),
            
            account_type=data.get('account_type'),
            document_type=data.get('document_type'),
            policy_data_source=data.get('policy_data_source'),
            field_confidences=data.get('field_confidences'),
            premium_audit_flag=data.get('premium_audit_flag'),
            policy_type=data.get('policy_type'),
            classification_confidence=data.get('classification_confidence'),
            classification_signals=signals_json,
            status=status_val,
            
            liability_limit=data.get('liability_limit'),
            general_liability_limit=data.get('general_liability_limit'),
            cargo_limit=data.get('cargo_limit'),
            cargo_deductible=data.get('cargo_deductible'),
            um_uim_limit=data.get('um_uim_limit'),
            med_pay_limit=data.get('med_pay_limit'),
            pip_limit=data.get('pip_limit'),
            comp_deductible=data.get('comp_deductible'),
            coll_deductible=data.get('coll_deductible'),
            
            has_full_collision=data.get('has_full_collision'),
            has_general_liability=data.get('has_general_liability', False),
            has_auto_liability=data.get('has_auto_liability', False),
            extraction_extras=data.get('extraction_extras'),
        )
        
        vehs = data.get('vehicles', [])
        # Support both list of dicts and list of model objects.
        for v in vehs:
            if isinstance(v, dict):
                if not v.get('vin') and not v.get('make'): continue # Skip empty
                
                ref_type = v.get('vehicle_type')
                if not ref_type:
                     refinement = refine_vehicle_type(v.get('year'), v.get('make'), v.get('model'), v.get('vin'), v.get('type'), gvw=v.get('gvw'))
                     ref_type = refinement.get('final_type')
                
                policy.vehicles.append(Vehicle(
                    year=v.get('year'),
                    make=v.get('make'),
                    model=v.get('model'),
                    vin=v.get('vin'),
                    gvw=v.get('gvw'),
                    vehicle_type=v.get('type'),
                    chassis=v.get('chassis'),
                    body=v.get('body')
                ))
            elif isinstance(v, Vehicle):
                policy.vehicles.append(v) # Allow passing objects directly

        drvs = data.get('drivers', [])
        for d in drvs:
            if isinstance(d, dict):
                if not d.get('full_name'): continue
                policy.drivers.append(Driver(
                    full_name=d.get('full_name'),
                    license_number=d.get('license_number'),
                    is_excluded=d.get('is_excluded', False)
                ))
            elif isinstance(d, Driver):
                policy.drivers.append(d)

        def _norm_vin(v):
            if not v:
                return None
            return str(v).strip().upper()

        vin_to_vehicle = {}
        for veh in policy.vehicles:
            nv = _norm_vin(getattr(veh, "vin", None))
            if nv:
                vin_to_vehicle[nv] = veh

        covs = data.get('coverages', [])
        for c in covs:
            if isinstance(c, dict):
                # Handle flattened editor payloads or nested extraction payloads.
                per_person = c.get('per_person') or c.get('limits', {}).get('per_person')
                per_accident = c.get('per_accident') or c.get('limits', {}).get('per_accident')
                per_occ = c.get('per_occurrence') or c.get('limits', {}).get('per_occurrence')
                csl = c.get('combined_single_limit') or c.get('limits', {}).get('combined_single_limit')
                agg = c.get('aggregate') or c.get('limits', {}).get('aggregate')

                matched_vehicle = None
                vv = c.get('vehicle_vin')
                if vv:
                    matched_vehicle = vin_to_vehicle.get(_norm_vin(vv))

                policy.coverages.append(
                    Coverage(
                        type=c.get('type') or c.get('display_name'),
                        coverage_code=c.get('coverage_code'),
                        family=c.get('family'),
                        per_person=per_person,
                        per_accident=per_accident,
                        per_occurrence=per_occ,
                        combined_single_limit=csl,
                        aggregate=agg,
                        deductible=c.get('deductible'),
                        limit_per_person=c.get('limit_per_person'),
                        limit_per_accident=c.get('limit_per_accident'),
                        limit_property_damage=c.get('limit_property_damage'),
                        vehicle=matched_vehicle,
                    )
                )
            elif isinstance(c, Coverage):
                policy.coverages.append(c)

        ais = data.get('additional_interests', [])
        for a in ais:
              if isinstance(a, dict):
                  if not a.get('name'): continue
                  from .database import AdditionalInterest
                  policy.additional_interests.append(AdditionalInterest(
                      name=a.get('name'),
                      address=a.get('address'),
                      interest_type=a.get('interest_type')
                  ))
              elif isinstance(a, AdditionalInterest):
                  policy.additional_interests.append(a)

        return policy

    def ask_your_data(self, user_query, api_key):
        """
        Uses Gemini to translate natural language into SQL, then executes it.
        """
        from google import genai
        from google.genai import types
        from sqlalchemy import text
        
        if not api_key:
            return None, "API Key missing."
            
        client = genai.Client(api_key=api_key)
        
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash', 
                # Keep prefix stable to maximize implicit cache hits.
                contents=[
                    SQL_SCHEMA_CONTEXT,
                    f"User Question: {user_query}\nSQL:",
                ],
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
            )
            usage_md = getattr(response, "usage_metadata", None)
            if usage_md:
                UsageService(self.session).log_usage(
                    model_name="gemini-2.5-flash",
                    input_tokens=usage_md.prompt_token_count or 0,
                    output_tokens=usage_md.candidates_token_count or 0,
                    request_type="query_sql",
                )
            generated_sql = response.text.strip()
            
            generated_sql = generated_sql.replace("```sql", "").replace("```", "").strip()
            if generated_sql.endswith(";"):
                generated_sql = generated_sql[:-1].strip()
            
            if not generated_sql.lower().startswith("select"):
                return None, f"Safety Error: Only SELECT queries are allowed. Generated: {generated_sql}"
            if ";" in generated_sql:
                return None, f"Safety Error: Multiple statements (;) are not allowed. Generated: {generated_sql}"
            
            result = self.session.execute(text(generated_sql))
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            
            return rows, generated_sql
            
        except Exception as e:
            return None, f"Error: {e}"
class COIService:
    @staticmethod
    def prepare_coi_data(p: Policy):
        from reporting.acord_view import build_acord_view_from_orm_policy

        cargo_ded_val = p.cargo_deductible if p.cargo_deductible else "1000"
        
        has_gl = p.has_general_liability if p.has_general_liability is not None else True
        has_auto = p.has_auto_liability if p.has_auto_liability is not None else True
        
        current_naic = p.naic_number if p.naic_number else get_naic_for_carrier(p.carrier_name)
        
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
        
        desc_lines = []
        if p.vehicles:
            v_str = " ".join([f"[{v.year} {v.make} {v.vin}]" for v in p.vehicles])
            desc_lines.append(f"Vehicle List: {v_str}")
            p_data["vehicle_list_str"] = v_str
        if p.drivers:
            d_str = ", ".join([d.full_name for d in p.drivers])
            desc_lines.append(f"Driver List: {d_str}")
            p_data["driver_list_str"] = d_str

        av = build_acord_view_from_orm_policy(p)
        comp = av.get("compliance") or {}
        if comp.get("mcs90"):
            desc_lines.append(f"MCS-90: {comp.get('mcs90')}")
        if comp.get("motor_carrier_id"):
            desc_lines.append(f"MC # / motor carrier: {comp.get('motor_carrier_id')}")
        if comp.get("dot"):
            desc_lines.append(f"USDOT: {comp.get('dot')}")
        for de in (comp.get("doc_endorsements") or []):
            if not isinstance(de, dict):
                continue
            fid = (de.get("form_id") or "").strip()
            nms = de.get("named_individuals") or []
            nms_s = ", ".join(str(x) for x in nms) if nms else ""
            if fid or nms_s:
                desc_lines.append(
                    f"Drive Other Car / DOC: {fid or '—'}"
                    + (f" — named: {nms_s}" if nms_s else "")
                )
        st_disp = (av.get("policy_ontology") or {}).get("statutory_auto_liability_display")
        if st_disp:
            desc_lines.append(f"State minimum (reference): {st_disp}")
        for vrow in av.get("acord_127_vehicles") or []:
            sym = vrow.get("covered_auto_symbols")
            if sym:
                vlabel = vrow.get("vin") or "vehicle"
                desc_lines.append(f"BAP symbols ({vlabel}): {sym}")
        auto25 = av.get("acord_25_automobile_liability") or {}
        if auto25.get("um_stacked_effective"):
            desc_lines.append(f"UM stacked (effective): {auto25.get('um_stacked_effective')}")
        cbf = av.get("coverages_by_family") or {}
        hnoa_seen: set[str] = set()
        for rows in cbf.values():
            for r in rows or []:
                hb = r.get("hnoa_basis")
                ha = r.get("hnoa_attached_to")
                if not (hb or ha):
                    continue
                cc = r.get("coverage_code") or "coverage"
                sig = f"{cc}|{hb}|{ha}"
                if sig in hnoa_seen:
                    continue
                hnoa_seen.add(sig)
                msg = f"Hired/Non-Owned ({cc}): {hb or '—'}"
                if ha:
                    msg += f" (attached: {ha})"
                desc_lines.append(msg)
            
        return p_data, desc_lines


class UsageService:
    PRICING = {
        "gemini-2.5-flash": {"input": 0.10 / 1_000_000, "output": 0.40 / 1_000_000},
        "gemini-2.0-flash": {"input": 0.10 / 1_000_000, "output": 0.40 / 1_000_000},
        "gemini-1.5-flash": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
        "default": {"input": 0.10 / 1_000_000, "output": 0.40 / 1_000_000}
    }

    def __init__(self, session: Session):
        self.session = session

    def log_usage(self, model_name: str, input_tokens: int, output_tokens: int, request_type: str = "extraction"):
        """Logs a single API request's token usage and estimated cost."""
        pricing = self.PRICING.get(model_name, self.PRICING["default"])
        cost = (input_tokens * pricing["input"]) + (output_tokens * pricing["output"])
        
        usage = ApiUsage(
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            status="success",
            request_type=request_type,
            timestamp=datetime.utcnow()
        )
        self.session.add(usage)
        self.session.commit()
        return usage

    def get_daily_usage(self):
        """Returns the total cost for the current day."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        total_cost = self.session.query(func.sum(ApiUsage.cost)).filter(
            ApiUsage.timestamp >= today_start
        ).scalar() or 0.0
        return total_cost

    def is_over_budget(self, daily_limit: float = 1.0):
        """Checks if the daily spend has exceeded the limit."""
        return self.get_daily_usage() >= daily_limit

    def clear_usage(self):
        """Deletes all usage logs."""
        try:
            self.session.query(ApiUsage).delete()
            self.session.commit()
            return True, "Usage logs cleared."
        except Exception as e:
            self.session.rollback()
            return False, str(e)

    def get_recent_usage(self, limit: int = 10):
        """Returns the most recent API calls."""
        return self.session.query(ApiUsage).order_by(ApiUsage.timestamp.desc()).limit(limit).all()

    def get_todays_token_stats(self):
        """Returns tuple (total_input, total_output) for today."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        result = self.session.query(
            func.sum(ApiUsage.input_tokens),
            func.sum(ApiUsage.output_tokens)
        ).filter(ApiUsage.timestamp >= today_start).first()
        
        return (result[0] or 0, result[1] or 0)


