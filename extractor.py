import google.generativeai as genai
import os
import json
import tempfile
import time

CLASSIFICATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "policy_type": {
            "type": "STRING",
            "enum": [
                "personal_auto",
                "commercial_auto",
                "general_liability",
                "bop",
                "commercial_package",
                "umbrella",
                "motor_truck_cargo",
                "unknown"
            ]
        },
        "confidence": {
            "type": "STRING",
            "enum": ["high", "medium", "low"]
        },
        "signals": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        }
    },
    "required": ["policy_type", "confidence"]
}

BASE_EXTRACTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "policy": {
            "type": "OBJECT",
            "properties": {
                "carrier_name": {"type": "STRING"},
                "naic_number": {"type": "STRING"},
                "policy_number": {"type": "STRING"},
                "effective_date": {"type": "STRING"},
                "expiration_date": {"type": "STRING"},
                "account_type": {"type": "STRING"},
                "insured_name": {"type": "STRING"},
                "insured_address": {"type": "STRING"},
                "insured_city": {"type": "STRING"},
                "insured_state_code": {"type": "STRING"},
                "insured_zip": {"type": "STRING"},
                "business_name": {"type": "STRING"},
                "premium": {"type": "STRING"},
                "state": {"type": "STRING"},
                "financial_responsibility_name": {"type": "STRING"},
                "liability_limit": {"type": "STRING"},
                "cargo_limit": {"type": "STRING"},
                "cargo_deductible": {"type": "STRING"},
                "has_full_collision": {"type": "BOOLEAN"},
                "has_general_liability": {"type": "BOOLEAN"},
                "has_auto_liability": {"type": "BOOLEAN"}
            }
        },
        "vehicles": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "year": {"type": "INTEGER"},
                    "make": {"type": "STRING"},
                    "model": {"type": "STRING"},
                    "vin": {"type": "STRING"},
                    "gvw": {"type": "INTEGER"},
                    "type": {"type": "STRING"}
                }
            }
        },
        "coverages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "type": {"type": "STRING"},
                    "limit_person": {"type": "INTEGER"},
                    "limit_accident": {"type": "INTEGER"},
                    "deductible": {"type": "INTEGER"}
                }
            }
        },
        "drivers": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "full_name": {"type": "STRING"},
                    "license_number": {"type": "STRING"},
                    "is_excluded": {"type": "BOOLEAN"}
                }
            }
        }
    }
}

PERSONAL_AUTO_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "policy": {
            "type": "OBJECT",
            "properties": {
                "carrier_name": {"type": "STRING"},
                "naic_number": {"type": "STRING"},
                "policy_number": {"type": "STRING"},
                "effective_date": {"type": "STRING"},
                "expiration_date": {"type": "STRING"},
                "account_type": {"type": "STRING"},
                "insured_name": {"type": "STRING"},
                "insured_address": {"type": "STRING"},
                "insured_city": {"type": "STRING"},
                "insured_state_code": {"type": "STRING"},
                "insured_zip": {"type": "STRING"},
                "business_name": {"type": "STRING"},
                "premium": {"type": "STRING"},
                "state": {"type": "STRING"},
                "financial_responsibility_name": {"type": "STRING"},
                "liability_limit": {"type": "STRING"},
                "cargo_limit": {"type": "STRING"},
                "cargo_deductible": {"type": "STRING"},
                "has_full_collision": {"type": "BOOLEAN"},
                "has_general_liability": {"type": "BOOLEAN"},
                "has_auto_liability": {"type": "BOOLEAN"}
            }
        },
        "vehicles": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "year": {"type": "INTEGER"},
                    "make": {"type": "STRING"},
                    "model": {"type": "STRING"},
                    "vin": {"type": "STRING"},
                    "gvw": {"type": "INTEGER"},
                    "type": {"type": "STRING"}
                }
            }
        },
        "coverages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "type": {"type": "STRING"},
                    "family": {
                        "type": "STRING",
                        "enum": [
                            "auto_liability",
                            "uninsured_motorist",
                            "underinsured_motorist",
                            "medical_payments",
                            "pip",
                            "other"
                        ]
                    },
                    "limit_person": {"type": "INTEGER"},
                    "limit_accident": {"type": "INTEGER"},
                    "limit_property_damage": {"type": "INTEGER"},
                    "deductible": {"type": "INTEGER"}
                }
            }
        },
        "drivers": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "full_name": {"type": "STRING"},
                    "license_number": {"type": "STRING"},
                    "is_excluded": {"type": "BOOLEAN"}
                }
            }
        }
    }

}

def build_personal_auto_liability_limit(coverages):
    """
    Deterministically builds liability limit string using strict Coverage Family logic.
    Priority: CSL > Split Limits
    """
    # Filter for ONLY Auto Liability family to exclude UM/UIM
    auto_liability = [
        c for c in coverages
        if c.get("family") == "auto_liability"
    ]

    # Check for CSL (Combined Single Limit)
    # Detection: Explicit 'CSL' in type OR 'limit_accident' present without 'limit_person'
    csl = next(
        (c for c in auto_liability if "CSL" in c.get("type", "") or (c.get("limit_accident") and not c.get("limit_person"))),
        None
    )

    if csl and csl.get("limit_accident"):
        val = csl["limit_accident"]
        # Format as thousands if applicable, e.g. "100 CSL"
        fmt_val = str(val // 1000 if val >= 1000 else val)
        return f"{fmt_val} CSL"

    # Fallback to Split Limits (BI + PD)
    bi = next((c for c in auto_liability if "bodily injury" in c.get("type", "").lower()), None)
    pd = next((c for c in auto_liability if "property damage" in c.get("type", "").lower()), None)

    parts = []
    if bi:
        if bi.get('limit_person'):
            val = bi['limit_person']
            parts.append(str(val // 1000 if val >= 1000 else val))
        if bi.get('limit_accident'):
            val = bi['limit_accident']
            parts.append(str(val // 1000 if val >= 1000 else val))
    
    if pd and pd.get('limit_property_damage'):
        val = pd['limit_property_damage']
        parts.append(str(val // 1000 if val >= 1000 else val))
        
    return "/".join(parts) if parts else None

def validate_liability_limit(result):
    """
    Safety Guard: Ensures no CSL policy is incorrectly summarized as split limits.
    """
    summary = result.get("policy", {}).get("liability_limit")
    coverages = result.get("coverages", [])
    
    if summary and "/" in summary:
        auto_liability = [c for c in coverages if c.get("family") == "auto_liability"]
        if any("CSL" in c.get("type", "") for c in auto_liability):
            # This is a critical logic failure if it happens
            print("WARNING: CSL detected but split limit summary generated. Check extraction.")

def classify_policy(sample_file, model_name="gemini-2.0-flash"):
    """
    Determines the primary policy type of the provided PDF.
    """
    model = genai.GenerativeModel(model_name)
    
    classification_prompt = """
You are an insurance policy classification system.

Task:
Determine the primary policy type of the provided PDF.

Choose ONE value from this list:
- personal_auto
- commercial_auto
- general_liability
- bop
- commercial_package
- umbrella
- motor_truck_cargo
- unknown

Rules:
- Base your decision on explicit wording and structure.
- Prefer declarations and coverage titles.
- If multiple coverages exist, choose the dominant policy type.
- If uncertain, return "unknown".

Return STRICT JSON only.
"""

    response = model.generate_content(
        [sample_file, classification_prompt],
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=CLASSIFICATION_SCHEMA
        )
    )

    return json.loads(response.text)

def configure_gemini(api_key):
    genai.configure(api_key=api_key)

def process_pdf(file_bytes, api_key):
    """
    Uploads a PDF to Gemini and extracts structured data.
    """
    configure_gemini(api_key)
    
    # Save bytes to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name

    try:
        # Upload using the File API
        print(f"Uploading file: {tmp_path}")
        sample_file = genai.upload_file(path=tmp_path, display_name="Policy PDF")
        
        # Verify upload with timeout
        start_time = time.time()
        while sample_file.state.name == "PROCESSING":
            if time.time() - start_time > 60: # 60 seconds timeout
                raise TimeoutError("File processing timed out.")
            time.sleep(0.5)
            sample_file = genai.get_file(sample_file.name)
            
        if sample_file.state.name == "FAILED":
            raise ValueError("File upload failed.")

        # Prepare the model with fallback strategy
        # Based on available models: gemini-flash-latest, gemini-pro-latest
        model_candidates = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ]
        
        system_instructions = {
            "commercial_auto": """
You are a senior U.S. insurance underwriter specializing in commercial auto policies.

Task:
Extract policy data from the provided PDF into STRICT JSON that conforms exactly to the provided schema.

GLOBAL RULES:
- Output JSON only.
- Do not guess or infer values.
- If a value is not explicitly present, return null.
- Do not include explanatory text in values.
- Do not add extra fields.

SECTION PRIORITY:
1. Declarations Page
2. Coverage Schedule
3. Vehicle Schedule
4. Driver Schedule
5. Endorsements
6. Invoices (premium only if not found elsewhere)

CARRIER:
- carrier_name must be the underwriting insurance company, not the agent, broker, MGA, or program administrator.

FINANCIAL RESPONSIBILITY NAME:
- Extract ONLY the customer’s personal legal name from the “Financial Responsibility Information” section.
- Exclude insurers, state agencies, filing offices, and companies.

VEHICLES:
- Extract all vehicles with valid VINs (17 characters, alphanumeric, excluding I, O, Q).
- Extract Year, Make, and Model.
- **VEHICLE TYPE EXCEPTION**: Unlike other fields, you **SHOULD INFER** the valid vehicle type based on the Make and Model if it is not explicitly stated.
  - **MANDATORY**: You must use one of these specific types: "Tractor", "Straight Truck", "Box Truck", "Cargo Van", "Pickup", "Trailer", "Dump Truck", "Tow Truck".
  - **FORBIDDEN**: Do NOT use generic terms like "Truck" or "Auto".
- Each VIN must be unique.

COVERAGES:
- Extract limit amounts only (e.g. "$1,000,000").
- If coverage is CSL, do not fabricate split limits.
- has_full_collision = true if any vehicle has Collision or Comprehensive coverage.

FLAGS:
- has_general_liability = true only if a General Liability section with limits exists.
- has_auto_liability = true only if an Auto Liability section with limits exists.

DRIVERS:
- Extract all listed drivers.
- is_excluded = true only if explicitly stated.

FORMATTING:
- Dates must be YYYY-MM-DD.
- Currency values must preserve symbols.
- Integers must not contain commas.
""",
            "personal_auto": """
You are a senior U.S. insurance underwriter specializing in personal auto policies.

Task:
Extract policy data from the provided PDF into STRICT JSON that conforms exactly to the provided schema.

GLOBAL RULES:
- Output JSON only.
- Do not guess or infer values.
- If a value is not explicitly present, return null.

SPECIFIC TO PERSONAL AUTO:
- DRIVERS: Extract all listed drivers, including household members and excluded drivers.
- VEHICLES: Extract all personal vehicles.

COVERAGE FAMILY RULES (CRITICAL):
Each coverage MUST be assigned to exactly one family:
- "auto_liability"
- "uninsured_motorist"
- "underinsured_motorist"
- "medical_payments"
- "pip"
- "other"

Auto Liability includes:
- "Liability Insurance"
- "Bodily Injury Liability"
- "Property Damage Liability"
- "Combined Single Limit"

Uninsured / Underinsured Motorist includes:
- "Uninsured Motorist"
- "UM"
- "Underinsured Motorist"
- "UIM"

UM/UIM coverages MUST NOT be treated as Auto Liability.

COMBINED SINGLE LIMIT (CSL) RULES:
If a coverage explicitly states "Combined Single Limit", "CSL", or "Each Accident" with a single dollar amount:
- Extract ONE coverage with:
  type = "Auto Liability - CSL"
  family = "auto_liability"
  limit_accident = <amount>
- Do NOT create limit_person

PERSONAL AUTO LIABILITY RULES (Split Limits):
  - Bodily Injury Liability is usually listed as:
    - "$X each person"
    - "$Y each accident"
  - Property Damage Liability is usually listed separately as:
    - "$Z each accident"

  You MUST extract:
  - A coverage with type exactly "Bodily Injury Liability":
    - family = "auto_liability"
    - set limit_person = X
    - set limit_accident = Y
  - A coverage with type exactly "Property Damage Liability":
    - family = "auto_liability"
    - set limit_property_damage = Z

- EXCLUSIONS: If a driver is listed as 'Excluded', set 'is_excluded' to true.

FORMATTING:
- Dates: YYYY-MM-DD.
- Currency: Preserve symbols (e.g., "$50,000").
- INTEGERS: For limits in coverages, provide RAW INTEGERS (e.g. 30000 instead of "$30,000").
"""
        }
        

        # 1. Classify Policy
        print("Classifying policy type...")
        try:
            classification = classify_policy(sample_file)
            print(f"Classification result: {classification}")
            
            if classification['policy_type'] == "unknown" or classification['confidence'] == "low":
                if classification['policy_type'] == "unknown":
                    print("Could not determine policy type. Extraction aborted.")
                    return None, None
                else:
                    print("Low confidence in policy classification. Proceeding with caution.")
        except Exception as e:
            print(f"Classification failed: {e}")
            return None, None

        policy_type = classification['policy_type']
        
        # 2. Select Instruction and Schema
        instruction = system_instructions.get(policy_type, system_instructions["commercial_auto"])
        schema = PERSONAL_AUTO_SCHEMA if policy_type == "personal_auto" else BASE_EXTRACTION_SCHEMA
        
        # 3. Attempt extraction with fallbacks
        response = None
        last_error = None
        for model_name in model_candidates:
            print(f"Attempting generation with model: {model_name}")
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    [sample_file, instruction],
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        response_schema=schema
                    )
                )
                print(f"Success with {model_name}")
                break # Stop if successful
            except Exception as e:
                print(f"Failed with {model_name}: {e}")
                last_error = e
        
        if not response:
            print("All model attempts failed.")
            if last_error:
                raise last_error
        
        # Parse JSON
        try:
            result = json.loads(response.text)
            
            # Post-Process Personal Auto Liability Limit
            if policy_type == "personal_auto":
                validate_liability_limit(result)
                assembled_limit = build_personal_auto_liability_limit(result.get("coverages", []))
                if assembled_limit:
                    result["policy"]["liability_limit"] = assembled_limit

            # Inject classification metadata into the result
            result['classification'] = classification
            return result, response.usage_metadata
        except json.JSONDecodeError: 
            # Fallback for removing markdown code blocks if they slip through (rare with schema)
            clean_text = response.text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            try:
                return json.loads(clean_text), response.usage_metadata
            except:
                print(f"Failed to decode JSON: {response.text}")
                return None, None
            
    finally:
        # Cleanup
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
