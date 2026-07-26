import requests
import base64
import json
import os

# Configuration
XRAY_URL = "http://127.0.0.1:5000/predict"
LAB_URL = "http://127.0.0.1:5001/parse"
INTERPRETER_URL = "http://127.0.0.1:5002/interpret"

def test_xray():
    print("\n--- Testing X-Ray Microservice ---")
    # Create a dummy small image
    from PIL import Image
    import io

    img = Image.new('RGB', (100, 100), color = 'red')
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')

    payload = {
        "payload": {
            "image_base64": img_base64,
            "body_part": "chest"
        }
    }

    try:
        response = requests.post(XRAY_URL, json=payload, timeout=5)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text[:200]}")
    except Exception as e:
        print(f"Failed: {e}")

def test_interpreter():
    print("\n--- Testing Interpreter Microservice ---")
    payload = {
        "username": "TestUser",
        "language": "english",
        "type": "report",
        "predictions": json.dumps({"test": "data"})
    }
    try:
        response = requests.post(INTERPRETER_URL, json=payload, timeout=5)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text[:200]}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    print("Starting tests... (Ensure services are running)")
    test_xray()
    test_interpreter()
