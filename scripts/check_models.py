
import google.generativeai as genai
import os
import tomllib

def get_key():
    try:
        if os.path.exists(".streamlit/secrets.toml"):
            with open(".streamlit/secrets.toml", "rb") as f:
                secrets = tomllib.load(f)
                return secrets.get("GEMINI_API_KEY", "")
    except Exception as e:
        print(f"Error reading secrets: {e}")
    return os.getenv("GEMINI_API_KEY", "")

api_key = get_key()
if not api_key:
    print("No API Key found.")
    exit()

print(f"--- Diagnosing API Key: {api_key[:8]}... ---")
genai.configure(api_key=api_key)

try:
    print("Listing available models...")
    models = genai.list_models()
    count = 0
    for m in models:
        if 'generateContent' in m.supported_generation_methods:
            print(f"  - {m.name} ({m.display_name})")
            count += 1
    
    if count == 0:
        print("No models found with 'generateContent' support.")
except Exception as e:
    print(f"Error: {e}")
