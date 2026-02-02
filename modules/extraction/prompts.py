
GLOBAL_EXTRACTION_PRINCIPLES = """
    GLOBAL EXTRACTION PRINCIPLES:
    - Extract from tables, key-value blocks, or prose.
    - BE CONCISE: Only reason about high-ambiguity cases. 
    - THINKING RULE: Keep internal chain-of-thought extremely short (under 50 tokens).
    - Output MUST be valid JSON.
"""

CLASSIFY_POLICY_PROMPT = GLOBAL_EXTRACTION_PRINCIPLES + """
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
    - Ignore standalone endorsement pages unless they clearly state the base policy form.
    - If unsure, return "unknown".
    
    DOMINANCE RULE:
    - Classify based on the PRIMARY policy form, not endorsements.
    - If multiple coverage types exist, choose the base policy (e.g., Commercial Auto + Cargo endorsement -> commercial_auto).
    
    PACKAGE CONFIRMATION:
    - If you choose 'commercial_package', you MUST confirm that it contains AT LEAST TWO of: General Liability, Property, or Auto.
    - If it only has Auto + Cargo, classify as 'commercial_auto' (dominance rule).
    - List the detected coverage families used to justify this decision in the 'signals' array.
    """











def get_extract_all_prompt(registry_text):
    return GLOBAL_EXTRACTION_PRINCIPLES + f"""
    You are an expert insurance underwriter and data extraction specialist.
    Your task is to CLASSIFY and EXTRACT the COMPLETE policy information from the provided document in a single pass.

    You must extract five main sections:
    1. CLASSIFICATION: Determine the primary policy type (e.g., commercial_auto, personal_auto).
    2. POLICY DECLARATIONS: General info like Carrier, Policy #, Dates, Insured Name/Address.
    3. COVERAGES: Limits & Deductibles based on the provided registry.
    4. VEHICLES: Full schedule of vehicles.
    5. DRIVERS: Full schedule of drivers.

    --- SECTION 1: CLASSIFICATION ---
    Choose ONE: personal_auto, commercial_auto, general_liability, bop, commercial_package, umbrella, motor_truck_cargo, unknown.
    - Base decision on explicit wording.
    - PACKAGE RULE: If 'commercial_package', confirm AT LEAST TWO of: General Liability, Property, or Auto.

    --- SECTION 2: POLICY DECLARATIONS ---
    - Distinguish between Carrier (Risk Bearer) and Agency (Broker).
    - Fields: Carrier Name, Policy #, NAIC, Effective/Expiration Dates, Insured Name/Address/City/State/Zip, Business Name.
    - Premium: Extract the GRAND TOTAL premium for the policy term.

    --- SECTION 3: VEHICLES ---
    - Extract ALL vehicles (VIN, Year, Make, Model, GVW, Type).
    - Look for explicit schedules OR vehicles mentioned in prose.

    --- SECTION 4: DRIVERS ---
    - Extract ALL drivers (Name, License #, Excluded Status).

    --- SECTION 5: COVERAGES ---
    - Use the strict COVERAGE ONTOLOGY below.
    - REGISTRY (MINIFIED):
    {registry_text}
    
    - Map every coverage to a valid 'coverage_code'.
    - Link coverages to 'vehicle_vin' if they apply to a specific unit.

    OUTPUT FORMAT:
    Return a SINGLE JSON object matching exactly:
    {{
        "classification": {{ "policy_type": "...", "confidence": "...", "signals": [...] }},
        "policy": {{ ...declarations_fields... }},
        "coverages": [ ...list_of_coverages... ],
        "vehicles": [ ...list_of_vehicles... ],
        "drivers": [ ...list_of_drivers... ]
    }}
    
    Verify that all JSON keys match the schema exactly.
    """
