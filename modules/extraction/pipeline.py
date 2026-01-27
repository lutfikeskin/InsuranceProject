from google import genai
from google.genai import types
import os
import json
import tempfile
import time
import hashlib
import io
import pypdf
import concurrent.futures
from core.coverage_ontology import (
    COVERAGE_REGISTRY, 
    summarize_auto_liability, 
    summarize_general_liability,
    summarize_cargo,
    validate_coverage, 
    is_coverage_allowed_for_policy_type,
    format_liability_limit
)

# Import schemas and prompts
from .schemas import (
    CLASSIFICATION_SCHEMA,
    SECTION_LOCATOR_SCHEMA,
    DECLARATIONS_SCHEMA,
    COVERAGE_SCHEMA,
    VEHICLE_SCHEMA,
    DRIVER_SCHEMA
)

from .prompts import (
    CLASSIFY_POLICY_PROMPT,
    LOCATE_SECTIONS_PROMPT,
    EXTRACT_DECLARATIONS_PROMPT,
    EXTRACT_VEHICLES_PROMPT,
    EXTRACT_DRIVERS_PROMPT,
    get_coverages_prompt
)

# --- CONFIGURATION ---
ROUTING_MODEL = "gemini-2.0-flash"
EXTRACTION_MODEL = "gemini-2.5-flash"

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
    response = client.models.generate_content(
        model=ROUTING_MODEL,
        contents=[raw_pdf_part, CLASSIFY_POLICY_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CLASSIFICATION_SCHEMA
        )
    )
    return json.loads(response.text)

def locate_sections(client, raw_pdf_part):
    """Step 2: Locate Sections (Page Numbers)"""
    response = client.models.generate_content(
        model=ROUTING_MODEL,
        contents=[raw_pdf_part, LOCATE_SECTIONS_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SECTION_LOCATOR_SCHEMA
        )
    )
    return json.loads(response.text)

def extract_declarations(client, raw_pdf_part):
    """Step 3a: Extract Declarations"""
    response = client.models.generate_content(
        model=EXTRACTION_MODEL,
        contents=[raw_pdf_part, EXTRACT_DECLARATIONS_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DECLARATIONS_SCHEMA
        )
    )
    return json.loads(response.text)

def extract_coverages(client, raw_pdf_part, policy_type):
    """Step 3b: Extract Coverages with Ontology"""
    registry_text = json.dumps(COVERAGE_REGISTRY, indent=2)
    prompt = get_coverages_prompt(registry_text, policy_type)
    
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
    response = client.models.generate_content(
        model=EXTRACTION_MODEL,
        contents=[raw_pdf_part, EXTRACT_VEHICLES_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VEHICLE_SCHEMA
        )
    )
    return json.loads(response.text)

def extract_drivers(client, raw_pdf_part):
    """Step 3d: Extract Drivers"""
    response = client.models.generate_content(
        model=EXTRACTION_MODEL,
        contents=[raw_pdf_part, EXTRACT_DRIVERS_PROMPT],
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

def process_pdf(file_bytes, api_key, status_callback=None):
    """
    Orchestrates the modular extraction pipeline.
    """
    # Initialize Client
    client = get_client(api_key)
    
    # 1. Caching & File Prep
    file_hash = get_pdf_hash(file_bytes)
    cached_classification = _CACHE.get(f"{file_hash}_class")
    
    # Prepare types.Part for direct binary transmission
    raw_pdf_part = types.Part.from_bytes(data=file_bytes, mime_type='application/pdf')

    try:
        # 2. Classification
        if cached_classification:
            print("Using cached classification.")
            if status_callback: status_callback(" Using cached classification")
            classification = cached_classification
        else:
            print("Classifying policy...")
            if status_callback: status_callback(" Classifying policy...")
            classification = classify_policy(client, raw_pdf_part)
            _CACHE[f"{file_hash}_class"] = classification
            
        policy_type = classification['policy_type']
        confidence = classification.get('confidence', 'unknown')
        if status_callback: status_callback(f" Policy Type: {policy_type.replace('_', ' ').title()} ({confidence})")

        if policy_type == "unknown":
            return None, None, "Unknown Policy Type"
            
        print(f"Policy Type: {policy_type}")

        # 3. Parallel Extraction
        print("Starting Parallel Extraction...")
        if status_callback: status_callback(" Starting Parallel Extraction...")
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Submit tasks
            future_decs = executor.submit(extract_declarations, client, raw_pdf_part)
            future_cov = executor.submit(extract_coverages, client, raw_pdf_part, policy_type)
            
            future_vehicles = None
            future_drivers = None
            
            if policy_type in ["personal_auto", "commercial_auto", "motor_truck_cargo", "umbrella"]:
                future_vehicles = executor.submit(extract_vehicles, client, raw_pdf_part)
                future_drivers = executor.submit(extract_drivers, client, raw_pdf_part)

            # Gather Results
            try:
                print("Waiting for Declarations...")
                decs_data = future_decs.result()
                if status_callback: status_callback(" Declarations extracted")
                
                print("Waiting for Coverages...")
                cov_data = future_cov.result()
                if status_callback: status_callback(" Coverages extracted")
                
                vehicles_data = {"vehicles": []}
                if future_vehicles:
                    print("Waiting for Vehicles...")
                    vehicles_data = future_vehicles.result()
                    if status_callback: status_callback(f" Extracted {len(vehicles_data.get('vehicles', []))} Vehicles")
                    
                drivers_data = {"drivers": []}
                if future_drivers:
                    print("Waiting for Drivers...")
                    drivers_data = future_drivers.result()
                    if status_callback: status_callback(f" Extracted {len(drivers_data.get('drivers', []))} Drivers")
                    
            except Exception as exc:
                print(f"Parallel Extraction failed: {exc}")
                raise exc

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
