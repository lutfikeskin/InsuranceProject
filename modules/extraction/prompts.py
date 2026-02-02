
GLOBAL_EXTRACTION_PRINCIPLES = """
    GLOBAL EXTRACTION PRINCIPLES:
    - The document may be any insurance artifact (declaration, endorsement, jacket, memorandum, certificate, ID card).
    - Information may appear in tables, key-value blocks, footnotes, or free-form paragraphs.
    - NEVER assume a section header exists.
    - Presence of information matters more than formatting.
    - If information exists but is incomplete, extract it anyway.
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

LOCATE_SECTIONS_PROMPT = GLOBAL_EXTRACTION_PRINCIPLES + """
    Analyze the PDF and identify page numbers for the following sections.

    Sections:
    - declarations (Policy info, dates, insured, Policy Premium Amount, Rating Worksheet, Invoice, Payment Schedule, Premium Summary)
    - coverages (Limits, deductibles)
    - vehicles (Schedule of all vehicles)
    - drivers (List of all drivers)

    Rules:
    - Use EMPTY ARRAY [] if a section is missing.
    - Do NOT return objects, ranges, or single integers.
    - A section may be embedded inside another page without a header.
    - Return the page number if the content exists, even if no section title is present.
    """

UNIVERSAL_SCOUT_PROMPT = GLOBAL_EXTRACTION_PRINCIPLES + """
    You are a document intelligence system analyzing an insurance policy PDF.

    Your task is NOT to extract values.
    Your task is to identify WHERE important information exists in the document.

    Scan the entire document carefully and identify page numbers for the following signals:

    1. PREMIUM SIGNALS
       - Any page containing:
         - Total Policy Premium
         - Amount Due
         - Net / Adjusted / Discounted Premium
         - Invoice Total
       - Ignore line-item fees or per-coverage charges.
       - Return ALL possible premium-related pages.
       - CLASSIFY TYPE: "gross", "net", "total", "installment", "fee", or "unknown".
       - IDENTIFY PERIOD: Does it explicitly state "Annual", "6-Month", or "Monthly"?

    2. VEHICLE SCHEDULE SIGNALS
       - Pages containing:
         - Schedule of Vehicles
         - Fleet Schedule
         - VIN Lists
         - Auto Schedule tables
       - If a formal schedule is missing, still return pages where vehicle information is described in prose.

    3. DRIVER SCHEDULE SIGNALS
       - Pages containing:
         - Driver Schedules
         - Named Driver Lists
         - Excluded Driver Endorsements
       - If a formal schedule is missing, still return pages where driver information is described in prose.

    4. COVERAGE SCHEDULE SIGNALS
       - Pages containing:
         - Coverage Schedules
         - Endorsement-only coverages
         - Special or added coverage pages

    Rules:
    - Use 1-based page numbering.
    - Do NOT guess.
    - Do NOT extract dollar amounts.
    - If multiple signals exist, return all of them.
    - If nothing is found for a category, return an empty list.

    Return only valid JSON matching the provided schema.
"""

# MERGED PROMPT: The Cartographer
CARTOGRAPHER_PROMPT = GLOBAL_EXTRACTION_PRINCIPLES + """
    You are 'The Cartographer', a document intelligence system.
    Your job is to Map the Document.

    Perform TWO tasks simultaneously:
    
    TASK 1: LOCATE BROAD SECTIONS (Page Ranges)
    Identify page numbers for:
    - declarations (Policy info, dates, insured, Premium Summary)
    - coverages (Limits, deductibles)
    - vehicles (Schedule of all vehicles)
    - drivers (List of all drivers)

    TASK 2: SCOUT SPECIFIC SIGNALS (Precise Locations)
    Scan for specific signals to aid extraction:
    
    1. PREMIUM SIGNALS
       - Any page containing Total Policy Premium, Amount Due, or Net Premium.
       - Ignore line-item fees.
       - CLASSIFY: "gross", "net", "total", "installment".
       - PERIOD: "annual", "6-month", "monthly".

    2. VEHICLE SCHEDULE SIGNALS
       - Pages with explicit Vehicle Schedules, Fleet Lists, or VIN Tables.

    3. DRIVER SCHEDULE SIGNALS
       - Pages with Driver Lists or Excluded Driver endorsements.

    4. COVERAGE SCHEDULE SIGNALS
       - Pages with Coverage Schedules or specific Endorsement forms.

    Rules:
    - Use 1-based page numbering.
    - Do NOT extract dollar values or names at this stage, only finding the PAGES.
    - If a section is missing, use empty array [].
    - Return a single JSON object matching the CARTOGRAPHER_SCHEMA.
"""

EXTRACT_DECLARATIONS_PROMPT = GLOBAL_EXTRACTION_PRINCIPLES + """
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
    - Premium Amount (Documents can have different type of payments and amounts mentioned on them, we want to pick the amount that the customer will pay, actually total premium of the policy)

    NEGATIVE CONSTRAINTS - THE FEE TRAP:
    - Do NOT extract "Total Amount Due" if it includes installment fees, finance charges, or "Total Pay Plan".
    - Do NOT extract "Policy Coverage Amount" if it is just a subsection sum.
    - We want the GRAND TOTAL for the policy term (Premium for the Policy Period).

    PREMIUM SELECTION RULE:
    - Multiple premium amounts may exist across the document.
    - Use only the amount that represents the FINAL total premium for the full policy term.
    - TIME RULE: Prefer totals stated BEFORE payment schedules or installment tables.
    - If multiple candidates remain ambiguous, choose NONE and leave blank.

    For each extracted field, identify its location in the document.
    Return 'field_locations' array containing {field, page_number, bbox}.
    bbox format: [ymin, xmin, ymax, xmax] (0-1000 scale).
    """

EXTRACT_VEHICLES_PROMPT = GLOBAL_EXTRACTION_PRINCIPLES + """
    Extract ALL covered vehicles mentioned anywhere in the document.

    GLOBAL RULE:
    Before deciding "no vehicles exist", you MUST perform a semantic scan of the entire document
    for vehicle-related language, even if no table or schedule exists.

    VEHICLE EXISTENCE SIGNALS (ANY is sufficient):
    - VIN
    - Year / Make / Model
    - Unit #
    - Plate #
    - GVW
    - References such as:
      "any owned autos", "scheduled autos", "covered vehicles", "listed vehicles",
      "tractor", "trailer", "truck", "van", "auto"

    STRUCTURE RULE:
    - Vehicles may appear in tables OR embedded in paragraphs OR footnotes.
    - Multiple vehicles described in one paragraph MUST be split into separate records.
    - If a vehicle is referenced generically (e.g., "1 Tractor"), extract a record with description filled.

    FIELDS PER VEHICLE:
    - year
    - make
    - model
    - vin
    - gvw
    - type
    - chassis
    - body

    CHASSIS PRECEDENCE RULE (STRICT):
    - Chassis = underwriting platform
    - Body = attached structure
    - Chassis determines classification

    VEHICLE TYPE RULES (STRICT):
    - Cargo Van (Transit, ProMaster, Sprinter) → cargo_van
    - Box / Straight Truck (14–26 ft) → box_truck
    - Tractor / Semi → tractor
    - Pickup (F-150, RAM 1500, Silverado) → pickup
    - Passenger autos → passenger_auto

    INFERENCE RULES:
    - Type may be inferred from model name or GVW.
    - Never infer VINs or plates.
    - Never merge vehicles.

    FAILURE RULE:
    - If NO vehicles are explicitly or implicitly referenced, return:
      { "vehicles": [] }

    OUTPUT FORMAT (STRICT JSON):
    {
      "vehicles": [
        {
          "year": string | null,
          "make": string | null,
          "model": string | null,
          "vin": string | null,
          "gvw": string | null,
          "type": string,
          "chassis": string | null,
          "body": string | null,
          "description": string | null
        }
      ]
    }
    """

EXTRACT_DRIVERS_PROMPT = GLOBAL_EXTRACTION_PRINCIPLES + """
    Extract ALL drivers referenced anywhere in the document.

    GLOBAL RULE:
    Before deciding "no drivers exist", perform a semantic scan for driver-related language.

    DRIVER EXISTENCE SIGNALS (ANY is sufficient):
    - Person names labeled as drivers
    - "Driver", "Operator", "Named Driver"
    - "Excluded Driver"
    - Statements like:
      "All drivers are licensed"
      "Approved drivers include"
      "Coverage applies to listed drivers"

    STRUCTURE RULE:
    - Drivers may appear in tables, lists, prose, footnotes, or endorsements.
    - Do NOT treat underwriting questionnaires as driver lists.

    FIELDS PER DRIVER:
    - full_name
    - license_number
    - is_excluded

    EXCLUSION RULES (STRICT):
    - is_excluded = true ONLY if explicitly stated
    - Symbols (*, †, EXC, X) count as explicit exclusion
    - If listed under a section titled "Excluded Drivers", mark excluded
    - Cross-page exclusion references must be respected

    NON-INFERENCE RULES:
    - Do NOT invent driver names
    - Do NOT infer number of drivers
    - Do NOT assume exclusions

    FAILURE RULE:
    - If no drivers are mentioned anywhere, return:
      { "drivers": [] }

    OUTPUT FORMAT (STRICT JSON):
    {
      "drivers": [
        {
          "full_name": string | null,
          "license_number": string | null,
          "is_excluded": boolean
        }
      ]
    }
    """

def get_coverages_prompt(registry_text, policy_type):
    return GLOBAL_EXTRACTION_PRINCIPLES + f"""
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
    - "SILENT ZERO": If a limit is blank, dashes "---", or "Excluded", RETURN NULL. Do not return 0.
    - COLUMN BLEED: Do NOT infer limits from neighboring rows or columns (e.g. don't copy Med Pay limit to Towing).
    - Never create duplicate Auto Liability entries.
    - SAMPLE TABLE EXCLUSION: If a limit appears in an example, legend, or explanatory section, OMIT it.

    VALIDATION CHECK:
    Before returning results, verify that:
    - No coverage violates the registry family.
    - CSL and Split Auto Liability do NOT coexist.

    Context: Policy Type is {policy_type.upper()}.
    """
