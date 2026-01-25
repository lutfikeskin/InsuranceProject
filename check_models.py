import google.generativeai as genai
import os
import toml

# Load secrets
try:
    secrets = toml.load(".streamlit/secrets.toml")
    api_key = secrets.get("GEMINI_API_KEY")
    if not api_key:
        print("API Key not found in secrets.")
        exit(1)
except Exception as e:
    print(f"Error loading secrets: {e}")
    exit(1)

genai.configure(api_key=api_key)

print("Listing available models...")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"Error listing models: {e}")
