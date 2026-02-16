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

# --- KNOWN CARGO VAN MODELS ---
# These are always Cargo Van regardless of anything else
CARGO_VAN_KEYWORDS = [
    "TRANSIT", "SPRINTER", "PROMASTER", "PROMSTR",
    "PM2500", "PM3500", "PM 2500", "PM 3500",
    "PROMASTER 2500", "PROMASTER 3500", "PROMASTER2500", "PROMASTER3500",
    "NV 2500", "NV 3500", "NV2500", "NV3500",  # Nissan NV
    "METRIS",  # Mercedes Metris
    "SAVANA", "ECONOLINE", "EXPRESS",
    "E-350", "E350",  # Ford E-Series vans (non-cutaway)
    "CARGO VAN",
]

# --- MEDIUM/HEAVY DUTY CHASSIS INDICATORS ---
# These are Cab Chassis / Straight Truck platforms — never "Box Truck"
CAB_CHASSIS_KEYWORDS = [
    # Ford Medium Duty
    "F-450", "F-550", "F-650", "F-750", "F450", "F550", "F650", "F750",
    # Isuzu
    "NPR", "NQR", "NRR",
    # International
    "4300", "4400", "DURASTAR", "MV607", "MV607",
    # Morgan Olson (Stepvans)
    "MT45", "MT55",
    # Freightliner Medium Duty
    "M2 106", "M2 112", "M2106", "M2112", "108SD", "114SD",
    # Hino
    "HINO",
    # E-Series cutaways
    "E-450", "E-550", "E450", "E550",
    # NHTSA body class tags
    "INCOMPLETE", "CAB CHASSIS", "CHASSIS CAB", "TRUCK - CAB",
]

# Regex for standalone "M2" (e.g. "M2" but not "PM2500" or "RAM2500")
M2_PATTERN = re.compile(r'(?<![A-Z])M2(?!\d{3})', re.IGNORECASE)

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

def refine_vehicle_type(year, make, model, vin, extracted_type=None, extracted_chassis=None, extracted_body=None, gvw=None):
    """
    Refines the vehicle type based on a two-layer Chassis + Body model.
    Prioritizes NHTSA values if available, falls back to keyword matching.
    
    Priority Order (Recomposition):
    1. Trailer
    2. Tractor
    3. Cab Chassis (medium/heavy duty) → always "Straight Truck"
    4. Cargo Van
    5. Box body on light-duty/unknown chassis → "Box Truck"  
    6. Other body types (Dump, Tow, Flatbed)
    7. Pickup
    8. Passenger
    """
    year_str = str(year) if year else ""
    make = str(make).upper() if make else ""
    model = str(model).upper() if model else ""
    vin = str(vin).upper() if vin else ""
    extracted_type = str(extracted_type) if extracted_type else ""
    extracted_chassis = str(extracted_chassis) if extracted_chassis else ""
    extracted_body = str(extracted_body) if extracted_body else ""
    
    # Parse GVW to int
    gvw_int = 0
    if gvw:
        try:
            gvw_int = int(re.sub(r'[^\d]', '', str(gvw)))
        except (ValueError, TypeError):
            gvw_int = 0
    
    # --- 0a. Try NHTSA Decoding (The Gold Standard) ---
    nhtsa_data = decode_vin_nhtsa(vin)
    
    nhtsa_gvwr = 0
    if nhtsa_data:
        # Override basic info if valid
        n_make = nhtsa_data.get('Make', '').upper()
        n_model = nhtsa_data.get('Model', '').upper()
        n_body_class = nhtsa_data.get('Body Class', '').upper()
        
        if n_make: make = n_make
        if n_model: model = n_model
        
        # Inject NHTSA Body Class into our text search for downstream logic
        extracted_type += f" {n_body_class}"
        
        # Try to get GVWR from NHTSA
        gvwr_str = nhtsa_data.get('Gross Vehicle Weight Rating From', '')
        if gvwr_str:
            try:
                nhtsa_gvwr = int(re.sub(r'[^\d]', '', gvwr_str))
            except (ValueError, TypeError):
                pass

    # Use the best GVW we have
    effective_gvw = max(gvw_int, nhtsa_gvwr)

    # --- 0b. WMI Fixup (Fallback) ---
    if not make and len(vin) >= 3:
        wmi = vin[:3]
        wmi_val = WMI_MAP.get(wmi)
        if wmi_val:
            make = wmi_val.upper()
            
    text = f"{make} {model} {extracted_type} {extracted_chassis} {extracted_body}".upper()

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
        
    # B. Tractors (check before medium-duty to avoid false matches)
    elif any(x in text for x in ["CASCADIA", "T680", "VNL", "PROSTAR", "LT625", "VNL860", "389", "579", "TRUCK-TRACTOR", "TRUCK TRACTOR"]):
        chassis = "Tractor"
    
    # C. Cargo Vans — MUST run before Pickup to prevent "RAM" in "PROMASTER" matching Pickup
    elif any(x in text for x in CARGO_VAN_KEYWORDS):
        # Critical Cutaway detection
        # Note: NHTSA often says "Truck - Cab Chassis" explicitly for cutaways
        if any(x in text for x in ["CUTAWAY", "CAB CHASSIS", "CHASSIS CAB", "DRW", "INCOMPLETE CHASSIS", "TRUCK - CAB"]):
            chassis = "Cab Chassis"
        else:
            chassis = "Cargo Van"

    # D. Medium/Heavy Duty Cab Chassis — these are always Straight Trucks
    elif any(x in text for x in CAB_CHASSIS_KEYWORDS) or M2_PATTERN.search(text):
        chassis = "Cab Chassis"
        
    # E. Pickups
    elif any(x in text for x in ["F-150", "F-250", "F-350", "F150", "F250", "F350", "SILVERADO", "SIERRA", "RAM ", "RAM\t", "PICKUP"]):
        chassis = "Pickup"

    # F. Passenger
    elif any(x in text for x in ["SEDAN", "SUV", "EXPLORER", "JEEP", "TESLA", "CAMRY", "COUPE"]):
        chassis = "Passenger"

    # --- 2b. GVW OVERRIDE ---
    # If GVW >= 10,001 lbs and we didn't detect a specific chassis, force Cab Chassis
    # (FHWA Class 3+ is a medium-duty commercial vehicle, never a "Box Truck")
    if effective_gvw >= 10001 and chassis not in ("Trailer", "Tractor", "Cab Chassis"):
        chassis = "Cab Chassis"

    # --- 3. RECOMPOSITION ---
    # KEY FIX: Cab Chassis (medium/heavy-duty) ALWAYS produces "Straight Truck",
    # regardless of body type. Only light-duty/unknown chassis + box body = "Box Truck".
    final_type = "Truck"  # Default for commercial safety
    
    if chassis == "Trailer": 
        final_type = "Trailer"
    elif chassis == "Tractor": 
        final_type = "Tractor"
    elif chassis == "Cab Chassis":
        # Medium/heavy-duty platform — always "Straight Truck" regardless of body
        final_type = "Straight Truck"
    elif chassis == "Cargo Van": 
        final_type = "Cargo Van"
    elif body == "Box": 
        # Only light-duty or unknown chassis with box body
        final_type = "Box Truck"
    elif body == "Dump": 
        final_type = "Dump Truck"
    elif body == "Tow": 
        final_type = "Tow Truck"
    elif body == "Flatbed": 
        final_type = "Flatbed Truck"
    elif body == "Refrigerated":
        final_type = "Refrigerated Truck"
    elif chassis == "Pickup": 
        final_type = "Pickup"
    elif chassis == "Passenger": 
        final_type = "Private Passenger Auto"
    # Fallback for generic makes without chassis match -> Truck
    elif any(x in make for x in ["RAM", "FORD", "GMC", "CHEVROLET"]):
        final_type = "Truck" 

    return {
        "chassis": chassis,
        "body": body,
        "final_type": final_type,
        "make": make, # Enriched/Normed
        "model": model, # Enriched/Normed
        "gvw": effective_gvw if effective_gvw else None
    }
