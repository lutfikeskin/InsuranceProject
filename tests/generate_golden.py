import sys
import os
import json
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.extraction import process_pdf
from core.database import init_db # Just to ensure DB setup if needed
from core.logger import logger

def generate_golden(pdf_path, output_path=None, api_key=None):
    """
    Runs extraction on a PDF and saves the result as a 'Golden' JSON template.
    User should inspect and manually correct this JSON to establish ground truth.
    """
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        return

    print(f"Processing {pdf_path}...")
    
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    data, usage, error = process_pdf(file_bytes, api_key=api_key)
    
    if error:
        print(f"Extraction Failed: {error}")
        return

    if not output_path:
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        output_path = os.path.join(os.path.dirname(pdf_path), f"{base_name}.json")

    with open(output_path, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4)

    print(f"✅ Success! Golden template saved to: {output_path}")
    print("👉 ACTION REQUIRED: Open this JSON file and manually verify/correct the values to establish ground truth.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Golden JSON from PDF")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument("--key", help="Gemini API Key (optional, can read from env)", default=None)
    
    args = parser.parse_args()
    
    api_key = args.key
    if not api_key:
        try:
            with open(".streamlit/secrets.toml", "r") as f:
                for line in f:
                    if "GEMINI_API_KEY" in line:
                        api_key = line.split('=')[1].strip().strip('"')
                        break
        except:
            pass
            
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        print("Error: API Key required. Pass with --key or ensure it's in env/secrets.")
        sys.exit(1)

    generate_golden(args.pdf_path, api_key=api_key)
