from sqlalchemy.orm import Session
from .database import get_session, Policy, Vehicle, Driver, Coverage, ApiUsage
from datetime import datetime, timedelta
from sqlalchemy import func
from utils.naic_utils import get_naic_for_carrier
from .coverage_ontology import summarize_auto_liability, format_liability_limit
from utils.vehicle_utils import refine_vehicle_type
import pandas as pd
import json

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
        
        # Group by month
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
        
        # Determine account type based on classification
        account_type = ACCOUNT_TYPE_BY_POLICY.get(policy_type, "Commercial")
        policy_data['account_type'] = account_type
        
        # Add classification metadata
        policy_data['policy_type'] = policy_type
        policy_data['classification_confidence'] = classification.get('confidence')
        policy_data['classification_signals'] = json.dumps(classification.get('signals', []))
        
        return {
            "policy": policy_data,
            "vehicles": extraction_result.get('vehicles', []),
            "coverages": extraction_result.get('coverages', []),
            "drivers": extraction_result.get('drivers', []),
            "additional_interests": extraction_result.get('additional_interests', [])
        }

    def _create_policy_instance(self, extraction_result):
        """Helper to create a transient Policy object from data."""
        normalized = self.normalize_policy_data(extraction_result)
        
        # Flatten the normalized structure for the factory method
        # normalized['policy'] contains scalar fields
        # other keys are lists
        
        flat_data = normalized['policy'].copy()
        flat_data['vehicles'] = normalized['vehicles']
        flat_data['coverages'] = normalized['coverages']
        flat_data['drivers'] = normalized['drivers']
        flat_data['additional_interests'] = normalized['additional_interests']
        
        return self.create_policy_from_dict(flat_data)

    def save_policy_from_extraction(self, extraction_result):
        # 1. Create Transient Policy Object
        new_policy = self._create_policy_instance(extraction_result)
        
        # 2. Check for Existing
        existing = self.get_policy_by_number(new_policy.policy_number)
        
        if existing:
            # UPDATE LOGIC WITH HISTORY
            from .history_service import HistoryService
            history_svc = HistoryService(self.session)
            
            # Use strict diff
            # I will USE THE HELPERS I WROTE: compare_and_record(existing, normalized_dict)
            
            normalized = self.normalize_policy_data(extraction_result)
            is_changed, changes, collection_changes = history_svc.compare_and_record(existing, normalized, source="AI_Re-Extraction", event_type="AI_EXTRACTION")
            
            if is_changed:
                # IMPORTANT: scalar fields were updated by compare_and_record.
                
                # Update Collections Atomically if needed
                if collection_changes["vehicles"]:
                    existing.vehicles.clear()
                    for v in new_policy.vehicles:
                         # Append Copy (Re-creating objects to ensure no session conflict)
                         existing.vehicles.append(Vehicle(
                                year=v.year, make=v.make, model=v.model, vin=v.vin,
                                gvw=v.gvw, vehicle_type=v.vehicle_type, chassis=v.chassis, body=v.body
                         ))

                if collection_changes["coverages"]:
                    existing.coverages.clear()
                    for c in new_policy.coverages:
                        existing.coverages.append(Coverage(
                            type=c.type, coverage_code=c.coverage_code, family=c.family,
                            per_person=c.per_person, per_accident=c.per_accident, per_occurrence=c.per_occurrence,
                            combined_single_limit=c.combined_single_limit, aggregate=c.aggregate,
                            limit_per_person=c.limit_per_person, limit_per_accident=c.limit_per_accident,
                            limit_property_damage=c.limit_property_damage, deductible=c.deductible
                        ))

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
            else:
                 return False, "No changes detected."

        else:
            self.session.add(new_policy)
            self.session.commit()
            return True, "Saved successfully"

    def save_policy_object(self, policy: Policy):
        # Used when constructing object manually in review
        # Check duplicate
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
        
        # Determine payload structure
        if "policy" in updated_data or "vehicles" in updated_data or "drivers" in updated_data:
             # It is already a structured payload
             final_payload = updated_data
        else:
             # Legacy: Wrap scalar fields
             final_payload = {"policy": updated_data}
        
        is_changed, changes, collection_changes = history_svc.compare_and_record(policy, final_payload, source="Manual_Edit", event_type="MANUAL_EDIT")
        
        if is_changed:
            # Apply Collection Updates if flagged
            if collection_changes.get("vehicles"):
                new_vehs = final_payload.get('vehicles', [])
                policy.vehicles.clear()
                for v in new_vehs:
                    # Reconstruct Vehicle objects
                    # v is a dict here
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
        # 1. Parse Dates safely
        effective_dt = pd.to_datetime(data.get('effective_date'), errors='coerce')
        expiration_dt = pd.to_datetime(data.get('expiration_date'), errors='coerce')
        
        # 2. Create Base Policy
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
            
            # Account / Type
            account_type=data.get('account_type'),
            policy_type=data.get('policy_type'),
            classification_confidence=data.get('classification_confidence'),
            classification_signals=signals_json,
            status=status_val,
            
            # Limits (Scalar)
            liability_limit=data.get('liability_limit'),
            general_liability_limit=data.get('general_liability_limit'),
            cargo_limit=data.get('cargo_limit'),
            cargo_deductible=data.get('cargo_deductible'),
            um_uim_limit=data.get('um_uim_limit'),
            med_pay_limit=data.get('med_pay_limit'),
            pip_limit=data.get('pip_limit'),
            comp_deductible=data.get('comp_deductible'),
            coll_deductible=data.get('coll_deductible'),
            
            # Flags
            has_full_collision=data.get('has_full_collision'),
            has_general_liability=data.get('has_general_liability', False),
            has_auto_liability=data.get('has_auto_liability', False)
        )
        
        # 3. Add Nested Collections
        
        # Vehicles
        vehs = data.get('vehicles', [])
        # Support both list of dicts or list of objects (if reusing internal logic)
        for v in vehs:
            if isinstance(v, dict):
                # Check for required Minimums to avoid empty rows
                if not v.get('vin') and not v.get('make'): continue # Skip empty
                
                # Apply Refinement if not already present
                ref_type = v.get('vehicle_type')
                if not ref_type:
                     refinement = refine_vehicle_type(v.get('year'), v.get('make'), v.get('model'), v.get('vin'), v.get('type'), gvw=v.get('gvw'))
                     ref_type = refinement.get('final_type')
                     # Could also refine chassis/body if missing
                
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

        # Drivers
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

        # Coverages
        covs = data.get('coverages', [])
        for c in covs:
            if isinstance(c, dict):
                # Handle flattened structure (from Editor) or nested limits (from Extraction)
                
                # Try flattened first (Editor style)
                per_person = c.get('per_person') or c.get('limits', {}).get('per_person')
                per_accident = c.get('per_accident') or c.get('limits', {}).get('per_accident')
                per_occ = c.get('per_occurrence') or c.get('limits', {}).get('per_occurrence')
                csl = c.get('combined_single_limit') or c.get('limits', {}).get('combined_single_limit')
                agg = c.get('aggregate') or c.get('limits', {}).get('aggregate')
                
                policy.coverages.append(Coverage(
                    type=c.get('type') or c.get('display_name'),
                    coverage_code=c.get('coverage_code'),
                    family=c.get('family'),
                    per_person=per_person,
                    per_accident=per_accident,
                    per_occurrence=per_occ,
                    combined_single_limit=csl,
                    aggregate=agg,
                    deductible=c.get('deductible'),
                    # Legacy fields mapping
                    limit_per_person=c.get('limit_per_person'),
                    limit_per_accident=c.get('limit_per_accident'),
                    limit_property_damage=c.get('limit_property_damage')
                ))
            elif isinstance(c, Coverage):
                policy.coverages.append(c)

        # Additional Interests
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
        
        # 1. Define Schema Context
        # We simplify the schema description for the AI to minimize token usage
        schema_context = """
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
        3. Handle currency strings in 'liability_limit' or 'premium' by stripping '$' and ',' if mathematical comparison is needed (e.g. CAST(REPLACE(REPLACE(premium, '$', ''), ',', '') AS FLOAT)).
        4. If asking for specific coverages like "Comp/Coll", check 'has_full_collision' or join with coverages table if needed (but currently simplified to boolean flags on policy).
        """
        
        try:
            # 2. Generate SQL
            response = client.models.generate_content(
                model='gemini-2.5-flash', 
                contents=f"{schema_context}\n\nUser Question: {user_query}\nSQL:",
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
            )
            generated_sql = response.text.strip()
            
            # Clean up markdown and trailing semicolon
            generated_sql = generated_sql.replace("```sql", "").replace("```", "").strip()
            if generated_sql.endswith(";"):
                generated_sql = generated_sql[:-1].strip()
            
            # Safety: Basic check to prevent destructive queries
            if not generated_sql.lower().startswith("select"):
                return None, f"Safety Error: Only SELECT queries are allowed. Generated: {generated_sql}"
            if ";" in generated_sql:
                return None, f"Safety Error: Multiple statements (;) are not allowed. Generated: {generated_sql}"
            
            # 3. Execute
            # Use session.execute to keep the connection alive for the rest of the request
            result = self.session.execute(text(generated_sql))
            # Convert to list of dicts
            columns = result.keys()
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
            
            return rows, generated_sql
            
        except Exception as e:
            return None, f"Error: {e}"
class COIService:
    @staticmethod
    def prepare_coi_data(p: Policy):
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
        
        # Descriptions logic
        desc_lines = []
        if p.vehicles:
            v_str = " ".join([f"[{v.year} {v.make} {v.vin}]" for v in p.vehicles])
            desc_lines.append(f"Vehicle List: {v_str}")
        if p.drivers:
            d_str = ", ".join([d.full_name for d in p.drivers])
            desc_lines.append(f"Driver List: {d_str}")
            
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


