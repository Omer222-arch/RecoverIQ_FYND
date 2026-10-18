import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

api_key = os.getenv("GEMINI_API_KEY")
model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

if not api_key:
    raise SystemExit("ERROR: GEMINI_API_KEY is missing from backend/.env")

print("Gemini API key loaded:", True)
print("Model:", model)
print("Testing Gemini connection...")

client = genai.Client(api_key=api_key)

try:
    response = client.models.generate_content(
        model=model,
        contents="Reply with exactly: ReCoverIQ connected",
    )

    print("SUCCESS:", response.text)

except Exception as exc:
    print("ERROR TYPE:", type(exc).__name__)
    print("ERROR DETAILS:", str(exc))

finally:
    client.close()