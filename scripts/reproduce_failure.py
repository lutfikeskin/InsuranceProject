import os
import sys
import json
# Add project root to pythonpath
sys.path.append(os.getcwd())

from core.history_model import PolicyHistory # FIX: Register model for SQLAlchemy
from modules.extraction.pipeline import GeminiExtractionPipeline
from modules.extraction.pdf_ops import PdfProcessor # Import PdfProcessor
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

def debug_extraction():
    pipeline = GeminiExtractionPipeline(api_key=api_key)
    
    file_path = r"c:\Users\Lutfi\Documents\InsuranceProject\assets\TestPolicies\ABC EXPRESS LLC-BLACK-SEA-GROUP-COI.pdf"
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, "rb") as f:
        file_bytes = f.read()
    
    print(f"DEBUG: Processing {file_path}")
    
    # Check text content
    import io, pypdf
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    if len(reader.pages) > 0:
        text = reader.pages[0].extract_text()
        print("-" * 50)
        print(f"DEBUG: START PDF TEXT CONTENT ({len(text)} chars)")
        print(text[:2000]) # First 2000 chars
        print("DEBUG: END PDF TEXT CONTENT")
        print("-" * 50)

    print("DEBUG: Force Refreshing to bypass cache...")
    
    # Force refresh = True
    result, usage, err = pipeline.run(file_bytes, force_refresh=True)
    
    if err:
        print(f"ERROR: {err}")
        return
        
    print("-" * 50)
    print("DEBUG: SCOUT MAP Keys:", result.get("scout_map", {}).keys())
    print("DEBUG: Scout Vehicles:", result.get("scout_map", {}).get("vehicle_schedule_signals"))
    print("-" * 50)
    print("DEBUG: EXTRACTED VEHICLES:")
    print(json.dumps(result.get("vehicles", []), indent=2))
    print("-" * 50)
    print("DEBUG: EXTRACTED DRIVERS:")
    print(json.dumps(result.get("drivers", []), indent=2))

if __name__ == "__main__":
    debug_extraction()
