import cv2
import numpy as np
import requests
import time

# --- CONFIGURATION ---
PI_IP = "100.88.38.105"
STREAM_URL = f"http://{PI_IP}/webcam/?action=stream"
PAUSE_URL = f"http://{PI_IP}:7125/printer/print/pause"

# Vision Thresholds
# How many pixels of movement constitutes an "anomaly"? 
# (You will tune this based on your specific camera distance/resolution)
ANOMALY_AREA_THRESHOLD = 15000 
# How many consecutive bad frames before we actually pause? (Prevents false alarms from glitches)
MAX_ANOMALY_FRAMES = 30 

def emergency_pause():
    """Fires the API command to halt the machine."""
    print("\n🚨 CRITICAL FAILURE DETECTED: SPAGHETTI OR DETACHMENT!")
    print("🚨 Sending Emergency Pause command to Moonraker...")
    try:
        res = requests.post(PAUSE_URL, timeout=5)
        if res.ok:
            print("✅ Printer Paused Successfully. Awaiting operator intervention.")
        else:
            print(f"⚠️ Pause failed with status code: {res.status_code}")
    except Exception as e:
        print(f"🔴 Network error sending pause: {e}")

def run_vision_watchdog():
    print(f"👁️ Indus3D Watchdog booting up...")
    print(f"📡 Connecting to camera stream at {PI_IP}...")
    
    cap = cv2.VideoCapture(STREAM_URL)
    
    if not cap.isOpened():
        print("🔴 ERROR: Cannot connect to webcam. Is Tailscale connected?")
        return

    # MOG2 Background Subtractor: This algorithm automatically learns what the "static" 
    # background looks like (the bed, the frame) and isolates only the moving pixels.
    back_sub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=False)
    
    anomaly_counter = 0
    print("🟢 Vision Online. Monitoring kinematic volume...")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️ Stream dropped. Attempting reconnect...")
            time.sleep(2)
            cap = cv2.VideoCapture(STREAM_URL)
            continue

        # 1. Resize frame to a standard 640x480 for fast, consistent mathematical processing
        frame = cv2.resize(frame, (640, 480))
        
        # 2. Extract the moving objects (Returns a black and white mask)
        fg_mask = back_sub.apply(frame)
        
        # 3. Clean up the mask (Erode/Dilate to remove static camera noise/flicker)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        
        # 4. Find the boundaries of the moving blobs
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        total_moving_area = 0
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 500: # Ignore tiny specks of dust
                total_moving_area += area
                # Draw a green bounding box around moving objects for our diagnostic UI
                x, y, w, h = cv2.boundingRect(contour)
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

        # --- AI DECISION LOGIC ---
        
        if total_moving_area > ANOMALY_AREA_THRESHOLD:
            anomaly_counter += 1
            # Flash UI Red
            cv2.rectangle(frame, (0,0), (640, 480), (0, 0, 255), 10)
            cv2.putText(frame, f"ANOMALY DETECTED: {anomaly_counter}/{MAX_ANOMALY_FRAMES}", (20, 40), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
        else:
            # Cool down if the movement stops
            if anomaly_counter > 0:
                anomaly_counter -= 1
                
        # Draw the live area metric on screen
        cv2.putText(frame, f"Kinematic Area: {int(total_moving_area)} px", (20, 450), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

        # TRIGGER THE REFLEX
        if anomaly_counter >= MAX_ANOMALY_FRAMES:
            emergency_pause()
            anomaly_counter = 0 # Reset
            print("⏸️ Watchdog sleeping for 60 seconds to prevent API spam...")
            time.sleep(60)

        # Show the diagnostic windows
        cv2.imshow("Indus3D AI Vision", frame)
        cv2.imshow("Binary Motion Mask", fg_mask)

        # Press 'q' to quit the watchdog
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_vision_watchdog()
