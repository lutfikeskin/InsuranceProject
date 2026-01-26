import re

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

def refine_vehicle_type(year, make, model, vin, extracted_type=None):
    """
    Refines the vehicle type based on Make, Model, and VIN patterns.
    Strictly separates 'Box Truck' from 'Straight Truck'.
    """
    year_str = str(year) if year else ""
    make = str(make).upper() if make else ""
    model = str(model).upper() if model else ""
    vin = str(vin).upper() if vin else ""
    
    # 0. VIN WMI Lookup (Enhance Make if missing)
    if not make and len(vin) >= 3:
        wmi = vin[:3]
        if wmi in WMI_MAP:
            make = WMI_MAP[wmi].upper()
            
    text = f"{make} {model}"

    # 1. TRAILERS
    if any(x in text for x in ["TRAILER", "UTIL", "VANS", "STRICK", "WABASH", "GREAT DANE", "UTILITY"]):
        return "Trailer"
        
    # 2. TRACTORS (Heavy Duty)
    if any(x in text for x in ["FREIGHTLINER", "KENWORTH", "PETERBILT", "VOLVO", "MACK", "INTERNATIONAL"]):
        # Specific Tractor Models
        if "CASCADIA" in text or "T680" in text or "VNL" in text or "PROSTAR" in text or "LT625" in text:
            return "Tractor"
            
        # If Extractor saw "Tractor", trust it.
        if extracted_type == "Tractor":
            return "Tractor"
            
        # Check against "Straight Truck" models before defaulting
        # If Extractor said "Dump" or "Straight", keep it.
        if extracted_type in ["Straight Truck", "Dump Truck", "Box Truck", "Tow Truck"]:
            pass # Fall through to verification
        else:
            # Heavy Duty Default -> Tractor (most common in commercial excluding specific vocational)
            # UNLESS it's a known vocational model (M2, MV, Durastar)
            if any(x in text for x in ["M2", "MV", "DURASTAR", "4300", "4400", "GRANITE"]):
                # These are usually Straight Trucks
                pass 
            else:
                return "Tractor"
        
    # 3. PICKUPS
    if any(x in text for x in ["F-150", "F150", "SILVERADO", "SIERRA", "RAM 1500", "RAM 2500", "RAM 3500", "F-250", "F-350"]):
        return "Pickup"
        
    # 4. CARGO VANS
    if any(x in text for x in ["SPRINTER", "TRANSIT", "PROMASTER", "EXPRESS", "SAVANA", "ECONOLINE", "E-350", "E350"]):
        # But wait, Transit Connect vs Transit 350?
        if "CUTAWAY" in text or "CHASSIS" in text:
             return "Box Truck" # Usually a box on a cutaway
        return "Cargo Van"
        
    # 5. STRAIGHT TRUCK vs BOX TRUCK
    # Chassis Models often used for Box Trucks
    if any(x in text for x in ["F-450", "F-550", "F550", "NPR", "NQR", "HINO", "M2", "MV", "4300"]):
        
        # A. If Text explicitly says "BOX" -> Box Truck
        if "BOX" in text:
            return "Box Truck"
            
        # B. If Extractor explicitly found "Box Truck" -> Trust it
        if extracted_type == "Box Truck":
            return "Box Truck"
            
        # C. If Extractor explicitly found "Straight Truck" -> Trust it
        if extracted_type == "Straight Truck":
            return "Straight Truck"

        # D. Default for Cab Chassis -> Straight Truck (Generic Safe)
        # The user specifically requested segregation. "Box Truck" implies a specific body.
        # "Straight Truck" is the accurate description of the chassis configuration.
        return "Straight Truck"
        
    # 6. PASSENGER / SUV
    if any(x in text for x in ["SEDAN", "COUPE", "SUV", "EXCURSION", "EXPLORER", "CAMRY", "CIVIC", "ACCORD", "COROLLA", "JEEP", "TESLA"]):
        if "EXCURSION" in text or "SUBURBAN" in text or "YUKON" in text:
             return "SUV" # Or Private Passenger Auto
        return "Private Passenger Auto"
        
    # 7. Fallback to Extracted Type if specific
    SPECIFIC_TYPES = ["Tractor", "Straight Truck", "Box Truck", "Cargo Van", "Pickup", "Trailer", "Dump Truck", "Tow Truck"]
    if extracted_type in SPECIFIC_TYPES:
        return extracted_type
        
    # 8. Final Default
    return "Truck" if "TRUCK" in text else "Auto"
