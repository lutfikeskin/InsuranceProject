import sys
import os
import time
from dotenv import load_dotenv
from sqlalchemy import text

# Add project root to path
sys.path.append(os.getcwd())

from google import genai
from core.database import init_db, get_session
import core.history_model # Registers PolicyHistory
from core.services import UsageService

def audit_token_accuracy():
    print("Locked & Loaded: Starting Token Accuracy Audit...")
    
    # 1. Setup
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        try:
            import tomllib
            with open(".streamlit/secrets.toml", "rb") as f:
                secrets = tomllib.load(f)
                api_key = secrets.get("GEMINI_API_KEY")
        except: pass

    if not api_key:
        print("Error: No API Key found.")
        return

    client = genai.Client(api_key=api_key)
    
    db_engine = init_db()
    session = get_session(db_engine)
    usage_service = UsageService(session)

    # 2. Get Baseline
    print("\n--- Step 1: Baseline Check ---")
    # Clean test data if needed? No, just append.
    
    # 3. Perform Raw API Call (The "Generic Truth")
    print("\n--- Step 2: Generating 'Truth' (Raw API Call) ---")
    prompt = "Reply with exactly one word: 'Confirmed'."
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
    except Exception as e:
        print(f"API Call Failed: {e}")
        return

    if not response.usage_metadata:
        print("CRITICAL FAILURE: API did not return usage metadata.")
        return

    api_input = response.usage_metadata.prompt_token_count
    api_output = response.usage_metadata.candidates_token_count
    
    print(f"API REPORTED: Input={api_input}, Output={api_output}")

    # 4. Log to System (The "Pipeline Test")
    print("\n--- Step 3: Logging to Database ---")
    usage_service.log_usage(
        model_name="audit-test-model",
        input_tokens=api_input,
        output_tokens=api_output,
        request_type="audit_verification"
    )
    
    # 5. Verify Database Record (The "Proof")
    print("\n--- Step 4: Verifying Database Integrity ---")
    # Fetch last record
    last_record = session.execute(
        text("SELECT input_tokens, output_tokens, request_type FROM api_usage WHERE request_type='audit_verification' ORDER BY id DESC LIMIT 1")
    ).fetchone()
    
    if not last_record:
        print("FAILURE: No record found in Database!")
        return
        
    db_input = last_record[0]
    db_output = last_record[1]
    
    print(f"DB RECORDED:  Input={db_input}, Output={db_output}")
    
    # 6. Assertion
    if db_input == api_input and db_output == api_output:
        print("\n✅ SUCCESS: Database matches API Truth 100%.")
        print("Token tracking is VERIFIED ACCURATE.")
    else:
        print("\n❌ FAILURE: Discrepancy detected!")
        print(f"Diff: Input {db_input-api_input}, Output {db_output-api_output}")

if __name__ == "__main__":
    audit_token_accuracy()
