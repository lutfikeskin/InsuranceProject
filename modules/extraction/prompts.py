
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
    Analyze the PDF and identify page numbers for the following sections.

    Sections:
    - declarations (Policy info, dates, insured, Policy Premium Amount, Rating Worksheet, Invoice, Payment Schedule, Premium Summary)
    - coverages (Limits, deductibles)
    - vehicles (Schedule of all vehicles)
    - drivers (List of all drivers)

    Rules:
    - Use EMPTY ARRAY [] if a section is missing.
    - Do NOT return objects, ranges, or single integers.
    """

LOCATE_PREMIUM_SIGNALS_PROMPT = """
    Scan the full policy document.
    Identify ALL mentions related to the policy cost, premium, bills, or invoices.

    Target Signals:
    - "Gross Premium" / "Total Policy Premium"
    - "Amount Due" / "Total Amount Due"
    - "Discounted Premium" / "Adjusted Premium"
    - "Installment Total" / "Payment Plan"
    - "Invoice Total" / "Account Balance"

    For each signal found:
    1. Extract the exact Label (e.g. "Total 6 Month Premium").
    2. Identify the Page Number.
    3. Assign confidence (high if it looks like a Grand Total).
    
    Do NOT extract the actual dollar amounts here. We only need to know WHERE they are.
"""

EXTRACT_DECLARATIONS_PROMPT = """
    Extract core policy declarations information.
    
    CRITICAL - CARRIER NAME VS AGENCY:
    - You must distinguish between the "Carrier/Underwriter" (who pays claims) and the "Agency/Producer" (who sold the policy).
    - If multiple company names appear, choose the entity labeled: "Insurance Company", "Underwriter", or "Company".
    - IGNORE logos or names labeled "Producer", "Agent", or "Broker" (e.g., Truckers National, Marsh, etc.) unless they are explicitly the underwriter.

    Field List:
    - Carrier name (Use the advice above)
    - Policy Number
    - NAIC (If missing, leave it blank. Do NOT guess.)
    - Effective and Expiration Dates (YYYY-MM-DD)
    - Insured Name, Address, City, State, Zip
    - Business Name (if different from Insured Name)
    - State of Jurisdiction (if different from address state)
    - Financial Responsibility Name (Registered name for filings, e.g., on Form E or MCS-90)
    - Premium Amount (Documents can have different type of payments and amounts mentioned on them, we want to pick the amount that the customer will pay, actualy total premium of the policy)

    NEGATIVE CONSTRAINTS:
    - Do NOT extract a value if it is associated with a specific coverage (e.g., "Uninsured Motorist: $77").
    - Do NOT extract "Policy Coverage Amount" if it is just a subsection sum.
    - We want the GRAND TOTAL for the policy term.

    For each extracted field, identify its location in the document.
    Return 'field_locations' array containing {field, page_number, bbox}.
    bbox format: [ymin, xmin, ymax, xmax] (0-1000 scale).
    """

EXTRACT_VEHICLES_PROMPT = """
    Extract the schedule of covered vehicles.

    For each vehicle include:
    - year
    - make
    - model
    - vin
    - gvw
    - type

    VEHICLE TYPE RULES (STRICT):
    - Cargo Van examples: Ram ProMaster, Ford Transit, Mercedes Sprinter → "cargo_van"
    - Box Truck / Straight Truck (14ft–26ft) → "box_truck"
    - Semi / Tractor → "tractor"
    - Pickup (F-150, Silverado, RAM 1500) → "pickup"
    - Passenger vehicles → "passenger_auto"

    Rules:
    - Do NOT default to "auto".
    - If unsure, infer type from model name and GVW.
    - Never leave type empty.
    """

EXTRACT_DRIVERS_PROMPT = """
    Extract the list of drivers.

    For each driver:
    - full_name
    - license_number (if shown)
    - is_excluded (true ONLY if explicitly stated as excluded)

    Rules:
    - If a driver is marked "Excluded", set is_excluded = true.
    - If no drivers are listed, return an empty array.
    - Do NOT infer exclusions.
    """

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

    STRICT CONSTRAINTS:
    - Motor Truck Cargo MUST use family "cargo".
    - Auto Liability MUST use family "auto_liability".
    - Do NOT invent coverages not explicitly shown.
    - If a coverage limit is unclear, OMIT it.
    - Never create duplicate Auto Liability entries.

    VALIDATION CHECK:
    Before returning results, verify that:
    - No coverage violates the registry family.
    - CSL and Split Auto Liability do NOT coexist.

    Context: Policy Type is {policy_type.upper()}.
    """
