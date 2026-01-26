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
You are an Insurance Underwriter. Extract data from this policy PDF into strict JSON.
Rules:
1. Identify Carrier, Account Type, Premium Amount, and State of Policy.
2. Extract the "Financial Responsible Name" from the "Financial Responsibility Information" section. Look for the CUSTOMER'S PERSONAL NAME (e.g. "John Doe") listed in this section, not the insurance company or state agency.
3. Extract all Vehicles with VINs (17 chars).
4. Extract Coverages. SPECIFICALLY look for:
    - Liability Limit (Combined Single Limit or Split). EXTRACT ONLY THE AMOUNT (e.g. "$1,000,000"), do not include text like "Combined Single Limit" or "CSL".
    - General Liability Limit. EXTRACT ONLY THE AMOUNT (e.g. "$1,000,000"), do not include text like "Combined Single Limit" or "CSL".
    - Cargo Limit (Motor Truck Cargo) AND Deductible (e.g. "1000 ded"). EXTRACT ONLY THE AMOUNT for the limit.
    - Collision Coverage: Look for "Comprehensive", "Collision", "Comp/Coll", or "Physical Damage". If ANY vehicle has this coverage, has_full_collision is true.
    - EXTRACT "naic_number" for the Carrier if visible (usually near Carrier Name or in Insurer section).
    - Determine if "has_general_liability" is TRUE (look for General Liability section limits/premium).
    - Determine if "has_auto_liability" is TRUE (look for Auto section limits/premium, this is an alternative way of looking for the Liability).
    - Extract ALL drivers listed on the policy schedule or driver list. Capture their full names and license numbers if available.
5. JSON Structure:
{
  "policy": {
    "carrier_name": str,
    "naic_number": str, 
    "policy_number": str, 
    "effective_date": "YYYY-MM-DD", 
    "expiration_date": "YYYY-MM-DD", 
    "account_type": "Personal|Commercial", 
    "insured_name": str, 
    "insured_address": str,
    "insured_city": str,
    "insured_state_code": str,
    "insured_zip": str,
    "business_name": str,
    "premium": str,
    "state": str,
    "financial_responsibility_name": str,
    "liability_limit": str,
    "cargo_limit": str,
    "cargo_deductible": str,
    "has_full_collision": bool,
    "has_general_liability": bool,
    "has_auto_liability": bool
  },
  "vehicles": [{"year": int, "make": str, "model": str, "vin": str, "gvw": int, "type": str}],
  "coverages": [{"type": str, "limit_person": int, "limit_accident": int, "deductible": int}],
  "drivers": [{"full_name": str, "license_number": str, "is_excluded": bool}]
}
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
