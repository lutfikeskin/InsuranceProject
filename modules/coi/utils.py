import pandas as pd
import re

def load_companies(filepath):
    """
    Loads company data from Excel and parses address fields.
    Returns a dictionary keyed by Company Name.
    """
    try:
        df = pd.read_excel(filepath)
    except Exception as e:
        print(f"Error loading Excel: {e}")
        return {}
    
    df.columns = [str(c).strip() for c in df.columns]
    
    partners_col = None
    for col in df.columns:
        if 'PARTNERS' in col.upper():
            partners_col = col
            break
            
    if not partners_col:
        print("Could not find PARTNERS column")
        return {}

    companies = {}
    
    for _, row in df.iterrows():
        name = str(row.get('COMP NAME', '')).strip()
        raw_address = str(row.get(partners_col, '')).strip()
        
        if not name or name.lower() == 'nan':
            continue
            
        addr_parts = {
            "name": name,
            "address": raw_address,
            "city": "",
            "state": "",
            "zip": ""
        }
        
        if raw_address and raw_address.lower() != 'nan':
            lines = [l.strip() for l in raw_address.split('\n') if l.strip()]
            
            if len(lines) >= 1:
                addr_parts["address"] = lines[0]
                
            if len(lines) >= 2:
                city_line = lines[1]
                
                if ',' in city_line:
                    city_part, state_zip_part = city_line.split(',', 1)
                    addr_parts["city"] = city_part.strip()
                    
                    state_zip_part = state_zip_part.strip()
                    parts = state_zip_part.split()
                    if len(parts) >= 2:
                        addr_parts["zip"] = parts[-1]
                        addr_parts["state"] = " ".join(parts[:-1])
                    elif len(parts) == 1:
                         addr_parts["state"] = parts[0]
                else:
                    addr_parts["city"] = city_line
        
        companies[name] = addr_parts
        
    return companies
