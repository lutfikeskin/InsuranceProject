import pytest
import os
import json
import glob
from modules.extraction import process_pdf
from core.logger import logger

# Path to Golden Data
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

def normalize(val):
    """Normalize strings for comparison (ignore case, whitespace, currency symbols)"""
    if not isinstance(val, str):
        return val
    return val.lower().strip().replace("$", "").replace(",", "")

def compare_dicts(extracted, golden, path=""):
    """Recursively checks if extracted data matches golden expectation."""
    errors = []
    
    if isinstance(golden, dict):
        for k, v in golden.items():
            # Skip dynamic/unimportant fields
            if k in ["page_dimensions", "file_hash", "usage_metadata", "timestamp", "field_locations", "confidence"]:
                continue
                
            curr_path = f"{path}.{k}" if path else k
            
            # Check existence
            if k not in extracted:
                # If golden is None/Empty, it's okay if extracted is missing
                if not v: continue 
                errors.append(f"Missing Key: {curr_path}")
                continue
            
            extracted_val = extracted[k]
            
            # Recursive Deep Dive
            sub_errors = compare_dicts(extracted_val, v, curr_path)
            errors.extend(sub_errors)
            
    elif isinstance(golden, list):
        # List comparison is hard (order? items?). 
        # Simple check: Count match?
        if len(extracted) != len(golden):
             errors.append(f"List Count Variance at {path}: Exp {len(golden)}, Got {len(extracted)}")
    else:
        # Scalar Comparison
        n_ext = normalize(extracted)
        n_gold = normalize(golden)
        
        if n_ext != n_gold:
            errors.append(f"Mismatch at {path}: Exp '{golden}' vs Got '{extracted}'")

    return errors

def get_golden_pairs():
    """Finds all .pdf files that have a matching .json file."""
    pdfs = glob.glob(os.path.join(DATA_DIR, "*.pdf"))
    pairs = []
    for p in pdfs:
        json_path = p.replace(".pdf", ".json")
        if os.path.exists(json_path):
            pairs.append((p, json_path))
    return pairs

@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="Requires GEMINI_API_KEY env var")
@pytest.mark.parametrize("pdf_path,json_path", get_golden_pairs())
def test_extraction_accuracy(pdf_path, json_path):
    """
    Runs extraction on the PDF and compares against the JSON truth.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    # Run Extraction
    logger.info(f"Testing Accuracy on: {os.path.basename(pdf_path)}")
    data, usage, error = process_pdf(file_bytes, api_key=api_key)

    assert error is None, f"Extraction failed: {error}"

    # Load Golden Truth
    with open(json_path, "r", encoding='utf-8') as f:
        golden_data = json.load(f)

    # Compare
    # We mainly care about the 'policy' and 'coverages' keys
    
    # 1. Policy Details
    policy_errors = compare_dicts(data.get("policy", {}), golden_data.get("policy", {}), path="policy")
    
    assert not policy_errors, "\n".join(policy_errors)
    
    # 2. Coverages (Simplified check for now)
    # Checking specific codes presence could be complex, maybe trust list count for now?
    # Or strict comparison if user curated the JSON perfectly.
