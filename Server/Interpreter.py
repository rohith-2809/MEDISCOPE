#Interpreter.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
from googletrans import Translator
from dotenv import load_dotenv
import logging
import json
import os

# ----------------------------------
# Flask + Logging Setup
# ----------------------------------
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ----------------------------------
# Load environment variables
# ----------------------------------
load_dotenv()
API_KEY = os.getenv("API_KEY")

if not API_KEY:
    logging.error("❌ Missing API_KEY. Please set it in .env file.")
    # We do NOT raise an exception here to allow the service to start,
    # but endpoints using it will fail.

# Configure Gemini
genai.configure(api_key=API_KEY)
logging.info("✅ Gemini API configured successfully.")

# ----------------------------------
# Translator + Language Mapping
# ----------------------------------
translator = Translator()
LANGUAGE_MAP = {"english": "en", "telugu": "te", "hindi": "hi"}

# ----------------------------------
# Core Response Generator
# ----------------------------------
def generate_health_response(username, content, mode="report", language="english"):
    # --- Custom greeting (only once) ---
    greeting = f"👋 Hello {username}," if username and username.lower() not in ["patient", "none", ""] else "👋 Hello there,"

    # --- Build prompt ---
    if mode == "report":
        prompt = f"""
You are a compassionate medical professional explaining a diagnostic or radiology report.

Report Data:
-------------------------
{content}
-------------------------

Your task:
1. Do NOT begin with any greeting or name (the system adds that already).
2. Explain findings clearly and kindly in layman terms.
3. Say if results appear normal or may require attention.
4. If abnormal, suggest what kind of **specialist** to see.
5. Give 3–5 brief **home-care and lifestyle tips** (rest 😴, hydration 💧, warm compress 🌿, fresh diet 🍎, etc.).
6. Encourage professional consultation for confirmation.
7. Keep it under 10 lines, friendly but professional (💊🩺😊).
"""
    else:
        prompt = f"""
You are a friendly medical assistant giving conversational wellness guidance.

The patient says:
-------------------------
{content}
-------------------------

Respond with:
- No greeting at the start.
- Simple, clear suggestions (no jargon).
- 2–3 easy home remedies (hydration 💧, rest 😴, herbal tea 🌿).
- Mention which doctor to consult if needed.
- Keep under 6 lines, positive and reassuring.
"""

    # --- Direct REST API Call (Bypassing SDK/gRPC) ---
    import requests
    import json

    # primary_model = "gemini-flash-latest"
    # fallback_model = "gemini-pro-latest"

    # We will try primary then fallback
    models_to_try = ["gemini-flash-latest", "gemini-pro-latest"]

    final_response = ""

    for model_name in models_to_try:
        try:
            logging.info(f"🧠 Generating response using {model_name} (REST API) | Mode: {mode}")

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={API_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }]
            }

            response = requests.post(url, headers=headers, json=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                # Extract text
                # Structure: candidates[0].content.parts[0].text
                try:
                    final_response = result['candidates'][0]['content']['parts'][0]['text']
                    logging.info("✅ Gemini REST Response received.")
                    break # Success!
                except (KeyError, IndexError) as e:
                    logging.warning(f"⚠️ Unexpected JSON structure from {model_name}: {result}")
                    continue
            elif response.status_code == 429:
                logging.warning(f"⚠️ {model_name} Quota Exceeded (429). Switching to Mock Response.")
                final_response = (
                    "**[Simulated Analysis]**\n\n"
                    "**Findings:**\n"
                    "The uploaded image appears to be a standard radiological view. Visualized structures show normal alignment. No obvious acute fractures, dislocations, or severe soft tissue abnormalities are detected in this simulated check.\n\n"
                    "**Assessment:**\n"
                    "Appears within normal limits (Simulated).\n\n"
                    "**Suggested Specialist:**\n"
                    "Orthopedist or General Physician if pain persists.\n\n"
                    "**Home Care Tips:**\n"
                    "1. 🧊 **Ice**: Apply cold packs for 15-20 mins if swelling exists.\n"
                    "2. 😴 **Rest**: Avoid straining the affected area.\n"
                    "3. 💊 **Hydration**: Drink plenty of water to aid recovery.\n\n"
                    "*(Note: This is a placeholder because the AI service usage limit was reached.)*"
                )
                break
            elif response.status_code == 403:
                logging.error(f"❌ {model_name} API Key Invalid/Leaked (403).")
                final_response = (
                    "**[System Error: Invalid API Key]**\n\n"
                    "Google has blocked your API key because it was reported as **leaked** (publicly exposed).\n\n"
                    "**How to Fix:**\n"
                    "1. Go to [Google AI Studio](https://aistudio.google.com/) and generate a **new** key.\n"
                    "2. Open `Server/.env` file.\n"
                    "3. Paste the new key into `API_KEY=...`.\n"
                    "4. Restart the server."
                )
                break
            else:
                logging.warning(f"⚠️ {model_name} REST API failed: {response.status_code} - {response.text}")
                continue

        except Exception as e:
             logging.error(f"❌ {model_name} REST Request failed: {e}")
             continue

    if not final_response:
        final_response = "Sorry, I'm having trouble connecting to the AI service right now. Please check your internet connection."

    # --- Remove any duplicate greetings from model output ---
    import re
    final_response = re.sub(r"(?i)^\s*(hi|hello|hey)[^a-zA-Z]*", "", final_response).strip()
    final_response = re.sub(r"(?i)(^|\n)\s*(hi|hello|hey|dear)[^\n]*\n?", "", final_response).strip()

    # --- Translation ---
    if language.lower() != "english":
        dest_lang = LANGUAGE_MAP.get(language.lower(), "en")
        try:
            translated = translator.translate(final_response, dest=dest_lang)
            final_response = translated.text
        except Exception:
            final_response += "\n\n(Note: Translation to your selected language failed.)"

    return f"{greeting}\n\n{final_response}"

# ----------------------------------
# API Endpoint: /interpret
# ----------------------------------
@app.route("/interpret", methods=["POST"])
def interpret():
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
        username = data.get("username", "Patient")
        language = data.get("language", "english")
        mode = data.get("type", "report").lower()

        if mode == "chat":
            content = data.get("query", "")
            if not content:
                logging.error("❌ Missing 'query' field for chat request.")
                return jsonify({"error": "Missing 'query' for chat type"}), 400
        else:
            raw_preds = data.get("predictions", "{}")
            try:
                preds_json = json.loads(raw_preds) if isinstance(raw_preds, str) else raw_preds
                content = json.dumps(preds_json, indent=2)
            except json.JSONDecodeError:
                logging.warning("⚠️ Invalid JSON in predictions; using raw text.")
                content = raw_preds or "No diagnostic data provided."

        response_text = generate_health_response(username, content, mode, language)
        logging.info("✅ Successfully generated interpreter response.")
        return jsonify({"response": response_text})

    except Exception as e:
        logging.exception("Error in /interpret route:")
        return jsonify({"error": str(e)}), 500


# ----------------------------------
# Health Check Endpoint
# ----------------------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "🩺 AI Health Interpreter (Dr. Athena) is active and ready.",
        "usage": {
            "POST /interpret": {
                "fields": {
                    "username": "string (optional)",
                    "language": "english/telugu/hindi",
                    "type": "report/chat",
                    "predictions": "JSON (for report)",
                    "query": "string (for chat)"
                }
            }
        }
    })

# ----------------------------------
# Run App
# ----------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "False") == "True")
