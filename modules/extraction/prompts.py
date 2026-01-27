
CLASSIFY_POLICY_PROMPT = """
    You are an insurance policy classification system.
    Determine the primary policy type of the provided PDF.
    
    Choose ONE value:
    - personal_auto
    - commercial_auto
    - general_liability
    - bop
    - commercial_package
    - umbrella
    - motor_truck_cargo
    - unknown

    Rules:
    - Base decision on explicit wording and structure.
    - Prefer declarations and coverage titles.
    - If unsure, return "unknown".
    """

LOCATE_SECTIONS_PROMPT = """
    Analyze the PDF and identify the page numbers for the following sections:
    1. Declarations (Policy info, dates, insured)
    2. Coverages (Limits, deductibles)
    3. Vehicles (Schedule of vehicles)
    4. Drivers (List of drivers)

    Return a JSON object with lists of 1-based page numbers for each section. 
    If a section is missing, return an empty list.
    """

EXTRACT_DECLARATIONS_PROMPT = """
    Extract core policy declarations information.
    
    CRITICAL - CARRIER NAME VS AGENCY:
    - You must distinguish between the "Carrier/Underwriter" (who pays claims) and the "Agency/Producer" (who sold the policy).
    - Carrier Name should be the company providing coverage (e.g., Progressive, Travelers, Liberty Mutual, etc.).
    - Look for text like "Underwritten by", "Coverage provided by", or "Insurance Company".
    - IGNORE logos or names labeled "Producer", "Agent", or "Broker" (e.g., Truckers National, Marsh, etc.) unless they are explicitly the underwriter.
    - If you see "Truckers National", that is likely an AGENCY. Look for the actual carrier (e.g., Progressive, Lloyds).

    Field List:
    - Carrier name (Use the advice above)
    - Policy Number, NAIC
    - Effective and Expiration Dates (YYYY-MM-DD)
    - Insured Name, Address, City, State, Zip
    - Premium Amount
    
    For each extracted field, identify its location in the document.
    Return 'field_locations' array containing {field, page_number, bbox}.
    bbox format: [ymin, xmin, ymax, xmax] (0-1000 scale).
    """

EXTRACT_VEHICLES_PROMPT = "Extract the schedule of covered vehicles. Include Year, Make, Model, VIN, GVW."

EXTRACT_DRIVERS_PROMPT = "Extract the list of drivers. Mark 'is_excluded' as true if explicitly stated."

def get_coverages_prompt(registry_text, policy_type):
    return f"""
    Extract insurance coverages using the strict COVERAGE ONTOLOGY.
    
    REGISTRY:
    {registry_text}

    RULES:
    1. Map every coverage to a valid 'coverage_code' from the registry.
    2. Use the exact 'family' and 'limit_structure' from the registry.
    3. CSL Supremacy: If Auto Liability CSL exists, ignore BI/PD split limits. Use 'AUTO_LIAB_CSL'.
    4. Auto Split (Triple): If you see 3 numbers (e.g., 30/60/50), extract 30/60 as 'AUTO_LIAB_BI' (per_person/per_accident) and 50 as 'AUTO_LIAB_PD' (per_occurrence).
    5. UM/UIM: NEVER use 'auto_liability' family. Use 'uninsured_motorist' or 'underinsured_motorist'.
    6. Do not extract "Not Purchased" or "Excluded" as 0 or null. Omit them.
    7. For each coverage, provide the 'location' {{page_number, bbox}} where the limit/coverage is stated.
    bbox format: [ymin, xmin, ymax, xmax] (0-1000 scale).

    Context: Policy Type is {policy_type.upper()}.
    """
