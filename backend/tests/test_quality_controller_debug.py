import time
from digital_twin.quality_controller import QualityController, FLOW_DEADBAND, SPEED_DEADBAND, FLOW_MAX, FLOW_MIN

qc = QualityController()
qc._shaper_loaded = True 
ext_data = {
    "is_extruding": True,
    "expected_flow_mm3_s": 5.0,
    "flow_ratio": 0.8  
}
qc._last_flow_t = 0
now = time.time()
print(f"now: {now}")
print(f"now - _last_flow_t = {now - qc._last_flow_t}")
res = qc._flow_control(ext_data, now)
print(f"res: {res}")
print(f"flow_cmd: {qc._flow_cmd}")
