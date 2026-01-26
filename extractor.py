import google.generativeai as genai
import os
import json
import tempfile
import time
from coverage_ontology import (
    COVERAGE_REGISTRY, 
    summarize_auto_liability, 
    validate_coverage, 
    is_coverage_allowed_for_policy_type,
    format_liability_limit
)

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

# --- ONTOLOGY-AWARE SCHEMA ---
# This schema replaces the legacy schemas and correctly models the strict ontology.

ONTOLOGY_AWARE_SCHEMA = {
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
                    "coverage_code": {
                        "type": "STRING", 
                        "description": "Must be one of the explicitly allowed registry codes."
                    },
                    "display_name": {"type": "STRING"},
                    "family": {
                        "type": "STRING",
                        "enum": [
                            "auto_liability",
                            "uninsured_motorist",
                            "underinsured_motorist",
                            "physical_damage",
                            "general_liability",
                            "cargo",
                            "medical_payments",
                            "pip",
                            "other"
                        ]
                    },
                    "limit_structure": {
                        "type": "STRING",
                        "enum": ["csl", "split", "per_occurrence", "aggregate", "deductible_only", "scheduled"]
                    },
                    "limits": {
                        "type": "OBJECT",
                        "properties": {
                            "per_person": {"type": "INTEGER"},
                            "per_accident": {"type": "INTEGER"},
                            "per_occurrence": {"type": "INTEGER"},
                            "combined_single_limit": {"type": "INTEGER"},
                            "aggregate": {"type": "INTEGER"}
                        }
                    },
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

def perform_extraction_sanity_checks(result, policy_type):
    """
    Final defense: logical rules that must not be violated.
    Returns (True, None) or (False, FailureReason).
    """
    coverages = result.get("coverages", [])
    
    # 1. At least one Auto Liability for Auto Policies
    if policy_type in ["personal_auto", "commercial_auto"]:
        has_liab = any(c.get("family") == "auto_liability" for c in coverages)
        if not has_liab:
            msg = "SANITY CHECK FAILED: No auto liability found for auto policy."
            print(msg)
            return False, msg
            
    # 2. CSL and Split BI must never coexist in Auto Liab
    auto_liabs = [c for c in coverages if c.get("family") == "auto_liability"]
    has_csl = any(c.get("limit_structure") == "csl" for c in auto_liabs)
    has_split = any(c.get("limit_structure") == "split" for c in auto_liabs)
    if has_csl and has_split:
        msg = "SANITY CHECK WARNING: Mixed CSL and Split limits in Auto Liability. Keeping data for manual review."
        print(msg)
        # return False, msg  <-- DOWNGRADED TO WARNING
        
    # 3. UM/UIM must never be in auto_liability family
    for c in coverages:
        if "uninsured" in c.get("display_name", "").lower() or "um" == c.get("coverage_code", "").lower()[:2]:
            if c.get("family") == "auto_liability":
                msg = f"SANITY CHECK FAILED: UM/UIM found in auto_liability family: {c['display_name']}"
                print(msg)
                return False, msg
                
    return True, None

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
        model_candidates = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ]
        
        # 1. Classify Policy
        try:
            print("Classifying policy type...")
            classification = classify_policy(sample_file)
            print(f"Classification result: {classification}")
            
            if classification['policy_type'] == "unknown" or classification['confidence'] == "low":
                if classification['policy_type'] == "unknown":
                    print("Could not determine policy type. Extraction aborted.")
                    return None, None, "Unknown Policy Type"
                else:
                    print("Low confidence in policy classification. Proceeding with caution.")
        except Exception as e:
            print(f"Classification failed: {e}")
            return None, None, f"Classification Failed: {e}"

        policy_type = classification['policy_type']
        
        # 2. Prepare Ontology and Instruction
        registry_text = json.dumps(COVERAGE_REGISTRY, indent=2)
        
        ontology_instruction = f"""
You are an expert insurance extractor using a strict COVERAGE ONTOLOGY.

YOUR GOAL:
Map every coverage on the policy to the closest matching 'coverage_code' from the registry below.

STRICT RULES:
1. You must output JSON conforming to the schema.
2. For each coverage, you MUST choose a valid 'coverage_code' from the registry.
3. You must use the 'family' and 'limit_structure' defined in the registry for that code.
4. Populate the 'limits' object based on the structure:
   - If 'split': use 'per_person' and 'per_accident'
   - If 'csl': use 'combined_single_limit' ONLY
   - If 'per_occurrence': use 'per_occurrence'
   
REGISTRY (The Source of Truth):
{registry_text}

SPECIFIC RULES FOR {policy_type.upper()}:
- Extract all drivers and vehicles.
- For CSL policies ("Combined Single Limit" or "Each Accident" only):
    - Use coverage_code="AUTO_LIAB_CSL"
    - Set limits.combined_single_limit = <amount>
    - DO NOT set per_person limits.
- For Split Limit policies:
    - Use coverage_code="AUTO_LIAB_BI" (Bodily Injury)
    - Use coverage_code="AUTO_LIAB_PD" (Property Damage)
- Uninsured/Underinsured Motorist:
    - Use family="uninsured_motorist" or "underinsured_motorist"
    - NEVER use family="auto_liability" for these.

IMPORTANT GUARDRAIL:
- If a coverage includes BOTH per-person language AND CSL language (e.g. "$1,000,000 CSL with $25k BI"), 
  you MUST treat it as SPLIT unless the section title explicitly says "Combined Single Limit".
- If you find ANY per-person wording within the liability section, default to coverage_code="AUTO_LIAB_BI".
- **FORBIDDEN**: Do not extract "Not Purchased" coverages as 0 or null. Omit them entirely.

FORMATTING:
- Dates: YYYY-MM-DD
- Integers: Raw numbers (no commas)
"""
        
        # 3. Attempt extraction
        response = None
        last_error = None
        for model_name in model_candidates:
            print(f"Attempting generation with model: {model_name}")
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    [sample_file, ontology_instruction],
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        response_schema=ONTOLOGY_AWARE_SCHEMA
                    )
                )
                print(f"Success with {model_name}")
                break 
            except Exception as e:
                print(f"Failed with {model_name}: {e}")
                last_error = e
        
        if not response:
            print("All model attempts failed.")
            if last_error:
                raise last_error
        
        # 4. Parse & Normalize
        try:
            result = json.loads(response.text)
            
            # Universal Normalization via Ontology
            
            # Filter and Validate Coverages
            valid_coverages = []
            for c in result.get("coverages", []):
                # 1. Registry Parity (Family, Structure, Allowed Fields)
                is_valid, msg = validate_coverage(c)
                if not is_valid:
                    print(f"Skipping invalid coverage (Ontology): {msg}")
                    continue
                
                # 2. Policy-Type Context (Cross-check with classification)
                if not is_coverage_allowed_for_policy_type(c["coverage_code"], policy_type):
                    print(f"Skipping invalid coverage (Policy Type Context): {c['coverage_code']} not allowed for {policy_type}")
                    continue
                    
                valid_coverages.append(c)
            
            # Strict Update: Only keep valid coverages
            result["coverages"] = valid_coverages
            
            # Sanity Checks
            is_sane, sanity_msg = perform_extraction_sanity_checks(result, policy_type)
            if not is_sane:
                print("Extraction failed sanity checks. Discarding result.")
                return None, None, sanity_msg
            
            # Universal Normalization via Ontology
            raw_summary = summarize_auto_liability(valid_coverages)
            if raw_summary:
                # presentation formatting
                result["policy"]["liability_limit"] = format_liability_limit(raw_summary)

            # DERIVED FLAGS: Calculate purely from valid coverages (Ignore Model Hallucinations)
            has_auto_liab = any(c.get("family") == "auto_liability" for c in valid_coverages)
            has_gl = any(c.get("family") == "general_liability" for c in valid_coverages)
            has_comp_coll = any(c.get("family") == "physical_damage" for c in valid_coverages)
            
            result["policy"]["has_auto_liability"] = has_auto_liab
            result["policy"]["has_general_liability"] = has_gl
            result["policy"]["has_full_collision"] = has_comp_coll

            result['classification'] = classification
            return result, response.usage_metadata, None
        except json.JSONDecodeError: 
            # Fallback for removing markdown code blocks if they slip through (rare with schema)
            clean_text = response.text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            try:
                return json.loads(clean_text), response.usage_metadata, None
            except:
                print(f"Failed to decode JSON: {response.text}")
                return None, None, "JSON Decode Error"
            
    finally:
        # Cleanup
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
