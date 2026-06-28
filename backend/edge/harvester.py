import cv2
import requests
import time
import os
import numpy as np
from datetime import datetime

PI_IP = "100.88.38.105"
SNAPSHOT_URL = f"http://{PI_IP}/webcam/?action=snapshot"
# Query Klipper's internal memory for our custom macro variable
STATUS_URL = f"http://{PI_IP}:7125/printer/objects/query?gcode_macro%20INDUS_INSPECT"

DATASET_DIR = "dataset/raw_images"
os.makedirs(DATASET_DIR, exist_ok=True)

last_snap_time = 0 

def check_snap_flag():
    """Reads the custom Klipper variable to see if the machine is physically parked."""
    try:
        res = requests.get(STATUS_URL, timeout=2)
        if res.ok:
            data = res.json()
            # Read the custom flag we created in Klipper
            flag = data['result']['status']['gcode_macro INDUS_INSPECT']['snap_flag']
            return int(flag) == 1
    except Exception:
        pass
    return False

def run_harvester():
    global last_snap_time
    print("🌾 Indus3D CNC-Synchronized Harvester Online.")
    print("⏳ Waiting for the hardware sync flag...\n")

    images_collected = 0

    while True:
        # If Klipper explicitly tells us the flag is 1
        if check_snap_flag():
            current_time = time.time()
            
            # 3-second cooldown to prevent double-snapping
            if current_time - last_snap_time > 3:
                try:
                    img_resp = requests.get(SNAPSHOT_URL, timeout=5)
                    if img_resp.status_code == 200:
                        img_array = np.array(bytearray(img_resp.content), dtype=np.uint8)
                        frame = cv2.imdecode(img_array, -1)

                        if frame is not None:
                            # --- ROI CROPPING ---
                            center_y, center_x = 720 // 2, 1280 // 2
                            roi = frame[center_y - 320 : center_y + 320, center_x - 320 : center_x + 320]

                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            filename = f"{DATASET_DIR}/indus_roi_{timestamp}.jpg"
                            
                            cv2.imwrite(filename, roi)
                            images_collected += 1
                            print(f"📸 [{timestamp}] Hardware sync confirmed! Snapped ROI frame #{images_collected}.")
                            
                            last_snap_time = current_time
                except Exception as e:
                    print(f"🔴 Camera fetch error: {e}")
        
        # Poll rapidly 5 times a second to ensure we don't miss the 2-second parking window
        time.sleep(0.2)

if __name__ == "__main__":
    run_harvester()