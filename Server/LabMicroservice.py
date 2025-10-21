from flask import Flask, request, jsonify
import os, logging
from werkzeug.utils import secure_filename
from flask_cors import CORS

# ----------------- Setup -----------------
app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = './uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.INFO)

# ----------------- Lazy OCR -----------------
ocr_reader = None
def get_ocr_reader():
    global ocr_reader
    if ocr_reader is None:
        import easyocr
        ocr_reader = easyocr.Reader(['en'], gpu=False)  # Render has no GPU
    return ocr_reader

# ----------------- Gemini API -----------------
import google.generativeai as genai
API_KEY = "AIzaSyDBfH2xSnbEQejRsjLGPlokpSGUIM0N4dA"
genai.configure(api_key=API_KEY)

def summarize_with_gemini(text):
    prompt = f"""
You are a medical assistant. Summarize key points of this report in simple terms:

{text[:5000]}  # limit to 5000 chars
"""
    try:
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        resp = model.generate_content(prompt)
        return resp.text.strip() if hasattr(resp, "text") else "[No summary]"
    except Exception as e:
        logging.exception("Gemini failed:")
        return f"Gemini failed: {str(e)}"

# ----------------- Text Extraction -----------------
def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']:
        reader = get_ocr_reader()
        res = reader.readtext(file_path, detail=0)
        text = "\n".join(res) if res else "[No text]"
    else:  # PDF
        import fitz  # PyMuPDF
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text() + "\n"
    return text

# ----------------- Routes -----------------
@app.route('/parse', methods=['POST'])
def parse():
    # Case 1: Node sends file path
    if 'file_path' in request.form:
        file_path = request.form['file_path']
        if not os.path.exists(file_path):
            return jsonify({"error": f"File not found: {file_path}"}), 400
        text = extract_text(file_path)
        summary = summarize_with_gemini(text)
        return jsonify({
            "message": "Parsed successfully (from path)",
            "file": file_path,
            "summary": summary
        })

    # Case 2: Client uploads files
    if 'files' not in request.files:
        return jsonify({"error": "No files or file_path provided"}), 400

    files = request.files.getlist('files')
    diagnostics = {}
    summaries = []

    for f in files:
        filename = secure_filename(f.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        f.save(path)
        try:
            txt = extract_text(path)
            diag = {"text_length": len(txt)}
            diagnostics[filename] = diag

            summary = summarize_with_gemini(txt)
            summaries.append(f"=== {filename} ===\n{summary}\n")

            # Optional: delete file after processing to save disk space
            os.remove(path)
        except Exception as e:
            diagnostics[filename] = {"error": str(e)}

    final_summary = "\n".join(summaries)

    return jsonify({
        "message": "Parsed successfully (uploaded)",
        "diagnostics": diagnostics,
        "summary": final_summary
    })

# ----------------- Main -----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
