import os
import json
import logging
import numpy as np
from PIL import Image, ImageOps, ImageEnhance, ExifTags
import tensorflow as tf
from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
from io import BytesIO
import requests

# ============================================================
# ✅ CONFIG & LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s — %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("MEDISCOPE_XRAY_SERVICE")

gpus = tf.config.experimental.list_physical_devices('GPU')
if gpus:
    try:
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)
        logger.info("✅ GPU memory growth enabled.")
    except RuntimeError as e:
        logger.error(f"GPU setup error: {e}")

# ============================================================
# 📦 MODEL CONFIG
# ============================================================
MODEL_URL = "https://huggingface.co/Nikhil2104/MEDISCOPE/resolve/main/final_best_model.keras"
MODEL_PATH = "final_best_model.keras"
IMG_SIZE = (160, 160)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp'}

# ============================================================
# ⬇️ MODEL DOWNLOAD
# ============================================================
if not os.path.exists(MODEL_PATH):
    logger.info("⏳ Downloading model from Hugging Face...")
    try:
        response = requests.get(MODEL_URL, timeout=60)
        response.raise_for_status()
        with open(MODEL_PATH, "wb") as f:
            f.write(response.content)
        logger.info("✅ Model downloaded successfully.")
    except Exception as e:
        logger.exception("❌ Model download failed.")
        raise

# ============================================================
# 🧠 LOAD MODEL
# ============================================================
logger.info("⏳ Loading TensorFlow model...")
try:
    model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    logger.info("✅ Model loaded successfully.")
except Exception as e:
    logger.exception("❌ Model loading failed.")
    raise

class_names = [
    "Brain_Hemorrhage", "Brain_Normal", "Brain_Tumor",
    "Chest_PNEUMONIA", "Chest_Xray_Normal",
    "Kidney_Normal", "Kidney_Stone", "Kidney_Tumor",
    "Knee_Normal", "Knee_Osteoarthritis",
    "Lung_Cancer", "Lungs_Normal", "Lungs_TB", "No_Lung_Cancer"
]

# ============================================================
# 🧩 HELPER FUNCTIONS
# ============================================================
def allowed_file_extension(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def correct_exif_orientation(img):
    try:
        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == 'Orientation':
                break
        exif = img._getexif()
        if exif is None:
            return img
        orientation_value = exif.get(orientation, None)
        if orientation_value == 3:
            img = img.rotate(180, expand=True)
        elif orientation_value == 6:
            img = img.rotate(270, expand=True)
        elif orientation_value == 8:
            img = img.rotate(90, expand=True)
    except Exception:
        pass
    return img

def load_and_prepare_image(img):
    if img.mode != "RGB":
        img = img.convert("RGB")
    img = correct_exif_orientation(img)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.2)
    w, h = img.size
    if min(w, h) < 32:
        img = img.resize((max(w, 32), max(h, 32)), Image.BICUBIC)
        w, h = img.size
    min_side = min(w, h)
    left = (w - min_side) // 2
    top = (h - min_side) // 2
    right = left + min_side
    bottom = top + min_side
    img = img.crop((left, top, right, bottom))
    img = img.resize(IMG_SIZE, Image.BICUBIC)
    return img

def pil_to_model_array(pil_img):
    arr = np.array(pil_img)
    if arr.ndim != 3 or arr.shape[2] != 3:
        arr = np.stack([arr]*3, axis=-1) if arr.ndim == 2 else arr[:, :, :3]
    arr = arr.astype(np.float32)
    arr = tf.keras.applications.resnet50.preprocess_input(arr)
    return arr

def predict_with_tta(img):
    logger.info("🧮 Running prediction (TTA mode)...")
    base = load_and_prepare_image(img)
    imgs = [base, ImageOps.mirror(base)]
    arrays = np.stack([pil_to_model_array(im) for im in imgs], axis=0)
    preds = model.predict(arrays, verbose=0)
    avg = np.mean(preds, axis=0)
    class_idx = int(np.argmax(avg))
    confidence = float(avg[class_idx])
    pred_class = class_names[class_idx]
    logger.info(f"✅ Prediction complete: {pred_class} ({confidence:.3f})")
    return pred_class, confidence

def decode_base64_image(data):
    try:
        image_bytes = base64.b64decode(data)
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        return img
    except Exception as e:
        raise ValueError(f"Invalid base64 image data: {e}")

# ============================================================
# 🚀 FLASK APP
# ============================================================
app = Flask(__name__)
CORS(app)

@app.before_request
def log_request_info():
    logger.info(f"➡️ Incoming {request.method} {request.path}")
    if request.is_json:
        logger.info(f"📦 Payload keys: {list(request.get_json().keys())}")

@app.after_request
def log_response_info(response):
    logger.info(f"⬅️ Response: {response.status}")
    return response

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "xray", "model_loaded": True}), 200

@app.route("/predict", methods=["POST"])
def predict():
    logger.info("📩 Received prediction request.")
    data = request.get_json()
    if not data or "payload" not in data:
        logger.warning("❌ Missing payload.")
        return jsonify({"error": "Missing payload"}), 400

    payload = data["payload"]
    img = None

    # ---- IMAGE INPUT ----
    try:
        if "image_base64" in payload:
            img = decode_base64_image(payload["image_base64"])
            logger.info("🖼️ Image decoded from base64 successfully.")
        elif "image_path" in payload:
            if not os.path.exists(payload["image_path"]):
                logger.error(f"❌ Image path not found: {payload['image_path']}")
                return jsonify({"error": "File not found", "path": payload["image_path"]}), 400
            img = Image.open(payload["image_path"]).convert("RGB")
            logger.info(f"🖼️ Image loaded from path: {payload['image_path']}")
        else:
            logger.error("❌ No image provided in payload.")
            return jsonify({"error": "No image provided"}), 400
    except Exception as e:
        logger.exception("❌ Error while loading image.")
        return jsonify({"error": "Image loading failed", "message": str(e)}), 400

    # ---- PREDICTION ----
    try:
        pred_class, confidence = predict_with_tta(img)
    except Exception as e:
        logger.exception("❌ Prediction failed.")
        return jsonify({"error": "Prediction failed", "message": str(e)}), 500

    result = {
        "prediction": {
            "class": pred_class,
            "confidence": confidence
        },
        "patient_info": {
            "age": payload.get("age"),
            "weight": payload.get("weight"),
            "symptoms": payload.get("symptoms", ""),
            "body_part": payload.get("body_part", "")
        }
    }

    logger.info("✅ Returning prediction result.")
    return jsonify(result), 200

# ============================================================
# 🧰 SERVER START
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ("true", "1", "t")
    logger.info(f"🚀 Starting MEDISCOPE X-Ray Service on 0.0.0.0:{port} (debug={debug_mode})")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
