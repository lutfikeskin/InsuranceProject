import os
import sys

# Ensure we can import from the project root
sys.path.append(os.getcwd())

from extractor import process_pdf
from database import init_db

# We need a sample PDF to test. 
# We'll rely on one of the existing PDFs in the directory or create a dummy one if needed.
# Let's try to use 'test_filled_coi.pdf' if it exists, or 'COI Example.pdf'.

import argparse

TEST_PDF = "COI Example.pdf"

def test_pipeline():
    parser = argparse.ArgumentParser(description="Verify Extraction Pipeline")
    parser.add_argument("--api_key", required=True, help="Gemini API Key")
    args = parser.parse_args()

    if not os.path.exists(TEST_PDF):
        print(f"Test file {TEST_PDF} not found. Skipping test.")
        return

    print(f"Testing extraction pipeline with {TEST_PDF}...")
    
    with open(TEST_PDF, "rb") as f:
        file_bytes = f.read()

    try:
        result, usage, error = process_pdf(file_bytes, args.api_key)
        
        if error:
            print(f"❌ Pipeline Failed: {error}")
        else:
            print("✅ Pipeline Success!")
            print(f"Policy Type: {result.get('classification', {}).get('policy_type')}")
            print(f"Coverages Found: {len(result.get('coverages', []))}")
            print(f"Vehicles Found: {len(result.get('vehicles', []))}")
            print(f"Drivers Found: {len(result.get('drivers', []))}")
            if usage:
                print(f"Token Usage: {usage}")

    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    test_pipeline()
