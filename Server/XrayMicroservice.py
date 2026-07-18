# x ray
import os
import logging
import requests
from flask import Flask, request, jsonify
import tensorflow as tf
from tensorflow.keras.models import load_model

# ------------------ Logging ------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MEDISCOPE_Server")

# ------------------ Model URLs ------------------
MODEL_HF_H5_URL = "https://huggingface.co/Nikhil2104/x-ray-predictor/resolve/main/final_best_model.h5"
MODEL_HF_KERAS_URL = "https://huggingface.co/Nikhil2104/MEDISCOPE/resolve/main/final_best_model.keras"
LOCAL_H5_PATH = "/tmp/final_best_model.h5"
LOCAL_KERAS_PATH = "/tmp/final_best_model.keras"

app = Flask(__name__)

# ------------------ Helper: Download Model ------------------
def download_model(url, local_path):
    try:
        logger.info(f"🌐 Downloading model from {url} ...")
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        logger.info(f"✅ Model downloaded to {local_path}")
        return local_path
    except Exception as e:
        logger.error(f"❌ Failed to download model: {e}")
        return None

# ------------------ Load Model ------------------
def load_mediscope_model():
    # Force CPU only
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    tf.config.threading.set_intra_op_parallelism_threads(4)
    tf.config.threading.set_inter_op_parallelism_threads(4)
    logger.info("💡 Running TensorFlow on CPU only.")

    # Try Keras .keras format first
    if os.path.exists(LOCAL_KERAS_PATH):
        try:
            model = load_model(LOCAL_KERAS_PATH, compile=False)
            logger.info("✅ Loaded model from local .keras file!")
            return model
        except Exception as e:
            logger.warning(f"⚠️ Local .keras load failed: {e}")

    # Download .keras from HF
    keras_path = download_model(MODEL_HF_KERAS_URL, LOCAL_KERAS_PATH)
    if keras_path:
        try:
            model = load_model(keras_path, compile=False)
            logger.info("✅ Loaded model from HF .keras file!")
            return model
        except Exception as e:
            logger.warning(f"⚠️ HF .keras load failed: {e}")

    # Fallback: H5 format
    if os.path.exists(LOCAL_H5_PATH):
        try:
            model = load_model(LOCAL_H5_PATH, compile=False)
            logger.info("✅ Loaded model from local .h5 file!")
            return model
        except Exception as e:
            logger.warning(f"⚠️ Local H5 load failed: {e}")

    h5_path = download_model(MODEL_HF_H5_URL, LOCAL_H5_PATH)
    if h5_path:
        try:
            model = load_model(h5_path, compile=False)
            logger.info("✅ Loaded model from HF .h5 file!")
            return model
        except Exception as e:
            logger.warning(f"⚠️ HF .h5 load failed: {e}")

    raise RuntimeError("❌ Unable to load MEDISCOPE model from any source.")

# Load model at startup
model = load_mediscope_model()

# ------------------ Flask Endpoint ------------------
# ------------------ Flask Endpoint ------------------
@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.get_json()
        if not data or "payload" not in data:
            return jsonify({"error": "Invalid request format. Expected JSON with 'payload' key."}), 400

        payload = data["payload"]
        if "image_base64" not in payload:
             return jsonify({"error": "Missing 'image_base64' in payload."}), 400

        # Decode base64 image
        import base64
        import io
        from PIL import Image
        import numpy as np

        image_data = base64.b64decode(payload["image_base64"])
        image = Image.open(io.BytesIO(image_data)).convert("RGB")

        # Resize to model's expected input size (160x160 for this model)
        image = image.resize((160, 160))
        image_array = np.array(image) / 255.0
        image_array = np.expand_dims(image_array, axis=0)

        # Predict
        prediction = model.predict(image_array)

        # Convert prediction to readable format
        # This part depends heavily on the specific model's output classes.
        # Check if model has a mapping, otherwise return raw probabilities or index.
        # For now, returning the raw prediction list.
        prediction_list = prediction.tolist()

        return jsonify({
            "message": "Prediction successful",
            "prediction": prediction_list,
            "raw_output": str(prediction)
        }), 200

    except Exception as e:
        logger.error(f"❌ Prediction error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def health_check():
    return "Xray Microservice is running", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "False") == "True")
