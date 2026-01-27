from google import genai
from google.genai import types
import os
import json
import tempfile
import time
import hashlib
import io
import pypdf
from coverage_ontology import (
    COVERAGE_REGISTRY, 
    summarize_auto_liability, 
    summarize_general_liability,
    summarize_cargo,
    validate_coverage, 
    is_coverage_allowed_for_policy_type,
    format_liability_limit
)

# --- CONFIGURATION ---
ROUTING_MODEL = "gemini-2.0-flash"
EXTRACTION_MODEL = "gemini-2.5-flash"

# --- SCHEMAS ---

CLASSIFICATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "policy_type": {
            "type": "STRING",
            "enum": [
                "personal_auto", "commercial_auto", "general_liability", "bop",
                "commercial_package", "umbrella", "motor_truck_cargo", "unknown"
            ]
        },
        "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "signals": {"type": "ARRAY", "items": {"type": "STRING"}}
    },
    "required": ["policy_type", "confidence"]
}

SECTION_LOCATOR_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "declarations": {"type": "ARRAY", "items": {"type": "INTEGER"}}, # Page numbers
        "coverages": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "vehicles": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "drivers": {"type": "ARRAY", "items": {"type": "INTEGER"}}
    },
    "required": ["declarations", "coverages"]
}

DECLARATIONS_SCHEMA = {
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
        "field_locations": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "field": {"type": "STRING"},
                    "page_number": {"type": "INTEGER"},
                    "bbox": {
                        "type": "ARRAY", 
                        "items": {"type": "INTEGER"},
                        "description": "[ymin, xmin, ymax, xmax] in 0-1000 scale"
                    }
                }
            }
        }
    }
}

COVERAGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
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
                            "auto_liability", "uninsured_motorist", "underinsured_motorist",
                            "physical_damage", "general_liability", "cargo",
                            "medical_payments", "pip", "other"
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
                    "deductible": {"type": "INTEGER"},
                    "location": {
                        "type": "OBJECT",
                        "properties": {
                            "page_number": {"type": "INTEGER"},
                            "bbox": {"type": "ARRAY", "items": {"type": "INTEGER"}}
                        }
                    }
                }
            }
        }
    }
}

VEHICLE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
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
        }
    }
}

DRIVER_SCHEMA = {
    "type": "OBJECT",
    "properties": {
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

# --- CACHING UTILS ---

def get_pdf_hash(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()

def get_page_dimensions(file_bytes):
    try:
        pdf = pypdf.PdfReader(io.BytesIO(file_bytes))
        dims = []
        for page in pdf.pages:
            dims.append({"width": float(page.mediabox.width), "height": float(page.mediabox.height)})
        return dims
    except Exception as e:
        print(f"Error getting dimensions: {e}")
        return []

# In-memory cache for simplicity in this session
_CACHE = {} 

def get_client(api_key):
    return genai.Client(api_key=api_key)

# --- PIPELINE STEPS ---

def classify_policy(client, raw_pdf_part):
    """Step 1: Fast Classification"""
    prompt = """
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
    
    response = client.models.generate_content(
        model=ROUTING_MODEL,
        contents=[raw_pdf_part, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CLASSIFICATION_SCHEMA
        )
    )
    return json.loads(response.text)

def locate_sections(client, raw_pdf_part):
    """Step 2: Locate Sections (Page Numbers)"""
    prompt = """
    Analyze the PDF and identify the page numbers for the following sections:
    1. Declarations (Policy info, dates, insured)
    2. Coverages (Limits, deductibles)
    3. Vehicles (Schedule of vehicles)
    4. Drivers (List of drivers)

    Return a JSON object with lists of 1-based page numbers for each section. 
    If a section is missing, return an empty list.
    """
    
    response = client.models.generate_content(
        model=ROUTING_MODEL,
        contents=[raw_pdf_part, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SECTION_LOCATOR_SCHEMA
        )
    )
    return json.loads(response.text)

def extract_declarations(client, raw_pdf_part):
    """Step 3a: Extract Declarations"""
    prompt = """
    Extract core policy declarations information.
    - Carrier name, Policy Number, NAIC
    - Effective and Expiration Dates (YYYY-MM-DD)
    - Insured Name, Address, City, State, Zip
    - Premium Amount
    
    For each extracted field, identify its location in the document.
    Return 'field_locations' array containing {field, page_number, bbox}.
    bbox format: [ymin, xmin, ymax, xmax] (0-1000 scale).
    """
    response = client.models.generate_content(
        model=EXTRACTION_MODEL,
        contents=[raw_pdf_part, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DECLARATIONS_SCHEMA
        )
    )
    return json.loads(response.text)

def extract_coverages(client, raw_pdf_part, policy_type):
    """Step 3b: Extract Coverages with Ontology"""
    registry_text = json.dumps(COVERAGE_REGISTRY, indent=2)
    prompt = f"""
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
    response = client.models.generate_content(
        model=EXTRACTION_MODEL,
        contents=[raw_pdf_part, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=COVERAGE_SCHEMA
        )
    )
    return json.loads(response.text)

def extract_vehicles(client, raw_pdf_part):
    """Step 3c: Extract Vehicles"""
    prompt = "Extract the schedule of covered vehicles. Include Year, Make, Model, VIN, GVW."
    response = client.models.generate_content(
        model=EXTRACTION_MODEL,
        contents=[raw_pdf_part, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VEHICLE_SCHEMA
        )
    )
    return json.loads(response.text)

def extract_drivers(client, raw_pdf_part):
    """Step 3d: Extract Drivers"""
    prompt = "Extract the list of drivers. Mark 'is_excluded' as true if explicitly stated."
    response = client.models.generate_content(
        model=EXTRACTION_MODEL,
        contents=[raw_pdf_part, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DRIVER_SCHEMA
        )
    )
    return json.loads(response.text)

# --- ASSEMBLY & VALIDATION ---

def perform_extraction_sanity_checks(coverages, policy_type):
    """Logical rules validation."""
    # 1. At least one Auto Liability for Auto Policies
    if policy_type in ["personal_auto", "commercial_auto"]:
        has_liab = any(c.get("family") == "auto_liability" for c in coverages)
        if not has_liab:
            msg = "SANITY CHECK FAILED: No auto liability found for auto policy."
            print(msg)
            return False, msg
            
    # 2. CSL and Split BI must never coexist in Auto Liab (CSL Supremacy Enforcement)
    auto_liabs = [c for c in coverages if c.get("family") == "auto_liability"]
    has_csl = any(c.get("limit_structure") == "csl" for c in auto_liabs)
    has_split = any(c.get("limit_structure") == "split" for c in auto_liabs)
    
    if has_csl and has_split:
        print("WARNING: CSL Supremacy Violation. Pruning Split limits in favor of CSL.")
        # Filter out split limits
        coverages[:] = [c for c in coverages if not (c.get("family") == "auto_liability" and c.get("limit_structure") == "split")]
        
    return True, None

def process_pdf(file_bytes, api_key):
    """
    Orchestrates the modular extraction pipeline.
    """
    # Initialize Client
    client = get_client(api_key)
    
    # 1. Caching & File Prep
    file_hash = get_pdf_hash(file_bytes)
    cached_classification = _CACHE.get(f"{file_hash}_class")
    
    # Prepare types.Part for direct binary transmission (faster, no upload needed for small files)
    # Note: For very large files > 20MB, we should use the File API, but for policies, this is perfect.
    raw_pdf_part = types.Part.from_bytes(data=file_bytes, mime_type='application/pdf')

    try:
        # 2. Classification
        if cached_classification:
            print("Using cached classification.")
            classification = cached_classification
        else:
            print("Classifying policy...")
            classification = classify_policy(client, raw_pdf_part)
            _CACHE[f"{file_hash}_class"] = classification
            
        policy_type = classification['policy_type']
        if policy_type == "unknown":
            return None, None, "Unknown Policy Type"
            
        print(f"Policy Type: {policy_type}")

        # 3. Parallel/Sequential Extraction
        
        print("Extracting Declarations...")
        decs_data = extract_declarations(client, raw_pdf_part)
        
        print("Extracting Coverages...")
        cov_data = extract_coverages(client, raw_pdf_part, policy_type)
        
        vehicles_data = {"vehicles": []}
        drivers_data = {"drivers": []}
        
        if policy_type in ["personal_auto", "commercial_auto", "motor_truck_cargo", "umbrella"]:
            print("Extracting Vehicles...")
            vehicles_data = extract_vehicles(client, raw_pdf_part)
            print("Extracting Drivers...")
            drivers_data = extract_drivers(client, raw_pdf_part)

        # 4. Assembly & Normalization
        final_result = {
            "policy": decs_data,
            "coverages": [],
            "vehicles": vehicles_data.get("vehicles", []),
            "drivers": drivers_data.get("drivers", []),
            "classification": classification,
            "page_dimensions": get_page_dimensions(file_bytes)
        }
        
        # Validate Coverages
        print(f"DEBUG: Raw extracted coverages: {json.dumps(cov_data.get('coverages', []), indent=2)}")
        
        for c in cov_data.get("coverages", []):
            is_valid, msg = validate_coverage(c)
            if not is_valid:
                print(f"Dropping invalid coverage (Registry): {msg}")
                continue
            
            # Check if allowed for policy type
            if not is_coverage_allowed_for_policy_type(c["coverage_code"], policy_type):
                print(f"Dropping disallowed coverage (Policy Type '{policy_type}'): {c['coverage_code']}")
                continue
                
            final_result["coverages"].append(c)
            
        print(f"DEBUG: Final valid coverages: {len(final_result['coverages'])}")
            
        # Sanity Checks & Fixups
        is_sane, msg = perform_extraction_sanity_checks(final_result["coverages"], policy_type)
        if not is_sane:
             return None, None, msg
             
        # Summarize Limits
        raw_summary = summarize_auto_liability(final_result["coverages"])
        if raw_summary:
            final_result["policy"]["liability_limit"] = format_liability_limit(raw_summary)

        raw_gl_summary = summarize_general_liability(final_result["coverages"])
        if raw_gl_summary:
            final_result["policy"]["general_liability_limit"] = format_liability_limit(raw_gl_summary)
            
        raw_cargo_summary = summarize_cargo(final_result["coverages"])
        if raw_cargo_summary:
             # simple formatting for now
             val = raw_cargo_summary["value"]
             final_result["policy"]["cargo_limit"] = f"${val:,}"
             if raw_cargo_summary.get("deductible"):
                  final_result["policy"]["cargo_deductible"] = str(raw_cargo_summary["deductible"])
            
        # Set Flags
        final_result["policy"]["has_auto_liability"] = any(c.get("family") == "auto_liability" for c in final_result["coverages"])
        final_result["policy"]["has_general_liability"] = any(c.get("family") == "general_liability" for c in final_result["coverages"])
        final_result["policy"]["has_full_collision"] = any(c.get("family") == "physical_damage" for c in final_result["coverages"])

        usage_metadata = {"total_token_count": "Aggregated"} 
        
        return final_result, usage_metadata, None

    except Exception as e:
        print(f"Pipeline Error: {e}")
        return None, None, str(e)
