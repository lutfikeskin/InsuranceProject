import os
import sys
from modules.extraction.pipeline import GeminiExtractionPipeline
from core.database import create_engine, get_session
from core.services import UsageService
import json

def verify_liberty():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not set in environment.")
        return

    file_path = "assets/TestPolicies/Libery Mutual Personal Auto.pdf"
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        return

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    pipeline = GeminiExtractionPipeline(api_key=api_key)
    print("Running extraction on Liberty Mutual...")
    
    # We use force_refresh=True to bypass the cache (even though we incremented v7)
    result, usage, error = pipeline.run(file_bytes, force_refresh=True)

    if error:
        print(f"Extraction failed: {error}")
        return

    print("\n--- EXTRACTION SUCCESS ---")
    pol = result.get("policy", {})
    print(f"Policy Number: {pol.get('policy_number')}")
    print(f"Effective Date: {pol.get('effective_date')}")
    print(f"Carrier: {pol.get('carrier_name')}")
    print(f"Premium: {pol.get('premium')}")
    
    covs = result.get("coverages", [])
    print(f"Coverages Found: {len(covs)}")
    for c in covs[:5]:
        print(f"  - {c.get('coverage_code')}: {c.get('display_name')}")

    vehs = result.get("vehicles", [])
    print(f"Vehicles Found: {len(vehs)}")
    
    drvs = result.get("drivers", [])
    print(f"Drivers Found: {len(drvs)}")

if __name__ == "__main__":
    verify_liberty()
