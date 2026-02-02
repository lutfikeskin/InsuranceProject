
import os
import sys
import toml

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
import core.history_model # Crucial for Policy.req relationship
from modules.extraction.pipeline import GeminiExtractionPipeline

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    # Try streamlit secrets
    try:
        secrets_path = os.path.join(os.path.dirname(__file__), '..', '.streamlit', 'secrets.toml')
        if os.path.exists(secrets_path):
            data = toml.load(secrets_path)
            api_key = data.get("GEMINI_API_KEY")
    except Exception as e:
        print(f"Failed to read secrets: {e}")

if not api_key:
    print("Skipping test: No API Key found.")
    sys.exit(0)

def status_callback(msg):
    print(f"[Callback] {msg}")

pipeline = GeminiExtractionPipeline(api_key=api_key)

# Test file
pdf_path = r"assets\TestPolicies\Target Memo Sep 23.pdf"

if not os.path.exists(pdf_path):
    print(f"File not found: {pdf_path}")
    sys.exit(1)

with open(pdf_path, "rb") as f:
    file_bytes = f.read()

print(f"Running extraction on {pdf_path} ({len(file_bytes)} bytes)...")

# Force Refresh to bypass local disk cache (ExtractionCache)
result, usage, err = pipeline.run(file_bytes, status_callback=status_callback, force_refresh=True)

if err:
    print(f"Error: {err}")
else:
    print("Success!")
    print("Usage Metadata:", usage)
    
    # Check Result Keys
    print("Extracted Keys:", result.keys())
    if "policy" in result:
        print("Policy Number:", result["policy"].get("policy_number"))
        print("Insured:", result["policy"].get("insured_name"))
    
    print("Coverages Found:", len(result.get("coverages", [])))
    print("Vehicles Found:", len(result.get("vehicles", [])))

