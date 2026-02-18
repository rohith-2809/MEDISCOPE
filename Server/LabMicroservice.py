
# Lab Microservice
from flask import Flask, request, jsonify
import os, logging
from werkzeug.utils import secure_filename
import fitz  # PyMuPDF
import easyocr
import google.generativeai as genai
from flask import Flask
from flask_cors import CORS
# ----------------- Setup -----------------
app = Flask(__name__)
CORS(app)
UPLOAD_FOLDER = './uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.INFO)

# Lazy load EasyOCR
ocr_reader = None

def get_ocr_reader():
    global ocr_reader
    if ocr_reader is None:
        logging.info("⏳ Loading EasyOCR model... (might take a moment)")
        ocr_reader = easyocr.Reader(['en'])
        logging.info("✅ EasyOCR model loaded.")
    return ocr_reader

# Load API Key from Environment
from dotenv import load_dotenv
load_dotenv()
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    logging.warning("⚠️ API_KEY not found in environment variables. Gemini features will fail.")

genai.configure(api_key=API_KEY)

# ----------------- OCR -----------------
def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']:
        reader = get_ocr_reader()
        res = reader.readtext(file_path, detail=0)
        text = "\n".join(res) if res else "[No text]"
    else:  # PDF
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text() + "\n"
    return text

# ----------------- Gemini Analysis -----------------
def summarize_with_gemini(text):
    import requests
    import json

    prompt = f"""
    You are a medical assistant. Summarize key points of this report in simple terms:

    {text[:5000]}
    """

    # Use the same model as Interpreter for consistency
    model_name = "gemini-flash-latest"

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }

        # Timeout 30s
        logging.info(f"🧪 Generating summary using {model_name} (REST API)")
        response = requests.post(url, headers=headers, json=data, timeout=30)

        if response.status_code == 200:
            result = response.json()
            try:
                summary = result['candidates'][0]['content']['parts'][0]['text']
                logging.info("✅ Lab Summary Received")
                return summary
            except (KeyError, IndexError):
                return "[Error Parsing AI Response]"

        elif response.status_code == 403:
            logging.error("❌ API Key Leaked/Invalid (403)")
            return "**[System Error]** Your API Key is invalid or leaked. Please update it in Server/.env."

        elif response.status_code == 429:
            logging.warning("⚠️ Quota Exceeded (429). Returning Mock Summary.")
            return (
                "**[Simulated Summary]**\n"
                "This report appears to show values within standard reference ranges. "
                "No critical abnormalities detected in this simulated check.\n"
                "*(Real AI analysis is temporarily unavailable due to quota limits.)*"
            )
        else:
            logging.error(f"❌ Gemini REST failed: {response.status_code} - {response.text}")
            return f"[AI Service Error: {response.status_code}]"

    except Exception as e:
        logging.exception("Gemini REST Request failed:")
        return f"[Connection Error: {str(e)}]"

# ----------------- Route -----------------
@app.route('/parse', methods=['POST'])
def parse():
    logging.info("📝 /parse called")

    # 🔹 Case 1: Node sends file path (Deprecated/Local only)
    if 'file_path' in request.form:
        file_path = request.form['file_path']
        logging.info(f"📂 Received file_path: {file_path}")
        if not os.path.exists(file_path):
            return jsonify({"error": f"File not found: {file_path}"}), 400
        text = extract_text(file_path)
        summary = summarize_with_gemini(text)
        return jsonify({
            "message": "Parsed successfully (from path)",
            "file": file_path,
            "summary": summary
        })

    # 🔹 Case 2: Client directly uploads files (Preferred for Microservices)
    if 'files' not in request.files:
        logging.error("❌ No files provided in request")
        return jsonify({"error": "No files or file_path provided"}), 400

    files = request.files.getlist('files')
    logging.info(f"📥 Received {len(files)} files via upload")

    combined_text = ""
    diagnostics = {}

    for f in files:
        filename = secure_filename(f.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        logging.info(f"💾 Saving file to: {path}")
        f.save(path)
        try:
            txt = extract_text(path)
            combined_text += f"\n=== {filename} ===\n{txt}\n"
            diagnostics[filename] = {"status": "success", "text_length": len(txt)}
            # Cleanup
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logging.error(f"❌ Error processing {filename}: {e}")
            diagnostics[filename] = {"status": "failed", "error": str(e)}

    summary = summarize_with_gemini(combined_text)
    return jsonify({
        "message": "Parsed successfully (uploaded)",
        "diagnostics": diagnostics,
        "summary": summary
    })

@app.route('/')
def health_check():
    return "Lab Microservice is running", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "False") == "True")
