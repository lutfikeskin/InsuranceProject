import google.generativeai as genai
import os
import json
import tempfile
import time

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
        
        system_instruction = """
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
  - Example: "Ford F-150" -> "Pickup"
  - Example: "Freightliner Cascadia" -> "Tractor"
  - Example: "Ford Transit" -> "Cargo Van"
  - Example: "Great Dane" -> "Trailer"
  - Example: "Freightliner M2" -> "Straight Truck" (or "Box Truck" if implied by context)
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
"""
        
        # Define Schema for strict JSON output
        response_schema = {
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

        # Attempt generation with fallbacks
        response = None
        last_error = None
        
        # Import streamlit here to avoid circular dependency at top level if possible, 
        # or just use print if st is not available, but we know we run in streamlit.
        import streamlit as st

        for model_name in model_candidates:
            print(f"Attempting generation with model: {model_name}")
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    [sample_file, system_instruction],
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        response_schema=response_schema
                    )
                )
                print(f"Success with {model_name}")
                st.toast(f"Success with {model_name}", icon="✅")
                break # Stop if successful
            except Exception as e:
                print(f"Failed with {model_name}: {e}")
                st.warning(f"Failed with {model_name}: {e}")
                last_error = e
                # Continue to next model
        
        if not response:
            print("All model attempts failed.")
            if last_error:
                raise last_error
        
        # Parse JSON - response_schema guarantees valid JSON structure
        try:
            result = json.loads(response.text)
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
