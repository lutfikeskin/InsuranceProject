import re
import requests

# Comprehensive WMI Map (World Manufacturer Identifier)
WMI_MAP = {
    "1FT": "Ford", "1FD": "Ford", "2FT": "Ford", "3FT": "Ford", "1F0": "Ford", "1FM": "Ford",
    "1GT": "GMC", "1GD": "GMC", 
    "1GC": "Chevrolet", "1GB": "Chevrolet",
    "1HT": "International", 
    "1M1": "Mack", "1M2": "Mack", "1M3": "Mack", "1M4": "Mack",
    "1NP": "Peterbilt", "2NP": "Peterbilt",
    "1NK": "Kenworth", "2NK": "Kenworth",
    "1XK": "Kenworth",
    "1XP": "Peterbilt", 
    "2WK": "Western Star", 
    "3AL": "Freightliner", "1FV": "Freightliner", "1FU": "Freightliner", "2FV": "Freightliner", "2FU": "Freightliner",
    "3WK": "Kenworth",
    "3XP": "Peterbilt",
    "4V1": "Volvo", "4V2": "Volvo", "4V4": "Volvo", "4V5": "Volvo",
    "5PV": "Hino", "JNK": "Hino", "JH4": "Hino",
    "JA3": "Mitsubishi Fuso", "JL5": "Mitsubishi Fuso",
    "JAL": "Isuzu", "JAA": "Isuzu", "4KL": "Isuzu", # NPR often 4KL
}

def decode_vin_nhtsa(vin):
    """
    Decodes VIN using the public NHTSA vPIC API.
    Returns a dict with raw NHTSA data or None if failed.
    """
    if not vin or len(vin) < 17:
        return None
        
    try:
        url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVin/{vin}?format=json"
        resp = requests.get(url, timeout=3) # Fast timeout to avoid blocking
        
        if resp.status_code == 200:
            data = resp.json()
            results = data.get('Results', [])
            
            # Convert list of ValueIds/Variables to a flat dict
            info = {}
            for item in results:
                var_name = item.get('Variable')
                value = item.get('Value')
                if var_name and value:
                    info[var_name] = value
            return info
            
    except Exception as e:
        print(f"NHTSA API Error: {e}")
        return None
        
    return None

def refine_vehicle_type(year, make, model, vin, extracted_type=None):
    """
    Refines the vehicle type based on a two-layer Chassis + Body model.
    Prioritizes NHTSA values if available, falls back to Regex.
    """
    year_str = str(year) if year else ""
    make = str(make).upper() if make else ""
    model = str(model).upper() if model else ""
    vin = str(vin).upper() if vin else ""
    extracted_type = str(extracted_type) if extracted_type else ""
    
    # --- 0a. Try NHTSA Decoding (The Gold Standard) ---
    nhtsa_data = decode_vin_nhtsa(vin)
    
    if nhtsa_data:
        # Override basic info if valid
        n_make = nhtsa_data.get('Make', '').upper()
        n_model = nhtsa_data.get('Model', '').upper()
        n_body_class = nhtsa_data.get('Body Class', '').upper()
        
        if n_make: make = n_make
        if n_model: model = n_model
        
        # Inject NHTSA Body Class into our text search for downstream logic
        extracted_type += f" {n_body_class}"

    # --- 0b. WMI Fixup (Fallback) ---
    elif not make and len(vin) >= 3:
        wmi = vin[:3]
        wmi_val = WMI_MAP.get(wmi)
        if wmi_val:
            make = wmi_val.upper()
            
    text = f"{make} {model} {extracted_type}".upper()

    # --- 1. BODY DETECTION (Upfits/Brands) ---
    body = None
    if any(x in text for x in ["BOX", "CUBE", "DRY VAN", "VAN BODY", "MORGAN", "SUPREME", "KIDRON", "UTILIMASTER"]):
        body = "Box"
    elif any(x in text for x in ["FLATBED", "STAKE", "PLATFORM", "KNAPHEIDE"]):
        body = "Flatbed"
    elif "DUMP" in text:
        body = "Dump"
    elif any(x in text for x in ["WRECKER", "TOW"]):
        body = "Tow"
    elif "REFER" in text or "REEFER" in text or "REFRIG" in text:
        body = "Refrigerated"

    # --- 2. CHASSIS DETECTION ---
    chassis = None
    
    # A. Trailers
    if any(x in text for x in ["TRAILER", "UTIL", "STRICK", "WABASH", "GREAT DANE"]):
        chassis = "Trailer"
        
    # B. Tractors
    elif any(x in text for x in ["CASCADIA", "T680", "VNL", "PROSTAR", "LT625", "VNL860", "389", "579", "TRUCK-TRACTOR"]):
        chassis = "Tractor"
    
    # C. Van Platforms
    elif any(x in text for x in ["TRANSIT", "SPRINTER", "PROMASTER", "PROMSTR", "PM2500", "PM3500", "EXPRESS", "SAVANA", "ECONOLINE", "E-350", "E-450", "CARGO VAN"]):
        # Critical Cutaway detection
        # Note: NHTSA often says "Truck - Cab Chassis" explicitly
        if any(x in text for x in ["CUTAWAY", "CHASSIS", "CAB CHASSIS", "DRW", "INCOMPLETE CHASSIS"]):
            chassis = "Cab Chassis"
        else:
            chassis = "Cargo Van"

    # D. Medium/Heavy Duty Cab Chassis
    elif any(x in text for x in ["F-450", "F-550", "F-650", "F-750", "NPR", "NQR", "NRR", "MT45", "MT55", "M2", "MV", "4300", "DURASTAR", "HINO", "INCOMPLETE"]):
        chassis = "Cab Chassis"
        
    # E. Pickups
    elif any(x in text for x in ["F-150", "F-250", "F-350", "SILVERADO", "SIERRA", "RAM", "PICKUP"]):
        chassis = "Pickup"

    # F. Passenger
    elif any(x in text for x in ["SEDAN", "SUV", "EXPLORER", "JEEP", "TESLA", "CAMRY", "COUPE"]):
        chassis = "Passenger"

    # --- 3. RECOMPOSITION ---
    final_type = "Truck" # Changed Default from "Auto" to "Truck" for commercial safety
    
    if chassis == "Trailer": 
        final_type = "Trailer"
    elif chassis == "Tractor": 
        final_type = "Tractor"
    elif body == "Box": 
        final_type = "Box Truck"
    elif body == "Dump": 
        final_type = "Dump Truck"
    elif body == "Tow": 
        final_type = "Tow Truck"
    elif body == "Flatbed": 
        final_type = "Flatbed Truck"
    elif chassis == "Cargo Van": 
        final_type = "Cargo Van"
    elif chassis == "Cab Chassis": 
        final_type = "Straight Truck"
    elif chassis == "Pickup": 
        final_type = "Pickup"
    elif chassis == "Passenger": 
        final_type = "Private Passenger Auto"
    # Fallback for "RAM" generic key without chassis match -> Truck
    elif "RAM" in text or "FORD" in text or "GMC" in text:
        final_type = "Truck" 

    return {
        "chassis": chassis,
        "body": body,
        "final_type": final_type,
        "make": make, # Enriched/Normed
        "model": model # Enriched/Normed
    }
