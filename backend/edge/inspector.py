import cv2
import requests
from ultralytics import YOLO

# --- CONFIGURATION ---
# We will drop the 'best.pt' file from your Windows PC in here later.
# For now, we use the base nano model just to test the code pipeline.
MODEL_PATH = "yolov8n.pt" 
MOONRAKER_URL = "http://100.88.38.105:7125/printer/print/pause"

# Confidence threshold (0.0 to 1.0). If the AI is 80% sure it's a failure, we stop the machine.
CONFIDENCE_THRESHOLD = 0.80  

def load_brain():
    print(f"🧠 Loading Indus3D Visual Cortex ({MODEL_PATH})...")
    return YOLO(MODEL_PATH)

def evaluate_image(model, image_path):
    print(f"📸 Evaluating Region of Interest: {image_path}")
    
    # Run the image through the Neural Network
    results = model(image_path)
    
    # YOLO returns a list of results. We grab the first one.
    result = results[0]
    
    failure_detected = False
    highest_confidence = 0.0
    detected_class = "None"

    # Loop through every bounding box the AI drew
    for box in result.boxes:
        confidence = float(box.conf[0])
        class_id = int(box.cls[0])
        
        # We will map these IDs to your actual Roboflow classes later 
        # (e.g., 0: spaghetti, 1: under-extrusion)
        class_name = model.names[class_id] 
        
        if confidence >= CONFIDENCE_THRESHOLD:
            failure_detected = True
            if confidence > highest_confidence:
                highest_confidence = confidence
                detected_class = class_name

    return failure_detected, detected_class, highest_confidence

def trigger_hardware_halt(reason, confidence):
    """Sends the emergency Pause command to Klipper via Moonraker API."""
    print(f"🚨 CRITICAL FAILURE DETECTED: {reason} ({confidence*100:.1f}%)")
    print("🛑 Transmitting hardware halt command to Klipper...")
    
    try:
        # We use a POST request to tell the printer to pause
        response = requests.post(MOONRAKER_URL, timeout=3)
        if response.ok:
            print("✅ Klipper Paused successfully. Waiting for human intervention.")
        else:
            print(f"⚠️ API Error: Printer refused command (Code: {response.status_code})")
    except Exception as e:
        print(f"🔴 NETWORK OFFLINE. Cannot reach printer: {e}")

if __name__ == "__main__":
    # 1. Boot the AI
    ai_model = load_brain()
    
    # 2. Feed it the calibration cube image you took earlier
    # (Make sure to put that specific image in the same folder as this script)
    test_image = "dataset/raw_images/test_subject.jpg" 
    
    # 3. Evaluate
    is_failing, defect_type, conf = evaluate_image(ai_model, test_image)
    
    # 4. Act
    if is_failing:
        trigger_hardware_halt(defect_type, conf)
    else:
        print("✅ Print is nominal. Continuing operation.")
