import pandas as pd
import io

def create_excel_report(policies_data):
    """
    Converts a list of policy dictionaries (including nested vehicles, coverages, drivers)
    into a multi-tab Excel file.
    
    Args:
        policies_data: List of dictionaries, each containing 'policy', 'vehicles', 'coverages', 'drivers'.
            Note: This input structure should match the Extractor's output format, assuming we combine them
            or query the DB to get this structure. 
            However, for the exporter, it's easier to process flat lists.
            Strategy: We will flatten the data into 4 lists: policies, vehicles, all_coverages, all_drivers.
    """
    
    policies_list = []
    vehicles_list = []
    coverages_list = []
    drivers_list = []
    
    for entry in policies_data:
        # Entry structure depends on how we pass it. 
        # Ideally, we pass the raw extracted JSONs or DB Objects converted to dicts.
        # Let's assume input is a list of the structure returned by the extractor 
        # BUT with an added 'id' or consistent link if possible. 
        # If input is form DB objects, we need to convert.
        # Let's assume the input is the list of DB objects for robustness, 
        # or we make this robust to handle the JSON structure with an arbitrary ID if needed.
        
        # To make it simple and decoupled from DB session state, let's assume input is dictionaries
        # matching the schema, where children have a 'policy_number' to link back 
        # (or we add it during flattening).
        
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
            
    # Define standard column sets
    POLICY_COLUMNS = [
        "carrier_name", "policy_number", "effective_date", "expiration_date",
        "account_type", "insured_name", "business_name", "premium", "state",
        "financial_responsibility_name", "liability_limit", "cargo_limit", "has_full_collision"
    ]
    VEHICLE_COLUMNS = ["year", "make", "model", "vin", "gvw", "type", "policy_number"]
    COVERAGE_COLUMNS = ["type", "limit_person", "limit_accident", "deductible", "policy_number"]
    DRIVER_COLUMNS = ["full_name", "license_number", "is_excluded", "policy_number"]

    # Create DataFrames and ensure column consistency
    df_policy = pd.DataFrame(policies_list).reindex(columns=POLICY_COLUMNS)
    df_vehicles = pd.DataFrame(vehicles_list).reindex(columns=VEHICLE_COLUMNS)
    df_coverages = pd.DataFrame(coverages_list).reindex(columns=COVERAGE_COLUMNS)
    df_drivers = pd.DataFrame(drivers_list).reindex(columns=DRIVER_COLUMNS)
    
    # Write to Excel in memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_policy.to_excel(writer, sheet_name='Summary', index=False)
        df_vehicles.to_excel(writer, sheet_name='Vehicles', index=False)
        df_coverages.to_excel(writer, sheet_name='Coverages', index=False)
        df_drivers.to_excel(writer, sheet_name='Drivers', index=False)
        
    return output.getvalue()
