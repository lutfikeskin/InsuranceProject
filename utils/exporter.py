import pandas as pd
import io

def create_excel_report(policies_data):
    """
    Converts a list of policy dictionaries (including nested vehicles, coverages, drivers)
    into a multi-tab Excel file.
    
    Args:
        policies_data: List of policy dictionaries containing 'policy', 'vehicles', 'coverages', and 'drivers'.
    """
    
    policies_list = []
    vehicles_list = []
    coverages_list = []
    drivers_list = []
    
    for entry in policies_data:
        p = entry.get('policy', {})
        policy_num = p.get('policy_number', 'UNKNOWN')
        
        policies_list.append(p)
        
        for v in entry.get('vehicles', []):
            v_copy = v.copy()
            v_copy['policy_number'] = policy_num
            vehicles_list.append(v_copy)
            
        for c in entry.get('coverages', []):
            c_copy = c.copy()
            c_copy['policy_number'] = policy_num
            coverages_list.append(c_copy)
            
        for d in entry.get('drivers', []):
            d_copy = d.copy()
            d_copy['policy_number'] = policy_num
            drivers_list.append(d_copy)
            
    POLICY_COLUMNS = [
        "carrier_name", "naic_number", "policy_number", "effective_date", "expiration_date",
        "account_type", "policy_type", "classification_confidence", "classification_signals", 
        "insured_name", "business_name", "insured_address", "insured_city", "insured_state_code", "insured_zip",
        "premium", "state", "financial_responsibility_name", 
        "liability_limit", "general_liability_limit", "cargo_limit", "cargo_deductible", 
        "has_full_collision", "has_general_liability", "has_auto_liability"
    ]
    VEHICLE_COLUMNS = ["year", "make", "model", "vin", "gvw", "type", "chassis", "body", "policy_number"]
    COVERAGE_COLUMNS = [
        "policy_number", "type", "coverage_code", "family", 
        "per_person", "per_accident", "per_occurrence", 
        "combined_single_limit", "aggregate", "deductible"
    ]
    DRIVER_COLUMNS = ["full_name", "license_number", "is_excluded", "policy_number"]

    df_policy = pd.DataFrame(policies_list).reindex(columns=POLICY_COLUMNS)
    df_vehicles = pd.DataFrame(vehicles_list).reindex(columns=VEHICLE_COLUMNS)
    df_coverages = pd.DataFrame(coverages_list).reindex(columns=COVERAGE_COLUMNS)
    df_drivers = pd.DataFrame(drivers_list).reindex(columns=DRIVER_COLUMNS)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_policy.to_excel(writer, sheet_name='Summary', index=False)
        df_vehicles.to_excel(writer, sheet_name='Vehicles', index=False)
        df_coverages.to_excel(writer, sheet_name='Coverages', index=False)
        df_drivers.to_excel(writer, sheet_name='Drivers', index=False)
        
    return output.getvalue()
